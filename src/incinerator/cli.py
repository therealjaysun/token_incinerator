from __future__ import annotations

import json
import os
import random
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import click

from incinerator.budget import is_exhausted, make_initial_state
from incinerator.daemon import PidFileManager, fork_daemon, is_daemon_process
from incinerator.logger import FileLogger, StderrLogger
from incinerator.loop import run_burn_loop
from incinerator.repo import walk_repo
from incinerator.runner import ClaudeRunner, check_claude_auth
from incinerator.schemas import DaemonConfig
from incinerator.watch import watch_loop

_STATE_DIR = str(Path.home() / ".incinerator")


class _RootHelpGroup(click.Group):
    """Include each subcommand's options in `incinerator --help` (not just command names)."""

    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        super().format_help(ctx, formatter)
        formatter.write_paragraph()
        formatter.write_heading("Commands (full)")
        for name in sorted(self.list_commands(ctx)):
            cmd = self.get_command(ctx, name)
            if cmd is None or getattr(cmd, "hidden", False):
                continue
            sub_ctx = click.Context(cmd, parent=ctx, info_name=name)
            formatter.write_paragraph()
            cmd.format_help(sub_ctx, formatter)


@click.group(cls=_RootHelpGroup)
def cli() -> None:
    """Token Incinerator — burn Claude tokens in the background because you're a modern day luddite"""


@cli.command()
@click.option("--repo", required=True, type=click.Path(exists=True), help="Path to the target repository")
@click.option("--tokens", default=None, type=int, help="Token budget (stop after N tokens)")
@click.option("--usd", default=None, type=float, help="USD budget (stop after $N)")
@click.option("--duration", default=None, type=str, help="Duration budget e.g. 2h, 30m, 3600s")
@click.option("--rate", default=5000, type=int, help="Target tokens/hour (controls pacing, only used with --statistical)")
@click.option("--model", default=None, help="Claude model to use (default: Claude's own default)")
@click.option("--working-hours-only", is_flag=True, default=False, help="Only burn during 9am-5pm")
@click.option("--statistical", is_flag=True, default=False, help="Use Poisson-distributed request timing to mimic natural pacing (default: fire continuously)")
def start(
    repo: str,
    tokens: Optional[int],
    usd: Optional[float],
    duration: Optional[str],
    rate: int,
    model: Optional[str],
    working_hours_only: bool,
    statistical: bool,
) -> None:
    """Start the incinerator. Opens the live watch display automatically."""
    ok, auth_error = check_claude_auth()
    if not ok:
        click.echo(f"Error: {auth_error}", err=True)
        sys.exit(1)

    mgr = PidFileManager(state_dir=_STATE_DIR)
    existing = mgr.read()
    if existing and mgr.is_process_alive(existing["pid"]):
        click.echo(f"Incinerator already running (PID {existing['pid']}). Run 'incinerator stop' first.", err=True)
        sys.exit(1)

    duration_seconds = _parse_duration(duration) if duration else None

    config = DaemonConfig(
        repo_path=str(Path(repo).resolve()),
        rate_per_hour=rate,
        model=model,
        working_hours_only=working_hours_only,
        statistical=statistical,
        budget_tokens=tokens,
        budget_usd=usd,
        budget_duration_seconds=duration_seconds,
    )

    pid = fork_daemon(config, state_dir=_STATE_DIR)
    click.echo(f"Incinerator started (PID {pid})")
    if tokens:
        click.echo(f"Budget: {tokens:,} tokens")
    if usd:
        click.echo(f"Budget: ${usd:.2f}")
    if duration:
        click.echo(f"Duration: {duration}")
    if statistical:
        click.echo(f"Mode: statistical ({rate:,} tokens/hr target)")
    else:
        click.echo("Mode: continuous (no delay between requests)")
    click.echo("")

    try:
        watch_loop(state_dir=_STATE_DIR)
    except KeyboardInterrupt:
        click.echo("\nDetached from watch. Daemon continues running in the background.")
        click.echo("  incinerator watch    — reconnect to live display")
        click.echo("  incinerator stop     — stop the daemon")


@cli.command()
def stop() -> None:
    """Stop the background incinerator."""
    mgr = PidFileManager(state_dir=_STATE_DIR)
    result = mgr.read()
    if result is None or not mgr.is_process_alive(result["pid"]):
        click.echo("Incinerator is not running.")
        mgr.remove()
        return
    try:
        os.kill(result["pid"], signal.SIGTERM)
        mgr.remove()
        click.echo(f"Incinerator stopped (PID {result['pid']}).")
    except ProcessLookupError:
        mgr.remove()
        click.echo("Process already gone.")


