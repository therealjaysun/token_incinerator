from __future__ import annotations

import json
import shutil
import subprocess
from typing import Optional

from pydantic import ValidationError

from incinerator.schemas import ClaudeJsonOutput
from incinerator.types import BurnPrompt, RunResult

_AUTH_ERROR_SIGNALS = (
    "not logged in",
    "please login",
    "authentication",
    "unauthorized",
    "401",
    "api key",
    "invalid credentials",
    "login",
)

_USAGE_LIMIT_ERROR_SIGNALS = (
    "usage limit",
    "quota exceeded",
    "monthly limit",
    "daily limit",
    "credit balance is too low",
)


def is_auth_error(message: str) -> bool:
    lower = message.lower()
    return any(signal in lower for signal in _AUTH_ERROR_SIGNALS)


def is_usage_limit_error(message: str) -> bool:
    lower = message.lower()
    return any(signal in lower for signal in _USAGE_LIMIT_ERROR_SIGNALS)


def check_claude_auth(claude_path: str = "claude") -> tuple[bool, str]:
    """Return (ok, error_message). Runs a cheap preflight to verify claude is installed and authed."""
    if shutil.which(claude_path) is None:
        return False, (
            f"'{claude_path}' not found on PATH. "
            "Install Claude Code: https://claude.ai/code"
        )
    try:
        proc = subprocess.run(
            [claude_path, "-p", "Say the word OK.", "--output-format", "json",
             "--no-session-persistence", "--permission-mode", "dontAsk",
             "--allowedTools", ""],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return False, "Preflight timed out — Claude may be hanging waiting for auth."
    except Exception as exc:
        return False, f"Failed to run claude: {exc}"

    if proc.returncode != 0:
        stderr = (proc.stderr.strip() or proc.stdout.strip())[:300]
        if is_auth_error(stderr):
            return False, (
                f"Claude is not logged in.\n"
                f"Run 'claude login' to authenticate, then retry.\n"
                f"Details: {stderr}"
            )
        if is_usage_limit_error(stderr):
            return False, (
                "Claude appears to be at a usage limit.\n"
                "Wait for your limit window to reset (or upgrade account limits), then retry.\n"
                f"Details: {stderr}"
            )
        return False, f"claude exited {proc.returncode}: {stderr}"

    return True, ""


class ClaudeRunner:
    def __init__(
        self,
        model: Optional[str] = None,
        claude_path: str = "claude",
        max_budget_usd_per_run: Optional[float] = None,
    ) -> None:
        self._model = model
        self._claude_path = claude_path
        self._max_budget_usd_per_run = max_budget_usd_per_run

    def run(self, prompt: BurnPrompt) -> RunResult:
        cmd = [
            self._claude_path,
            "-p", prompt.text,
            "--allowedTools", "Read,Grep,Glob",
            "--output-format", "json",
            "--no-session-persistence",
        ]
        if self._model is not None:
            cmd += ["--model", self._model]
        if self._max_budget_usd_per_run is not None:
            cmd += ["--max-budget-usd", str(self._max_budget_usd_per_run)]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            return RunResult(
                prompt_category=prompt.category,
                input_tokens=0,
                output_tokens=0,
                cache_read_tokens=0,
                cost_usd=0.0,
                duration_ms=0,
                success=False,
                error_message="subprocess timed out after 300 seconds",
            )
        except Exception as exc:
            return RunResult(
                prompt_category=prompt.category,
                input_tokens=0,
                output_tokens=0,
                cache_read_tokens=0,
                cost_usd=0.0,
                duration_ms=0,
                success=False,
                error_message=str(exc),
            )

        if proc.returncode != 0:
            stderr = proc.stderr.strip() or proc.stdout.strip()
            return RunResult(
                prompt_category=prompt.category,
                input_tokens=0,
                output_tokens=0,
                cache_read_tokens=0,
                cost_usd=0.0,
                duration_ms=0,
                success=False,
                error_message=f"claude exited {proc.returncode}: {stderr[:200]}",
            )

        try:
            data = json.loads(proc.stdout.strip())
            output = ClaudeJsonOutput.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            return RunResult(
                prompt_category=prompt.category,
                input_tokens=0,
                output_tokens=0,
                cache_read_tokens=0,
                cost_usd=0.0,
                duration_ms=0,
                success=False,
                error_message=f"failed to parse claude output: {exc}",
            )

        return RunResult(
            prompt_category=prompt.category,
            input_tokens=output.usage.input_tokens,
            output_tokens=output.usage.output_tokens,
            cache_read_tokens=output.usage.cache_read_input_tokens,
            cost_usd=output.total_cost_usd,
            duration_ms=output.duration_ms,
            success=not output.is_error,
            error_message=output.result if output.is_error else None,
        )
