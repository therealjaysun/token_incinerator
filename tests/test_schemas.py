import pytest
from pydantic import ValidationError

from incinerator.schemas import (
    ClaudeJsonOutput,
    DaemonConfig,
    BudgetState,
)


def make_valid_claude_output() -> dict:
    return {
        "type": "result",
        "is_error": False,
        "total_cost_usd": 0.0123,
        "usage": {
            "input_tokens": 1000,
            "output_tokens": 500,
            "cache_read_input_tokens": 0,
        },
        "duration_ms": 4200,
        "result": "Here is the review...",
    }


def make_valid_daemon_config() -> dict:
    return {
        "repo_path": "/home/user/myproject",
        "rate_per_hour": 5000,
        "model": "claude-opus-4-6",
        "working_hours_only": False,
    }


class TestClaudeJsonOutput:
    def test_parses_valid_output(self):
        output = ClaudeJsonOutput.model_validate(make_valid_claude_output())
        assert output.total_cost_usd == 0.0123
        assert output.usage.input_tokens == 1000
        assert output.usage.output_tokens == 500
        assert output.duration_ms == 4200

    def test_rejects_wrong_type(self):
        data = make_valid_claude_output()
        data["type"] = "not_a_result"
        with pytest.raises(ValidationError):
            ClaudeJsonOutput.model_validate(data)

    def test_rejects_missing_usage(self):
        data = make_valid_claude_output()
        del data["usage"]
        with pytest.raises(ValidationError):
            ClaudeJsonOutput.model_validate(data)

    def test_result_field_is_optional(self):
        data = make_valid_claude_output()
        del data["result"]
        output = ClaudeJsonOutput.model_validate(data)
        assert output.result is None


class TestDaemonConfig:
    def test_parses_valid_config(self):
        config = DaemonConfig.model_validate(make_valid_daemon_config())
        assert config.repo_path == "/home/user/myproject"
        assert config.rate_per_hour == 5000

    def test_applies_defaults(self):
        config = DaemonConfig.model_validate({"repo_path": "/some/repo"})
        assert config.rate_per_hour == 5000
        assert config.model is None
        assert config.working_hours_only is False

    def test_rejects_missing_repo_path(self):
        with pytest.raises(ValidationError):
            DaemonConfig.model_validate({})

    def test_rejects_negative_rate(self):
        data = make_valid_daemon_config()
        data["rate_per_hour"] = -1
        with pytest.raises(ValidationError):
            DaemonConfig.model_validate(data)

    def test_accepts_optional_budget_fields(self):
        data = make_valid_daemon_config()
        data["budget_tokens"] = 500_000
        data["budget_usd"] = 10.0
        data["budget_duration_seconds"] = 7200
        config = DaemonConfig.model_validate(data)
        assert config.budget_tokens == 500_000
        assert config.budget_usd == 10.0
        assert config.budget_duration_seconds == 7200


class TestBudgetState:
    def test_parses_valid_state(self):
        state = BudgetState.model_validate({
            "total_tokens_used": 12000,
            "total_cost_usd": 0.45,
            "run_count": 5,
            "started_at": "2026-04-15T09:00:00Z",
        })
        assert state.run_count == 5
        assert state.last_run_at is None

    def test_last_run_at_is_optional(self):
        state = BudgetState.model_validate({
            "total_tokens_used": 0,
            "total_cost_usd": 0.0,
            "run_count": 0,
            "started_at": "2026-04-15T09:00:00Z",
        })
        assert state.last_run_at is None
