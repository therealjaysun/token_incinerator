from __future__ import annotations

import threading
from typing import Callable, Protocol

from incinerator.budget import apply_run_result, is_exhausted
from incinerator.prompts import generate_prompt
from incinerator.repo import compute_file_weights, sample_weighted_files
from incinerator.runner import is_auth_error, is_usage_limit_error
from incinerator.schemas import BudgetState, DaemonConfig
from incinerator.timing import (
    is_within_work_window,
    sample_exponential_ms,
    seconds_until_work_window,
)
from incinerator.types import BurnPrompt, PromptCategory, RepoFile, RunResult

_CATEGORIES: list[PromptCategory] = [
    "review", "refactor", "security_audit", "doc_generation", "architecture"
]

_FILES_PER_PROMPT = 5
_MAX_CONSECUTIVE_FAILURES = 3
_HEARTBEAT_INTERVAL_SECONDS = 30
_MAX_OFF_HOURS_SLEEP_SECONDS = 300.0


class Runner(Protocol):
    def run(self, prompt: BurnPrompt) -> RunResult: ...


class Logger(Protocol):
    def log(self, event: dict) -> None: ...


def _default_local_hour() -> int:
    from datetime import datetime
    return datetime.now().hour


def run_burn_loop(
    config: DaemonConfig,
    repo_files: list[RepoFile],
    initial_state: BudgetState,
    runner: Runner,
    logger: Logger,
    delay_fn: Callable[[float, BudgetState], None],
    random_fn: Callable[[], float],
    local_hour_fn: Callable[[], int] = _default_local_hour,
) -> BudgetState:
    state = initial_state
    weighted = compute_file_weights(repo_files)
    category_index = 0
    consecutive_failures = 0
    first_run = True

    while not is_exhausted(state, config):
        if config.working_hours_only:
            hour = local_hour_fn()
            if not is_within_work_window(hour):
                wait_s = seconds_until_work_window(hour)
                sleep_s = min(wait_s, _MAX_OFF_HOURS_SLEEP_SECONDS)
                logger.log({
                    "event": "outside_work_hours",
                    "current_hour": hour,
                    "wait_seconds": wait_s,
                    "sleep_seconds": sleep_s,
                })
                delay_fn(sleep_s * 1000, state)
                continue

        category = _CATEGORIES[category_index % len(_CATEGORIES)]
        category_index += 1

        files = sample_weighted_files(weighted, count=_FILES_PER_PROMPT, random_fn=random_fn)
        if not files:
            files = repo_files[:_FILES_PER_PROMPT]

        prompt = generate_prompt(category=category, files=files, random_fn=random_fn)

        logger.log({"event": "prompt_dispatched", "category": category})

        result = _run_with_heartbeat(runner, prompt, logger, category)
        state = apply_run_result(state, result)

        logger.log({"event": "run_complete", "result": {
            "success": result.success,
            "cost_usd": result.cost_usd,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "error": result.error_message,
        }})

        if not result.success:
            consecutive_failures += 1
            error_msg = result.error_message or ""
            if is_auth_error(error_msg):
                logger.log({
                    "event": "fatal_error",
                    "reason": "auth_failure",
                    "message": "Claude is not logged in. Run 'claude login' then restart the incinerator.",
                })
                return state
            if is_usage_limit_error(error_msg):
                logger.log({
                    "event": "fatal_error",
                    "reason": "usage_limit",
                    "message": (
                        "Claude appears to be at a usage limit. "
                        "Wait for your limit window to reset, then restart the incinerator."
                    ),
                })
                return state
            if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                logger.log({
                    "event": "fatal_error",
                    "reason": "too_many_failures",
                    "message": f"{consecutive_failures} consecutive failures — last error: {error_msg}",
                })
                return state
        else:
            consecutive_failures = 0

        if is_exhausted(state, config):
            logger.log({"event": "budget_exhausted"})
            break

        if first_run or not config.statistical:
            delay_ms = 0.0 if first_run else 3_600_000 / config.rate_per_hour
        if config.statistical and not first_run:
            delay_ms = sample_exponential_ms(
                rate_per_hour=config.rate_per_hour,
                random_fn=random_fn,
            )
        first_run = False
        delay_fn(delay_ms, state)

    return state


def _run_with_heartbeat(
    runner: Runner,
    prompt: BurnPrompt,
    logger: Logger,
    category: PromptCategory,
) -> RunResult:
    stop = threading.Event()

    def beat() -> None:
        elapsed = 0
        while not stop.wait(_HEARTBEAT_INTERVAL_SECONDS):
            elapsed += _HEARTBEAT_INTERVAL_SECONDS
            logger.log({"event": "waiting_for_claude", "category": category, "elapsed_seconds": elapsed})

    t = threading.Thread(target=beat, daemon=True)
    t.start()
    try:
        return runner.run(prompt)
    finally:
        stop.set()
        t.join(timeout=1)
