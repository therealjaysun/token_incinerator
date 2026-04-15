from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from rich.columns import Columns
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from incinerator.schemas import BudgetState, DaemonConfig


def _fmt_elapsed(seconds: float) -> str:
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}h {m:02d}m {s:02d}s"
    if m > 0:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _tokens_per_hour(tokens: int, elapsed_seconds: float) -> float:
    if elapsed_seconds < 1:
        return 0.0
    return tokens / elapsed_seconds * 3600


def elapsed_from_state(state: "BudgetState", now: Optional[datetime] = None) -> float:
    _now = now or datetime.now(tz=timezone.utc)
    return (_now - state.started_at).total_seconds()


def _fmt_next_run(next_run_at: Optional[datetime]) -> str:
    if next_run_at is None:
        return "now"
    now = datetime.now(tz=timezone.utc)
    remaining = (next_run_at - now).total_seconds()
    if remaining <= 0:
        return "now"
    return f"in {_fmt_elapsed(remaining)}"


def render_display(
    state: BudgetState,
    config: DaemonConfig,
    elapsed_seconds: float,
    is_running: bool,
) -> object:
    status_text = Text("● RUNNING", style="bold green") if is_running else Text("■ STOPPED", style="bold red")

    # --- Stats table ---
    stats = Table.grid(padding=(0, 2))
    stats.add_column(style="dim", justify="right")
    stats.add_column(justify="left")

    rate = _tokens_per_hour(state.total_tokens_used, elapsed_seconds)

    stats.add_row("Tokens burned", f"[bold]{state.total_tokens_used:,}[/bold]")
    stats.add_row("Cost", f"[bold green]${state.total_cost_usd:.4f}[/bold green]")
    stats.add_row("Runs completed", str(state.run_count))
    stats.add_row("Avg rate", f"{rate:,.0f} tokens/hr")
    stats.add_row("Elapsed", _fmt_elapsed(elapsed_seconds))
    stats.add_row("Repo", config.repo_path)
    stats.add_row("Model", config.model or "(claude default)")

    if state.last_run_at:
        stats.add_row("Last run", state.last_run_at.strftime("%H:%M:%S UTC"))

    if is_running:
        if config.statistical:
            stats.add_row("Next run", _fmt_next_run(state.next_run_at))
        else:
            stats.add_row("Mode", "continuous")

    # --- Budget progress ---
    budget_lines: list[object] = []

    if config.budget_tokens is not None:
        pct = min(100.0, state.total_tokens_used / config.budget_tokens * 100)
        bar = _ascii_bar(pct, width=30)
        budget_lines.append(Text(
            f"  Tokens  {bar} {state.total_tokens_used:,} / {config.budget_tokens:,}  ({pct:.1f}%)"
        ))

    if config.budget_usd is not None:
        pct = min(100.0, state.total_cost_usd / config.budget_usd * 100)
        bar = _ascii_bar(pct, width=30)
        budget_lines.append(Text(
            f"  USD     {bar} ${state.total_cost_usd:.4f} / ${config.budget_usd:.2f}  ({pct:.1f}%)"
        ))

    if config.budget_duration_seconds is not None:
        pct = min(100.0, elapsed_seconds / config.budget_duration_seconds * 100)
        bar = _ascii_bar(pct, width=30)
        remaining = max(0, config.budget_duration_seconds - elapsed_seconds)
        budget_lines.append(Text(
            f"  Time    {bar} {_fmt_elapsed(elapsed_seconds)} / "
            f"{_fmt_elapsed(config.budget_duration_seconds)}  ({remaining:.0f}s left)"
        ))

    if not budget_lines:
        budget_lines.append(Text("  No budget set — running until stopped", style="dim"))

    budget_panel = Panel(
        Group(*budget_lines),
        title="Budget",
        border_style="dim",
        padding=(0, 1),
    )

    header = Panel(
        Group(status_text, Text(""), stats),
        title="[bold]Token Incinerator[/bold]",
        border_style="green" if is_running else "red",
        padding=(0, 1),
    )

    return Group(header, budget_panel)


def _ascii_bar(pct: float, width: int = 30) -> str:
    filled = int(width * pct / 100)
    return "[" + "█" * filled + "░" * (width - filled) + "]"


def watch_loop(state_dir: str, poll_interval: float = 1.0) -> None:
    from rich.live import Live

    from incinerator.daemon import PidFileManager

    mgr = PidFileManager(state_dir=state_dir)
    state_file = Path(state_dir) / "state.json"

    try:
        with Live(refresh_per_second=2, screen=False) as live:
            while True:
                pid_info = mgr.read()
                is_running = pid_info is not None and mgr.is_process_alive(pid_info["pid"])
                config = pid_info["config"] if pid_info else None

                if state_file.exists():
                    try:
                        state = BudgetState.model_validate_json(state_file.read_text())
                    except Exception:
                        state = _empty_state()
                else:
                    state = _empty_state()

                if config is None:
                    config = DaemonConfig(repo_path="(not running)")

                live.update(render_display(
                    state=state,
                    config=config,
                    elapsed_seconds=elapsed_from_state(state),
                    is_running=is_running,
                ))

                if not is_running:
                    time.sleep(0.5)
                    break

                time.sleep(poll_interval)
    except KeyboardInterrupt:
        raise  # let the caller (start command) print the detach message


def _empty_state() -> BudgetState:
    return BudgetState(
        total_tokens_used=0,
        total_cost_usd=0.0,
        run_count=0,
        started_at=datetime.now(tz=timezone.utc),
    )
