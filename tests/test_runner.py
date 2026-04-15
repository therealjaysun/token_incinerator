from pathlib import Path

import pytest

from incinerator.runner import ClaudeRunner
from incinerator.types import BurnPrompt

FIXTURES = Path(__file__).parent / "fixtures"


def make_prompt() -> BurnPrompt:
    return BurnPrompt(
        category="review",
        text="Review this codebase thoroughly.",
        estimated_input_tokens=500,
        target_files=("src/app.py",),
    )


class TestClaudeRunner:
    def test_returns_run_result_on_success(self):
        runner = ClaudeRunner(
            model=None,
            claude_path=str(FIXTURES / "fake_claude_success.sh"),
        )
        result = runner.run(make_prompt())
        assert result.success is True
        assert result.input_tokens == 2000
        assert result.output_tokens == 800
        assert result.cache_read_tokens == 100
        assert abs(result.cost_usd - 0.0234) < 0.0001
        assert result.duration_ms == 5100
        assert result.prompt_category == "review"

    def test_returns_failed_result_on_nonzero_exit(self):
        runner = ClaudeRunner(
            model=None,
            claude_path=str(FIXTURES / "fake_claude_error.sh"),
        )
        result = runner.run(make_prompt())
        assert result.success is False
        assert result.error_message is not None
        assert result.input_tokens == 0
        assert result.cost_usd == 0.0

    def test_returns_failed_result_on_bad_json(self):
        runner = ClaudeRunner(
            model=None,
            claude_path=str(FIXTURES / "fake_claude_bad_json.sh"),
        )
        result = runner.run(make_prompt())
        assert result.success is False
        assert result.error_message is not None

    def test_passes_allowed_tools_flag(self, tmp_path):
        # Write a script that records the args it received
        log = tmp_path / "args.txt"
        script = tmp_path / "recorder.sh"
        script.write_text(f"""#!/bin/bash
echo "$@" >> {log}
cat <<'EOF'
{{"type":"result","is_error":false,"total_cost_usd":0.001,"usage":{{"input_tokens":10,"output_tokens":5,"cache_read_input_tokens":0}},"duration_ms":100,"result":"ok"}}
EOF
""")
        script.chmod(0o755)
        runner = ClaudeRunner(
            model=None,
            claude_path=str(script),
        )
        runner.run(make_prompt())
        args = log.read_text()
        assert "--allowedTools" in args or "--allowed-tools" in args.lower()

    def test_passes_output_format_json_flag(self, tmp_path):
        log = tmp_path / "args.txt"
        script = tmp_path / "recorder.sh"
        script.write_text(f"""#!/bin/bash
echo "$@" >> {log}
cat <<'EOF'
{{"type":"result","is_error":false,"total_cost_usd":0.001,"usage":{{"input_tokens":10,"output_tokens":5,"cache_read_input_tokens":0}},"duration_ms":100,"result":"ok"}}
EOF
""")
        script.chmod(0o755)
        runner = ClaudeRunner(model=None, claude_path=str(script))
        runner.run(make_prompt())
        args = log.read_text()
        assert "json" in args

    def test_omits_model_flag_when_model_is_none(self, tmp_path):
        log = tmp_path / "args.txt"
        script = tmp_path / "recorder.sh"
        script.write_text(f"""#!/bin/bash
echo "$@" >> {log}
cat <<'EOF'
{{"type":"result","is_error":false,"total_cost_usd":0.001,"usage":{{"input_tokens":10,"output_tokens":5,"cache_read_input_tokens":0}},"duration_ms":100,"result":"ok"}}
EOF
""")
        script.chmod(0o755)
        runner = ClaudeRunner(model=None, claude_path=str(script))
        runner.run(make_prompt())
        args = log.read_text()
        assert "--model" not in args

    def test_passes_model_flag_when_model_is_set(self, tmp_path):
        log = tmp_path / "args.txt"
        script = tmp_path / "recorder.sh"
        script.write_text(f"""#!/bin/bash
echo "$@" >> {log}
cat <<'EOF'
{{"type":"result","is_error":false,"total_cost_usd":0.001,"usage":{{"input_tokens":10,"output_tokens":5,"cache_read_input_tokens":0}},"duration_ms":100,"result":"ok"}}
EOF
""")
        script.chmod(0o755)
        runner = ClaudeRunner(model="claude-opus-4-6", claude_path=str(script))
        runner.run(make_prompt())
        args = log.read_text()
        assert "--model" in args
        assert "claude-opus-4-6" in args

    def test_populates_error_message_from_result_when_is_error_true(self, tmp_path):
        script = tmp_path / "fake_is_error.sh"
        script.write_text("""#!/bin/bash
cat <<'EOF'
{"type":"result","is_error":true,"total_cost_usd":0.0,"usage":{"input_tokens":10,"output_tokens":5,"cache_read_input_tokens":0},"duration_ms":100,"result":"permission denied: tool not allowed"}
EOF
""")
        script.chmod(0o755)
        runner = ClaudeRunner(model=None, claude_path=str(script))
        result = runner.run(make_prompt())
        assert result.success is False
        assert result.error_message == "permission denied: tool not allowed"
