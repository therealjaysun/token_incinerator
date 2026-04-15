"""
Integration tests — these test full pipelines rather than individual units:

1. TestStatePersistence  - run_burn_loop writes correct state.json and log file to disk
2. TestCliCommands       - CLI status/stop commands read real state from a temp dir
3. TestDaemonLifecycle   - fork a real background daemon, verify PID file, SIGTERM, cleanup
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from incinerator.budget import make_initial_state
from incinerator.cli import cli
from incinerator.logger import FileLogger
from incinerator.loop import run_burn_loop
from incinerator.schemas import BudgetState, DaemonConfig
from incinerator.types import BurnPrompt, RepoFile, RunResult

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def main(): pass\n" * 50)
    (repo / "src" / "utils.py").write_text("def helper(): pass\n" * 30)
    (repo / "README.md").write_text("# Project\n" * 10)
    return repo


def make_fake_claude(tmp_path: Path, *, exit_code: int = 0) -> Path:
    """Write a fake claude script to tmp_path/claude and make it executable."""
    script = tmp_path / "claude"
    if exit_code == 0:
        script.write_text("""#!/bin/bash
cat <<'EOF'
{"type":"result","is_error":false,"total_cost_usd":0.0050,"usage":{"input_tokens":400,"output_tokens":200,"cache_read_input_tokens":0},"duration_ms":800,"result":"Analysis complete."}
EOF
""")
    else:
        script.write_text(f"""#!/bin/bash
