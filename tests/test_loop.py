import random
from datetime import datetime, timezone
from typing import Optional

import pytest

from incinerator.budget import make_initial_state
from incinerator.loop import run_burn_loop
from incinerator.schemas import BudgetState, DaemonConfig
from incinerator.types import BurnPrompt, PromptCategory, RepoFile, RunResult


def make_config(**kwargs) -> DaemonConfig:
    defaults = dict(repo_path="/repo", budget_tokens=10_000)
    defaults.update(kwargs)
    return DaemonConfig(**defaults)


def make_file(path: str = "src/app.py") -> RepoFile:
    return RepoFile(
        absolute_path=f"/repo/{path}",
        relative_path=path,
        extension=".py",
        size_bytes=1000,
        category="source",
    )


def make_success_result(tokens: int = 500) -> RunResult:
    return RunResult(
        prompt_category="review",
        input_tokens=tokens,
        output_tokens=200,
        cache_read_tokens=0,
        cost_usd=0.01,
        duration_ms=1000,
        success=True,
    )


class FakeRunner:
    def __init__(self, result: RunResult, max_calls: int = 100) -> None:
        self._result = result
        self._max_calls = max_calls
        self.call_count = 0
        self.prompts_received: list[BurnPrompt] = []

    def run(self, prompt: BurnPrompt) -> RunResult:
        self.call_count += 1
        self.prompts_received.append(prompt)
        if self.call_count >= self._max_calls:
            # Safety: prevent infinite loops in tests
            raise RuntimeError("max calls exceeded in FakeRunner")
        return self._result


class FakeLogger:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def log(self, event: dict) -> None:
        self.events.append(event)