@cli.command()
def status() -> None:
    """Show incinerator status and spend so far."""
    mgr = PidFileManager(state_dir=_STATE_DIR)
    result = mgr.read()
    if result is None or not mgr.is_process_alive(result["pid"]):
        click.echo("Status: STOPPED")
        return

    click.echo(f"Status: RUNNING (PID {result['pid']})")
    config: DaemonConfig = result["config"]
    click.echo(f"Repo:   {config.repo_path}")
    click.echo(f"Model:  {config.model or '(claude default)'}")
    click.echo(f"Rate:   {config.rate_per_hour:,} tokens/hr")

    state_file = Path(_STATE_DIR) / "state.json"
    if state_file.exists():
        try:
            from incinerator.schemas import BudgetState
            state = BudgetState.model_validate_json(state_file.read_text())
            click.echo(f"\nSpend so far:")
            click.echo(f"  Tokens:  {state.total_tokens_used:,}")
            click.echo(f"  Cost:    ${state.total_cost_usd:.4f}")
            click.echo(f"  Runs:    {state.run_count}")
            if state.last_run_at:
                click.echo(f"  Last:    {state.last_run_at.strftime('%H:%M:%S')}")
        except Exception:
            pass


@cli.command()
def watch() -> None:
    """Live token counter and progress display. Updates every second."""
    watch_loop(state_dir=_STATE_DIR)


@cli.command(name="__daemon__", hidden=True)
@click.argument("config_json")
def daemon_entry(config_json: str) -> None:
    """Internal: daemon process entry point."""
    config = DaemonConfig.model_validate_json(config_json)
    state_dir = os.environ.get("INCINERATOR_STATE_DIR", _STATE_DIR)
    mgr = PidFileManager(state_dir=state_dir)
    mgr.write(pid=os.getpid(), config=config)

    logger = FileLogger(log_path=str(Path(state_dir) / "incinerator.log"))
    logger.log({"event": "daemon_started", "pid": os.getpid(), "repo": config.repo_path})

    repo_files = walk_repo(config.repo_path, max_files=500)
    if not repo_files:
        logger.log({"event": "error", "message": f"No files found in {config.repo_path}"})
        mgr.remove()
        sys.exit(1)

    logger.log({"event": "repo_scanned", "file_count": len(repo_files)})

    runner = ClaudeRunner(model=config.model, claude_path=config.claude_path)
    initial_state = make_initial_state()
    state_file = Path(state_dir) / "state.json"
    current_state = [initial_state]  # mutable cell so SIGTERM handler always has latest

    # Deterministic seed derived from session start time — same session = same delay sequence
    rng = random.Random(int(initial_state.started_at.timestamp()))

    def save_state(s: "BudgetState") -> None:
        current_state[0] = s
        state_file.write_text(s.model_dump_json())

    def delay_fn(ms: float, s: "BudgetState") -> None:
        from incinerator.schemas import BudgetState as _BS
        if ms > 0:
            next_run = datetime.now(tz=timezone.utc) + timedelta(milliseconds=ms)
            s = _BS(
                total_tokens_used=s.total_tokens_used,
                total_cost_usd=s.total_cost_usd,
                run_count=s.run_count,
                started_at=s.started_at,
                last_run_at=s.last_run_at,
                next_run_at=next_run,
            )
        save_state(s)
        time.sleep(ms / 1000)

    def handle_sigterm(signum: int, frame: object) -> None:
        logger.log({"event": "daemon_stopped", "reason": "SIGTERM"})
        state_file.write_text(current_state[0].model_dump_json())
        mgr.remove()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_sigterm)

    final_state = run_burn_loop(
        config=config,
        repo_files=repo_files,
        initial_state=initial_state,
        runner=runner,
        logger=logger,
        delay_fn=delay_fn,
        random_fn=rng.random,
    )

    from incinerator.budget import is_exhausted as _is_exhausted
    stop_reason = "budget_exhausted" if _is_exhausted(final_state, config) else "fatal_error"
    logger.log({"event": "daemon_stopped", "reason": stop_reason})
    save_state(final_state)
    mgr.remove()


def _parse_duration(s: str) -> int:
    s = s.strip().lower()
    if s.endswith("h"):
        return int(s[:-1]) * 3600
    if s.endswith("m"):
        return int(s[:-1]) * 60
    if s.endswith("s"):
        return int(s[:-1])
    return int(s)


if __name__ == "__main__":
    cli()
