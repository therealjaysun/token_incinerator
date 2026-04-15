from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

FileCategory = Literal["source", "config", "docs", "test", "other"]
PromptCategory = Literal["review", "refactor", "security_audit", "doc_generation", "architecture"]


@dataclass(frozen=True)
class RepoFile:
    absolute_path: str
    relative_path: str
    extension: str
    size_bytes: int
    category: FileCategory


@dataclass(frozen=True)
class WeightedFile:
    file: RepoFile
    weight: float


@dataclass(frozen=True)
class BurnPrompt:
    category: PromptCategory
    text: str
    estimated_input_tokens: int
    target_files: tuple[str, ...]


@dataclass(frozen=True)
class RunResult:
    prompt_category: PromptCategory
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cost_usd: float
    duration_ms: int
    success: bool
    error_message: Optional[str] = None
