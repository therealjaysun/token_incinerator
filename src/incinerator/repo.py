from __future__ import annotations

import os
from typing import Callable, Optional

from incinerator.types import FileCategory, RepoFile, WeightedFile

_EXCLUDED_DIRS = {"node_modules", ".git", "dist", "build", "__pycache__", ".venv", "venv", ".mypy_cache"}

_SOURCE_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".kt",
    ".swift", ".c", ".cpp", ".h", ".cs", ".rb", ".php", ".ex", ".exs",
}
_CONFIG_EXTENSIONS = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env"}
_DOC_EXTENSIONS = {".md", ".rst", ".txt", ".adoc"}

_CATEGORY_WEIGHT = {
    "source": 3.0,
    "test": 2.0,
    "docs": 1.0,
    "config": 0.5,
    "other": 0.3,
}


def _classify(relative_path: str, extension: str) -> FileCategory:
    name = os.path.basename(relative_path).lower()
    if "test" in name or "spec" in name:
        return "test"
    if extension in _SOURCE_EXTENSIONS:
        return "source"
    if extension in _CONFIG_EXTENSIONS:
        return "config"
    if extension in _DOC_EXTENSIONS:
        return "docs"
    return "other"


def walk_repo(repo_path: str, max_files: Optional[int] = None) -> list[RepoFile]:
    results: list[RepoFile] = []
    for dirpath, dirnames, filenames in os.walk(repo_path):
        # Prune excluded directories in-place
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDED_DIRS]
        for filename in filenames:
            abs_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(abs_path, repo_path)
            ext = os.path.splitext(filename)[1].lower()
            try:
                size = os.path.getsize(abs_path)
            except OSError:
                continue
            category = _classify(rel_path, ext)
            results.append(RepoFile(
                absolute_path=abs_path,
                relative_path=rel_path,
                extension=ext,
                size_bytes=size,
                category=category,
            ))
            if max_files is not None and len(results) >= max_files:
                return results
    return results


def compute_file_weights(files: list[RepoFile]) -> list[WeightedFile]:
    return [
        WeightedFile(
            file=f,
            weight=max(1.0, f.size_bytes) * _CATEGORY_WEIGHT.get(f.category, 1.0),
        )
        for f in files
    ]


def sample_weighted_files(
    weighted: list[WeightedFile],
    count: int,
    random_fn: Callable[[], float],
) -> list[RepoFile]:
    if not weighted:
        return []
    count = min(count, len(weighted))
    total = sum(w.weight for w in weighted)
    selected: list[RepoFile] = []
    remaining = list(weighted)
    for _ in range(count):
        if not remaining:
            break
        r = random_fn() * sum(w.weight for w in remaining)
        cumulative = 0.0
        for i, w in enumerate(remaining):
            cumulative += w.weight
            if r <= cumulative:
                selected.append(w.file)
                remaining.pop(i)
                break
    return selected