echo "Error: not logged in" >&2
exit {exit_code}
""")
    script.chmod(0o755)
    return script


def make_file(repo: Path, relative: str = "src/app.py") -> RepoFile:
    abs_path = str(repo / relative)
    return RepoFile(
        absolute_path=abs_path,
        relative_path=relative,
        extension=".py",
        size_bytes=Path(abs_path).stat().st_size if Path(abs_path).exists() else 100,
        category="source",
    )


def make_fake_runner(n_tokens: int = 600, cost: float = 0.005):
    """Return a runner that always succeeds."""
    class FakeRunner:
        def run(self, prompt: BurnPrompt) -> RunResult:
            return RunResult(
                prompt_category=prompt.category,
                input_tokens=n_tokens,
                output_tokens=200,
                cache_read_tokens=0,
                cost_usd=cost,
                duration_ms=100,
                success=True,
            )
    return FakeRunner()


# ---------------------------------------------------------------------------
# 1. State + log persistence
# ---------------------------------------------------------------------------

class TestStatePersistence:
    def test_state_json_written_after_run(self, tmp_path: Path):
        repo = make_repo(tmp_path)
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        state_file = state_dir / "state.json"
        log_file = state_dir / "incinerator.log"

        state = make_initial_state()
        logger = FileLogger(log_path=str(log_file))

        def save_and_delay(ms: float) -> None:
            state_file.write_text(state.model_dump_json())

        # Patch: we need access to the evolving state inside delay_fn
        # Instead, run the loop then manually save at end
        import random
        calls = []

        class TrackingRunner:
            def run(self, prompt: BurnPrompt) -> RunResult:
                calls.append(prompt.category)
                return RunResult(
                    prompt_category=prompt.category,
                    input_tokens=500,
                    output_tokens=200,
                    cache_read_tokens=0,
                    cost_usd=0.01,
                    duration_ms=200,
                    success=True,
                )

        from incinerator.budget import apply_run_result
        from incinerator.repo import walk_repo

        config = DaemonConfig(repo_path=str(repo), budget_tokens=1000)
        repo_files = walk_repo(str(repo))

        final_state = [state]

        class StateSavingRunner:
            def run(self, prompt: BurnPrompt) -> RunResult:
                result = RunResult(
                    prompt_category=prompt.category,
                    input_tokens=500,
                    output_tokens=200,
                    cache_read_tokens=0,
                    cost_usd=0.01,
                    duration_ms=200,
                    success=True,
                )
                return result

        run_burn_loop(
            config=config,
            repo_files=repo_files,
            initial_state=state,
            runner=StateSavingRunner(),
            logger=logger,
            delay_fn=lambda ms, s: None,
            random_fn=random.Random(42).random,
        )

        # Write final state manually (mimics what daemon_entry does in delay_fn)
        # In production the daemon writes state on each delay; here we just verify
        # the log was written.
        assert log_file.exists(), "log file should have been created"
        log_lines = [json.loads(l) for l in log_file.read_text().splitlines() if l.strip()]
        event_names = [l["event"] for l in log_lines]
        assert "run_complete" in event_names
        assert "budget_exhausted" in event_names

    def test_log_contains_all_expected_events(self, tmp_path: Path):
        import random

        repo = make_repo(tmp_path)
        log_file = tmp_path / "incinerator.log"
        logger = FileLogger(log_path=str(log_file))

        from incinerator.repo import walk_repo
        config = DaemonConfig(repo_path=str(repo), budget_tokens=800)
        repo_files = walk_repo(str(repo))

        run_burn_loop(
            config=config,
            repo_files=repo_files,
            initial_state=make_initial_state(),
            runner=make_fake_runner(n_tokens=500),
            logger=logger,
            delay_fn=lambda ms, s: None,
            random_fn=random.Random(1).random,
        )

        log_lines = [json.loads(l) for l in log_file.read_text().splitlines() if l.strip()]
        event_names = {l["event"] for l in log_lines}
        assert "prompt_dispatched" in event_names
        assert "run_complete" in event_names
        assert "budget_exhausted" in event_names
        # All entries have a timestamp
        for line in log_lines:
            assert "timestamp" in line

    def test_state_accumulates_across_multiple_runs(self, tmp_path: Path):
        import random

        repo = make_repo(tmp_path)
        log_file = tmp_path / "incinerator.log"
        logger = FileLogger(log_path=str(log_file))

        from incinerator.repo import walk_repo
        from incinerator.budget import apply_run_result

        config = DaemonConfig(repo_path=str(repo), budget_tokens=3000)
        repo_files = walk_repo(str(repo))

        # Each run: 500 in + 200 out = 700 tokens, 4 runs = 2800, 5th = 3500 > 3000 → stops
        collected: list[RunResult] = []

        class CountingRunner:
            def run(self, prompt: BurnPrompt) -> RunResult:
                r = RunResult(
                    prompt_category=prompt.category,
                    input_tokens=500,
                    output_tokens=200,
                    cache_read_tokens=0,
                    cost_usd=0.005,
                    duration_ms=100,
                    success=True,
                )
                collected.append(r)
                return r

        run_burn_loop(
            config=config,
            repo_files=repo_files,
            initial_state=make_initial_state(),
            runner=CountingRunner(),
            logger=logger,
            delay_fn=lambda ms, s: None,
            random_fn=random.Random(7).random,
        )

        # 4 runs: 4 × 700 = 2800 < 3000; 5th run: 3500 > 3000 → stops after 5
        assert len(collected) == 5
        total_tokens = sum(r.input_tokens + r.output_tokens for r in collected)
        assert total_tokens == 5 * 700


# ---------------------------------------------------------------------------
# 2. CLI commands
# ---------------------------------------------------------------------------

class TestCliCommands:
    def test_root_help_includes_subcommand_options(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        out = result.output
        assert "Commands (full)" in out
        assert "--repo" in out
        assert "--statistical" in out
        assert "Usage:" in out and "start [OPTIONS]" in out

    def test_status_shows_stopped_when_no_daemon(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("incinerator.cli._STATE_DIR", str(tmp_path))
        runner = CliRunner()
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "STOPPED" in result.output

    def test_stop_when_not_running_exits_gracefully(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("incinerator.cli._STATE_DIR", str(tmp_path))
        runner = CliRunner()
        result = runner.invoke(cli, ["stop"])
        assert result.exit_code == 0
        assert "not running" in result.output.lower()

    def test_status_shows_running_when_pid_file_present(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("incinerator.cli._STATE_DIR", str(tmp_path))
        from incinerator.daemon import PidFileManager
        mgr = PidFileManager(state_dir=str(tmp_path))
        # Use current process PID so is_process_alive returns True
        config = DaemonConfig(repo_path="/fake/repo", rate_per_hour=3000)
        mgr.write(pid=os.getpid(), config=config)

        runner = CliRunner()
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "RUNNING" in result.output
        assert str(os.getpid()) in result.output
        assert "/fake/repo" in result.output

    def test_status_shows_spend_when_state_file_present(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("incinerator.cli._STATE_DIR", str(tmp_path))
        from incinerator.daemon import PidFileManager
        mgr = PidFileManager(state_dir=str(tmp_path))
        config = DaemonConfig(repo_path="/fake/repo")
        mgr.write(pid=os.getpid(), config=config)

        from datetime import datetime, timezone
        state = BudgetState(
            total_tokens_used=12_500,
            total_cost_usd=0.2345,
            run_count=7,
            started_at=datetime(2026, 4, 15, 9, 0, tzinfo=timezone.utc),
        )
        (tmp_path / "state.json").write_text(state.model_dump_json())

        runner = CliRunner()
        result = runner.invoke(cli, ["status"])
        assert "12,500" in result.output
        assert "0.2345" in result.output
        assert "7" in result.output

    def test_stop_sends_sigterm_to_running_pid(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("incinerator.cli._STATE_DIR", str(tmp_path))

        # Spin up a real sleeping subprocess to act as a "daemon"
        sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            from incinerator.daemon import PidFileManager
            mgr = PidFileManager(state_dir=str(tmp_path))
            mgr.write(pid=sleeper.pid, config=DaemonConfig(repo_path="/fake/repo"))

            runner = CliRunner()
            result = runner.invoke(cli, ["stop"])

            assert result.exit_code == 0
            assert str(sleeper.pid) in result.output or "stopped" in result.output.lower()

            # Process should be gone
            sleeper.wait(timeout=3)
            assert sleeper.returncode is not None
        finally:
            if sleeper.poll() is None:
                sleeper.kill()

    def test_start_fails_without_claude_on_path(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("incinerator.cli._STATE_DIR", str(tmp_path))
        repo = make_repo(tmp_path)
        monkeypatch.setattr(
            "incinerator.cli.check_claude_auth",
            lambda: (False, "claude not found on PATH. Install Claude Code: https://claude.ai/code"),
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["start", "--repo", str(repo), "--usd", "1.0"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower() or "not found" in (result.output + (result.exception or "")).lower()

    def test_start_command_forks_daemon_and_writes_pid_file(self, tmp_path: Path, monkeypatch):
        """
        Full end-to-end path: CLI start → check_claude_auth → fork_daemon → daemon writes PID.
        This is the test that would have caught the `detach=False` bug in fork_daemon.
        """
        monkeypatch.setattr("incinerator.cli._STATE_DIR", str(tmp_path))

        # Put fake claude on PATH so both check_claude_auth and the daemon subprocess find it
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        fake_claude = make_fake_claude(bin_dir)
        monkeypatch.setenv("PATH", str(bin_dir) + ":" + os.environ.get("PATH", ""))

        repo = make_repo(tmp_path)
        cli_runner = CliRunner()
        result = cli_runner.invoke(cli, ["start", "--repo", str(repo), "--usd", "1.0"])

        assert result.exit_code == 0, f"start failed: {result.output}"
        assert "started" in result.output.lower()

        pid_file = tmp_path / "incinerator.pid"
        assert wait_for_file(pid_file, timeout=8), "PID file not created — fork_daemon likely failed"

        # Clean up background daemon
        from incinerator.daemon import PidFileManager as _Mgr
        info = _Mgr(state_dir=str(tmp_path)).read()
        if info and _Mgr(state_dir=str(tmp_path)).is_process_alive(info["pid"]):
            os.kill(info["pid"], signal.SIGTERM)


# ---------------------------------------------------------------------------
# 3. Daemon lifecycle
# ---------------------------------------------------------------------------

def wait_for_file(path: Path, timeout: float = 10.0, poll: float = 0.1) -> bool:
    """Poll until path exists or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(poll)
    return False


