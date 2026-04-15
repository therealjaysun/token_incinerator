from __future__ import annotations

import random as _random
import time
from typing import Callable, Protocol

from incinerator.budget import apply_run_result, is_exhausted
from incinerator.prompts import generate_prompt
from incinerator.repo import compute_file_weights, sample_weighted_files
from incinerator.runner import is_auth_error
from incinerator.schemas import BudgetState, DaemonConfig
from incinerator.timing import sample_exponential_ms
from incinerator.types import BurnPrompt, PromptCategory, RepoFile, RunResult

_CATEGORIES: list[PromptCategory] = [
    "review", "refactor", "security_audit", "doc_generation", "architecture"
]

_FILES_PER_PROMPT = 5
_MAX_CONSECUTIVE_FAILURES = 3


class Runner(Protocol):
    def run(self, prompt: BurnPrompt) -> RunResult: ...


class Logger(Protocol):
    def log(self, event: dict) -> None: ...


def run_burn_loop(
    config: DaemonConfig,
    repo_files: list[RepoFile],
    initial_state: BudgetState,
    runner: Runner,
    logger: Logger,
    delay_fn: Callable[[float, BudgetState], None],
    random_fn: Callable[[], float],
) -> BudgetState:
    state = initial_state
    weighted = compute_file_weights(repo_files)
    category_index = 0
    consecutive_failures = 0

    while not is_exhausted(state, config):
        category = _CATEGORIES[category_index % len(_CATEGORIES)]
        category_index += 1

        files = sample_weighted_files(weighted, count=_FILES_PER_PROMPT, random_fn=random_fn)
        if not files:
            files = repo_files[:_FILES_PER_PROMPT]

        prompt = generate_prompt(category=category, files=files, random_fn=random_fn)

        logger.log({"event": "prompt_dispatched", "category": category})

        result = runner.run(prompt)
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
                return
            if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                logger.log({
                    "event": "fatal_error",
                    "reason": "too_many_failures",
                    "message": f"{consecutive_failures} consecutive failures — last error: {error_msg}",
                })
                return
        else:
            consecutive_failures = 0

        if is_exhausted(state, config):
            logger.log({"event": "budget_exhausted"})
            break

        delay_ms = sample_exponential_ms(
            rate_per_hour=config.rate_per_hour,
            random_fn=random_fn,
        )
        delay_fn(delay_ms, state)

    return state
