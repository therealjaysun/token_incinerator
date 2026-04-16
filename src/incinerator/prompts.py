from __future__ import annotations

from typing import Callable

from incinerator.types import BurnPrompt, PromptCategory, RepoFile

_MAX_FILE_CHARS = 6_000

_PLAN_ONLY_SUFFIX = (
    "\n\nIMPORTANT: This is a planning and analysis exercise only. "
    "Do not execute any commands, do not write any files, do not make any git commits or pushes. "
    "Provide your analysis and recommendations in text only."
)

_TEMPLATES: dict[PromptCategory, str] = {
    "review": """\
Code review the following files. For each file, list the top 3 issues \
(bugs, quality, or design) with the exact line and a one-sentence fix.

{file_contents}
{suffix}""",

    "refactor": """\
Suggest refactoring improvements for the following code. \
For each file, identify the single biggest SRP violation and propose a concrete fix with code.

{file_contents}
{suffix}""",

    "security_audit": """\
Security audit the following code. List every vulnerability you find, \
cite the file and line, classify severity (Critical/High/Medium/Low), and give a one-line fix.

{file_contents}
{suffix}""",

    "doc_generation": """\
Write concise API documentation for every public function and class in the following code. \
Include type signatures, parameter descriptions, and a usage example for each.

{file_contents}
{suffix}""",

    "architecture": """\
Analyze the architecture of the following code. Draw an ASCII component diagram, \
identify the top 3 architectural concerns, and propose one improvement for each.

{file_contents}
{suffix}""",
}


_BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".exe", ".dll", ".so", ".dylib", ".o", ".a", ".pyc", ".pyo",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv", ".flac",
    ".bin", ".dat", ".db", ".sqlite", ".sqlite3",
    ".wasm", ".class", ".jar",
}


def _read_file_safe(path: str) -> str:
    import os
    ext = os.path.splitext(path)[1].lower()
    if ext in _BINARY_EXTENSIONS:
        return "(binary file — skipped)"
    try:
        with open(path, "rb") as f:
            raw = f.read(_MAX_FILE_CHARS)
        if b"\x00" in raw:
            return "(binary file — skipped)"
        content = raw.decode("utf-8", errors="replace")
        if len(raw) == _MAX_FILE_CHARS:
            content += "\n... (truncated)"
        return content
    except Exception:
        return "(could not read file)"


def _format_file_contents(files: list[RepoFile]) -> str:
    sections: list[str] = []
    for f in files:
        content = _read_file_safe(f.absolute_path)
        sections.append(f"### FILE: {f.relative_path}\n```\n{content}\n```")
    return "\n\n".join(sections)


def generate_prompt(
    category: PromptCategory,
    files: list[RepoFile],
    random_fn: Callable[[], float],
) -> BurnPrompt:
    file_contents = _format_file_contents(files)
    template = _TEMPLATES[category]
    text = template.format(file_contents=file_contents, suffix=_PLAN_ONLY_SUFFIX)
    estimated_tokens = len(text) // 4
    return BurnPrompt(
        category=category,
        text=text,
        estimated_input_tokens=max(1, estimated_tokens),
        target_files=tuple(f.relative_path for f in files),
    )