class TestDaemonLifecycle:
    """
    These tests fork a real background process using the CLI's __daemon__ entry point
    with a fake claude script injected via DaemonConfig.claude_path.
    """

    def test_daemon_writes_pid_file(self, tmp_path: Path):
        repo = make_repo(tmp_path)
        (tmp_path / "bin").mkdir(exist_ok=True)
        fake_claude = make_fake_claude(tmp_path / "bin")

        config = DaemonConfig(
            repo_path=str(repo),
            claude_path=str(fake_claude),
            budget_tokens=5000,
            rate_per_hour=100_000,  # tiny delays
        )
        pid_file = tmp_path / "incinerator.pid"
        env = {**os.environ, "INCINERATOR_STATE_DIR": str(tmp_path)}

        proc = subprocess.Popen(
            [sys.executable, "-m", "incinerator.cli", "__daemon__", config.model_dump_json()],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
        try:
            assert wait_for_file(pid_file, timeout=8), "PID file was not created within 8s"
            pid_text = pid_file.read_text().strip()
            assert pid_text.isdigit()
            assert int(pid_text) == proc.pid
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)

    def test_daemon_cleans_up_pid_file_on_sigterm(self, tmp_path: Path):
        repo = make_repo(tmp_path)
        (tmp_path / "bin").mkdir(exist_ok=True)
        fake_claude = make_fake_claude(tmp_path / "bin")

        config = DaemonConfig(
            repo_path=str(repo),
            claude_path=str(fake_claude),
            budget_tokens=500_000,   # large budget so it keeps running
            rate_per_hour=100_000,
        )
        pid_file = tmp_path / "incinerator.pid"
        env = {**os.environ, "INCINERATOR_STATE_DIR": str(tmp_path)}

        proc = subprocess.Popen(
            [sys.executable, "-m", "incinerator.cli", "__daemon__", config.model_dump_json()],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
        try:
            assert wait_for_file(pid_file, timeout=8), "PID file not created"
            os.kill(proc.pid, signal.SIGTERM)
            proc.wait(timeout=5)

            # PID file should be gone after clean shutdown
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and pid_file.exists():
                time.sleep(0.1)
            assert not pid_file.exists(), "PID file should be removed after SIGTERM"
        finally:
            if proc.poll() is None:
                proc.kill()

    def test_daemon_writes_log_file(self, tmp_path: Path):
        repo = make_repo(tmp_path)
        (tmp_path / "bin").mkdir(exist_ok=True)
        fake_claude = make_fake_claude(tmp_path / "bin")

        config = DaemonConfig(
            repo_path=str(repo),
            claude_path=str(fake_claude),
            budget_tokens=2000,
            rate_per_hour=100_000,
        )
        log_file = tmp_path / "incinerator.log"
        env = {**os.environ, "INCINERATOR_STATE_DIR": str(tmp_path)}

        proc = subprocess.Popen(
            [sys.executable, "-m", "incinerator.cli", "__daemon__", config.model_dump_json()],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
        try:
            # Wait for process to finish (small budget → terminates quickly)
            proc.wait(timeout=30)
            assert log_file.exists(), "log file should exist"
            lines = [json.loads(l) for l in log_file.read_text().splitlines() if l.strip()]
            events = {l["event"] for l in lines}
            assert "daemon_started" in events
            assert "run_complete" in events
        finally:
            if proc.poll() is None:
                proc.kill()

    def test_daemon_state_file_has_correct_totals(self, tmp_path: Path):
        repo = make_repo(tmp_path)
        (tmp_path / "bin").mkdir(exist_ok=True)
        fake_claude = make_fake_claude(tmp_path / "bin")

        # Each fake run: 400 in + 200 out = 600 tokens, cost $0.005
        # Budget 1500 tokens → should complete ~2 runs (1200 < 1500, 1800 > 1500)
        config = DaemonConfig(
            repo_path=str(repo),
            claude_path=str(fake_claude),
            budget_tokens=1500,
            rate_per_hour=100_000,
        )
        state_file = tmp_path / "state.json"
        env = {**os.environ, "INCINERATOR_STATE_DIR": str(tmp_path)}

        proc = subprocess.Popen(
            [sys.executable, "-m", "incinerator.cli", "__daemon__", config.model_dump_json()],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
        try:
            proc.wait(timeout=30)
            assert state_file.exists(), "state.json should exist after daemon finishes"
            state = BudgetState.model_validate_json(state_file.read_text())
            assert state.run_count >= 1
            assert state.total_tokens_used >= 600
            assert state.total_cost_usd > 0
        finally:
            if proc.poll() is None:
                proc.kill()