class TestRunBurnLoop:
    def test_does_not_run_when_already_exhausted(self):
        from incinerator.budget import apply_run_result
        state = make_initial_state()
        # Pre-consume all tokens so budget is already exhausted
        state = apply_run_result(state, make_success_result(tokens=9800))
        config = make_config(budget_tokens=10_000)
        runner = FakeRunner(result=make_success_result())
        logger = FakeLogger()

        run_burn_loop(
            config=config,
            repo_files=[make_file()],
            initial_state=state,
            runner=runner,
            logger=logger,
            delay_fn=lambda ms, s: None,
            random_fn=random.Random(42).random,
        )

        assert runner.call_count == 0

    def test_runs_until_token_budget_exhausted(self):
        # Budget of 800 tokens, each run uses 700 in + 200 out = 900 total → stops after 1 run
        state = make_initial_state()
        config = make_config(budget_tokens=800)
        result = make_success_result(tokens=700)  # 700 + 200 out = 900 total
        runner = FakeRunner(result=result)
        logger = FakeLogger()

        run_burn_loop(
            config=config,
            repo_files=[make_file()],
            initial_state=state,
            runner=runner,
            logger=logger,
            delay_fn=lambda ms, s: None,
            random_fn=random.Random(42).random,
        )

        assert runner.call_count == 1

    def test_runs_until_usd_budget_exhausted(self):
        state = make_initial_state()
        config = make_config(budget_tokens=None, budget_usd=0.05)
        result = RunResult(
            prompt_category="review",
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=0,
            cost_usd=0.03,
            duration_ms=500,
            success=True,
        )
        runner = FakeRunner(result=result)
        logger = FakeLogger()

        run_burn_loop(
            config=config,
            repo_files=[make_file()],
            initial_state=state,
            runner=runner,
            logger=logger,
            delay_fn=lambda ms, s: None,
            random_fn=random.Random(42).random,
        )

        # 0.03 + 0.03 = 0.06 >= 0.05, so 2 runs
        assert runner.call_count == 2

    def test_calls_delay_between_requests(self):
        state = make_initial_state()
        config = make_config(budget_tokens=2000)
        runner = FakeRunner(result=make_success_result(tokens=500))
        logger = FakeLogger()
        delays: list[float] = []

        run_burn_loop(
            config=config,
            repo_files=[make_file()],
            initial_state=state,
            runner=runner,
            logger=logger,
            delay_fn=lambda ms, s: delays.append(ms),
            random_fn=random.Random(42).random,
        )

        assert len(delays) >= 1

    def test_logs_each_run(self):
        state = make_initial_state()
        config = make_config(budget_tokens=1000)
        runner = FakeRunner(result=make_success_result(tokens=700))
        logger = FakeLogger()

        run_burn_loop(
            config=config,
            repo_files=[make_file()],
            initial_state=state,
            runner=runner,
            logger=logger,
            delay_fn=lambda ms, s: None,
            random_fn=random.Random(42).random,
        )

        event_names = [e.get("event") for e in logger.events]
        assert "run_complete" in event_names

    def test_prompts_contain_file_paths_from_repo(self):
        state = make_initial_state()
        config = make_config(budget_tokens=1000)
        runner = FakeRunner(result=make_success_result(tokens=700))
        logger = FakeLogger()
        files = [make_file("src/auth.py"), make_file("src/db.py")]

        run_burn_loop(
            config=config,
            repo_files=files,
            initial_state=state,
            runner=runner,
            logger=logger,
            delay_fn=lambda ms, s: None,
            random_fn=random.Random(42).random,
        )

        assert runner.call_count >= 1
        prompt_text = runner.prompts_received[0].text
        # At least one file path should appear in the prompt
        assert any(f.relative_path in prompt_text for f in files)

    def test_continues_after_failed_run(self):
        state = make_initial_state()
        config = make_config(budget_tokens=2000)
        failed = RunResult(
            prompt_category="review",
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cost_usd=0.0,
            duration_ms=0,
            success=False,
            error_message="rate limited",
        )

        call_count = 0
        success = make_success_result(tokens=1500)

        class AlternatingRunner:
            def run(self, prompt: BurnPrompt) -> RunResult:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return failed
                return success

        logger = FakeLogger()
        run_burn_loop(
            config=config,
            repo_files=[make_file()],
            initial_state=state,
            runner=AlternatingRunner(),
            logger=logger,
            delay_fn=lambda ms, s: None,
            random_fn=random.Random(42).random,
        )

        assert call_count >= 2

    def test_returns_budget_state_on_auth_failure(self):
        state = make_initial_state()
        config = make_config(budget_tokens=10_000)
        auth_fail = RunResult(
            prompt_category="review",
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cost_usd=0.0,
            duration_ms=0,
            success=False,
            error_message="not logged in — please login first",
        )
        runner = FakeRunner(result=auth_fail)
        logger = FakeLogger()

        result = run_burn_loop(
            config=config,
            repo_files=[make_file()],
            initial_state=state,
            runner=runner,
            logger=logger,
            delay_fn=lambda ms, s: None,
            random_fn=random.Random(42).random,
        )

        assert result is not None
        assert isinstance(result, BudgetState)

    def test_skips_prompt_outside_working_hours(self):
        state = make_initial_state()
        config = make_config(budget_tokens=2000, working_hours_only=True)
        runner = FakeRunner(result=make_success_result(tokens=1500))
        logger = FakeLogger()
        delays: list[float] = []
        hour_calls = 0

        def night_then_day() -> int:
            nonlocal hour_calls
            hour_calls += 1
            if hour_calls <= 1:
                return 3  # 3 AM — outside work window
            return 10     # 10 AM — inside work window

        run_burn_loop(
            config=config,
            repo_files=[make_file()],
            initial_state=state,
            runner=runner,
            logger=logger,
            delay_fn=lambda ms, s: delays.append(ms),
            random_fn=random.Random(42).random,
            local_hour_fn=night_then_day,
        )

        event_names = [e.get("event") for e in logger.events]
        assert "outside_work_hours" in event_names
        assert runner.call_count >= 1

    def test_no_work_hours_check_when_flag_off(self):
        state = make_initial_state()
        config = make_config(budget_tokens=1000, working_hours_only=False)
        runner = FakeRunner(result=make_success_result(tokens=700))
        logger = FakeLogger()

        run_burn_loop(
            config=config,
            repo_files=[make_file()],
            initial_state=state,
            runner=runner,
            logger=logger,
            delay_fn=lambda ms, s: None,
            random_fn=random.Random(42).random,
            local_hour_fn=lambda: 3,  # 3 AM, but flag is off
        )

        event_names = [e.get("event") for e in logger.events]
        assert "outside_work_hours" not in event_names
        assert runner.call_count >= 1

    def test_returns_budget_state_on_too_many_consecutive_failures(self):
        state = make_initial_state()
        config = make_config(budget_tokens=10_000)
        fail = RunResult(
            prompt_category="review",
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cost_usd=0.0,
            duration_ms=0,
            success=False,
            error_message="network error",
        )
        runner = FakeRunner(result=fail)
        logger = FakeLogger()

        result = run_burn_loop(
            config=config,
            repo_files=[make_file()],
            initial_state=state,
            runner=runner,
            logger=logger,
            delay_fn=lambda ms, s: None,
            random_fn=random.Random(42).random,
        )

        assert result is not None
        assert isinstance(result, BudgetState)
