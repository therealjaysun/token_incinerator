import random
from pathlib import Path

import pytest

from incinerator.budget import make_initial_state
from incinerator.loop import run_burn_loop
from incinerator.runner import check_claude_auth, is_auth_error
from incinerator.schemas import DaemonConfig
from incinerator.types import BurnPrompt, RepoFile, RunResult

FIXTURES = Path(__file__).parent / "fixtures"


def make_config(**kwargs) -> DaemonConfig:
    defaults = dict(repo_path="/repo", budget_tokens=100_000)
    defaults.update(kwargs)
    return DaemonConfig(**defaults)


def make_file() -> RepoFile:
    return RepoFile(
        absolute_path="/repo/app.py",
        relative_path="app.py",
        extension=".py",
        size_bytes=1000,
        category="source",
    )


class FakeLogger:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def log(self, event: dict) -> None:
        self.events.append(event)


class TestIsAuthError:
    def test_detects_not_logged_in(self):
        assert is_auth_error("Error: not logged in")

    def test_detects_please_login(self):
        assert is_auth_error("Please login to continue")

    def test_detects_401(self):
        assert is_auth_error("HTTP 401 Unauthorized")

    def test_detects_api_key(self):
        assert is_auth_error("Invalid API key provided")

    def test_case_insensitive(self):
        assert is_auth_error("NOT LOGGED IN")

    def test_ignores_unrelated_errors(self):
        assert not is_auth_error("rate limit exceeded")
        assert not is_auth_error("timeout after 300 seconds")
        assert not is_auth_error("model not found")


class TestCheckClaudeAuth:
    def test_returns_false_when_claude_not_on_path(self):
        ok, msg = check_claude_auth(claude_path="/nonexistent/claude")
        assert ok is False
        assert "not found" in msg.lower() or "install" in msg.lower()

    def test_returns_true_for_successful_fake_claude(self, tmp_path: Path):
        script = tmp_path / "claude"
        script.write_text("""#!/bin/bash
cat <<'EOF'
{"type":"result","is_error":false,"total_cost_usd":0.0001,"usage":{"input_tokens":5,"output_tokens":2,"cache_read_input_tokens":0},"duration_ms":50,"result":"OK"}
EOF
""")
        script.chmod(0o755)
        ok, msg = check_claude_auth(claude_path=str(script))
        assert ok is True
        assert msg == ""

    def test_returns_false_for_auth_error_fake_claude(self, tmp_path: Path):
        script = tmp_path / "claude"
        script.write_text("""#!/bin/bash
echo "Error: not logged in" >&2
exit 1
""")
        script.chmod(0o755)
        ok, msg = check_claude_auth(claude_path=str(script))
        assert ok is False
        assert "not logged in" in msg.lower() or "claude login" in msg.lower()

    def test_returns_false_for_generic_failure(self, tmp_path: Path):
        script = tmp_path / "claude"
        script.write_text("""#!/bin/bash
echo "unexpected internal error" >&2
exit 2
""")
        script.chmod(0o755)
        ok, msg = check_claude_auth(claude_path=str(script))
        assert ok is False

    def test_returns_false_for_usage_limit_error(self, tmp_path: Path):
        script = tmp_path / "claude"
        script.write_text("""#!/bin/bash
echo "Error: usage limit reached for your account" >&2
exit 1
""")
        script.chmod(0o755)
        ok, msg = check_claude_auth(claude_path=str(script))
        assert ok is False
        assert "usage limit" in msg.lower()


