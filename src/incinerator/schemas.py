from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class ClaudeUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int


class ClaudeJsonOutput(BaseModel):
    type: Literal["result"]
    is_error: bool
    total_cost_usd: float
    usage: ClaudeUsage
    duration_ms: int
    result: Optional[str] = None


class DaemonConfig(BaseModel):
    repo_path: str
    rate_per_hour: int = Field(default=5000, gt=0)
    model: Optional[str] = None
    claude_path: str = "claude"
    working_hours_only: bool = False
    statistical: bool = False
    budget_tokens: Optional[int] = Field(default=None, gt=0)
    budget_usd: Optional[float] = Field(default=None, gt=0)
    budget_duration_seconds: Optional[int] = Field(default=None, gt=0)


class BudgetState(BaseModel):
    total_tokens_used: int
    total_cost_usd: float
    run_count: int
    started_at: datetime
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
