import random

import pytest

from incinerator.prompts import generate_prompt
from incinerator.types import PromptCategory, RepoFile


ALL_CATEGORIES: list[PromptCategory] = [
    "review", "refactor", "security_audit", "doc_generation", "architecture"
]


def make_file(path: str, size: int = 1000) -> RepoFile:
    return RepoFile(
        absolute_path=f"/repo/{path}",
        relative_path=path,
        extension=".py",
        size_bytes=size,
        category="source",
    )


def make_files() -> list[RepoFile]:
    return [
        make_file("src/auth/login.py", 3000),
        make_file("src/api/routes.py", 5000),
        make_file("src/db/models.py", 8000),
    ]


class TestGeneratePrompt:
    def test_returns_burn_prompt(self):
        from incinerator.types import BurnPrompt
        prompt = generate_prompt(
            category="review",
            files=make_files(),
            random_fn=random.Random(42).random,
        )
        assert isinstance(prompt, BurnPrompt)

    def test_prompt_text_is_non_empty(self):
        prompt = generate_prompt(
            category="review",
            files=make_files(),
            random_fn=random.Random(42).random,
        )
        assert len(prompt.text) > 200

    def test_prompt_contains_file_paths(self):
        files = make_files()
        prompt = generate_prompt(
            category="security_audit",
            files=files,
            random_fn=random.Random(42).random,
        )
        for f in files:
            assert f.relative_path in prompt.text

    def test_each_category_produces_distinct_prompt(self):
        files = make_files()
        prompts = {
            cat: generate_prompt(
                category=cat,
                files=files,
                random_fn=random.Random(42).random,
            ).text
            for cat in ALL_CATEGORIES
        }
        texts = list(prompts.values())
        for i, t1 in enumerate(texts):
            for t2 in texts[i + 1:]:
                assert t1 != t2, "Two categories produced identical prompts"

    def test_includes_plan_only_instruction(self):
        for cat in ALL_CATEGORIES:
            prompt = generate_prompt(
                category=cat,
                files=make_files(),
                random_fn=random.Random(42).random,
            )
            lower = prompt.text.lower()
            assert "do not" in lower or "plan only" in lower or "do not execute" in lower

    def test_estimated_input_tokens_is_positive(self):
        prompt = generate_prompt(
            category="architecture",
            files=make_files(),
            random_fn=random.Random(42).random,
        )
        assert prompt.estimated_input_tokens > 0

    def test_target_files_contains_provided_paths(self):
        files = make_files()
        prompt = generate_prompt(
            category="refactor",
            files=files,
            random_fn=random.Random(42).random,
        )
        for f in files:
            assert f.relative_path in prompt.target_files

    def test_works_with_single_file(self):
        prompt = generate_prompt(
            category="review",
            files=[make_file("app.py")],
            random_fn=random.Random(42).random,
        )
        assert "app.py" in prompt.text