class TestLoopAbortOnAuthFailure:
    def make_auth_fail_result(self) -> RunResult:
        return RunResult(
            prompt_category="review",
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cost_usd=0.0,
            duration_ms=0,
            success=False,
            error_message="claude exited 1: Error: not logged in",
        )

    def test_loop_aborts_immediately_on_auth_error(self):
        call_count = 0
        auth_result = self.make_auth_fail_result()

        class AuthFailRunner:
            def run(self, prompt: BurnPrompt) -> RunResult:
                nonlocal call_count
                call_count += 1
                return auth_result

        logger = FakeLogger()
        run_burn_loop(
            config=make_config(),
            repo_files=[make_file()],
            initial_state=make_initial_state(),
            runner=AuthFailRunner(),
            logger=logger,
            delay_fn=lambda ms, s: None,
            random_fn=random.Random(42).random,
        )

        assert call_count == 1
        event_names = [e.get("event") for e in logger.events]
        assert "fatal_error" in event_names
        fatal = next(e for e in logger.events if e.get("event") == "fatal_error")
        assert fatal.get("reason") == "auth_failure"

    def test_loop_aborts_after_max_consecutive_failures(self):
        call_count = 0
        generic_fail = RunResult(
            prompt_category="review",
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cost_usd=0.0,
            duration_ms=0,
            success=False,
            error_message="rate limit exceeded",
        )

        class FailRunner:
            def run(self, prompt: BurnPrompt) -> RunResult:
                nonlocal call_count
                call_count += 1
                return generic_fail

        logger = FakeLogger()
        run_burn_loop(
            config=make_config(),
            repo_files=[make_file()],
            initial_state=make_initial_state(),
            runner=FailRunner(),
            logger=logger,
            delay_fn=lambda ms, s: None,
            random_fn=random.Random(42).random,
        )

        assert call_count == 3  # _MAX_CONSECUTIVE_FAILURES
        fatal = next(e for e in logger.events if e.get("event") == "fatal_error")
        assert fatal.get("reason") == "too_many_failures"

    def test_failure_counter_resets_after_success(self):
        call_count = 0
        fail = RunResult(
            prompt_category="review", input_tokens=0, output_tokens=0,
            cache_read_tokens=0, cost_usd=0.0, duration_ms=0, success=False,
            error_message="transient error",
        )
        # Budget: 600 tokens, success result: 300+100 = 400 tokens. After 1 success we're under.
        # After 2nd success we hit 800 >= 600. So: fail, fail, success, fail, fail, success → stops.
        success = RunResult(
            prompt_category="review", input_tokens=300, output_tokens=100,
            cache_read_tokens=0, cost_usd=0.01, duration_ms=500, success=True,
        )
        responses = [fail, fail, success, fail, fail, success]
        idx = 0

        class MixedRunner:
            def run(self, prompt: BurnPrompt) -> RunResult:
                nonlocal idx, call_count
                call_count += 1
                r = responses[idx % len(responses)]
                idx += 1
                return r

        logger = FakeLogger()
        run_burn_loop(
            config=make_config(budget_tokens=600),
            repo_files=[make_file()],
            initial_state=make_initial_state(),
            runner=MixedRunner(),
            logger=logger,
            delay_fn=lambda ms, s: None,
            random_fn=random.Random(42).random,
        )

        event_names = [e.get("event") for e in logger.events]
        assert "fatal_error" not in event_names
        assert "budget_exhausted" in event_names


class TestLoopAbortOnUsageLimit:
    def test_loop_aborts_immediately_on_usage_limit(self):
        call_count = 0
        usage_limited = RunResult(
            prompt_category="review",
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cost_usd=0.0,
            duration_ms=0,
            success=False,
            error_message="claude exited 1: usage limit reached",
        )

        class UsageLimitRunner:
            def run(self, prompt: BurnPrompt) -> RunResult:
                nonlocal call_count
                call_count += 1
                return usage_limited

        logger = FakeLogger()
        run_burn_loop(
            config=make_config(),
            repo_files=[make_file()],
            initial_state=make_initial_state(),
            runner=UsageLimitRunner(),
            logger=logger,
            delay_fn=lambda ms, s: None,
            random_fn=random.Random(42).random,
        )

        assert call_count == 1
        fatal = next(e for e in logger.events if e.get("event") == "fatal_error")
        assert fatal.get("reason") == "usage_limit"
        assert "usage limit" in (fatal.get("message") or "").lower()
