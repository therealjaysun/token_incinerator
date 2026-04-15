import os
from pathlib import Path

import pytest

from incinerator.repo import walk_repo, compute_file_weights, sample_weighted_files
from incinerator.types import RepoFile


def make_file_tree(base: Path, structure: dict) -> None:
    for name, content in structure.items():
        path = base / name
        if isinstance(content, dict):
            path.mkdir()
            make_file_tree(path, content)
        else:
            path.write_text(content)


class TestWalkRepo:
    def test_returns_files_in_repo(self, tmp_path: Path):
        make_file_tree(tmp_path, {
            "src": {"main.py": "print('hello')", "utils.py": "pass"},
            "README.md": "# Project",
        })
        files = walk_repo(str(tmp_path))
        relative_paths = {f.relative_path for f in files}
        assert "src/main.py" in relative_paths
        assert "src/utils.py" in relative_paths
        assert "README.md" in relative_paths

    def test_excludes_node_modules(self, tmp_path: Path):
        make_file_tree(tmp_path, {
            "src": {"index.ts": "export {}"},
            "node_modules": {"lodash": {"index.js": "module.exports = {}"}},
        })
        files = walk_repo(str(tmp_path))
        relative_paths = {f.relative_path for f in files}
        assert not any("node_modules" in p for p in relative_paths)

    def test_excludes_git_directory(self, tmp_path: Path):
        make_file_tree(tmp_path, {
            "src": {"app.py": "pass"},
            ".git": {"HEAD": "ref: refs/heads/main"},
        })
        files = walk_repo(str(tmp_path))
        assert not any(".git" in f.relative_path for f in files)

    def test_excludes_dist_and_build(self, tmp_path: Path):
        make_file_tree(tmp_path, {
            "src": {"app.ts": "export {}"},
            "dist": {"app.js": "module.exports = {}"},
            "build": {"app.js": "module.exports = {}"},
        })
        files = walk_repo(str(tmp_path))
        relative_paths = {f.relative_path for f in files}
        assert not any("dist" in p for p in relative_paths)
        assert not any("build" in p for p in relative_paths)

    def test_returns_correct_metadata(self, tmp_path: Path):
        (tmp_path / "app.py").write_text("x = 1")
        files = walk_repo(str(tmp_path))
        assert len(files) == 1
        f = files[0]
        assert f.extension == ".py"
        assert f.size_bytes == len("x = 1")
        assert f.absolute_path == str(tmp_path / "app.py")
        assert f.relative_path == "app.py"

    def test_classifies_source_files(self, tmp_path: Path):
        make_file_tree(tmp_path, {
            "src.py": "pass",
            "src.ts": "export {}",
            "src.go": "package main",
            "config.json": "{}",
            "README.md": "docs",
            "test_app.py": "def test_x(): pass",
        })
        files = walk_repo(str(tmp_path))
        by_path = {f.relative_path: f for f in files}
        assert by_path["src.py"].category == "source"
        assert by_path["src.ts"].category == "source"
        assert by_path["config.json"].category == "config"
        assert by_path["README.md"].category == "docs"
        assert by_path["test_app.py"].category == "test"

    def test_respects_max_files_limit(self, tmp_path: Path):
        for i in range(20):
            (tmp_path / f"file_{i}.py").write_text(f"# file {i}")
        files = walk_repo(str(tmp_path), max_files=5)
        assert len(files) <= 5

    def test_returns_empty_list_for_empty_repo(self, tmp_path: Path):
        files = walk_repo(str(tmp_path))
        assert files == []


class TestComputeFileWeights:
    def make_file(self, path: str, size: int, category="source") -> RepoFile:
        return RepoFile(
            absolute_path=f"/repo/{path}",
            relative_path=path,
            extension=".py",
            size_bytes=size,
            category=category,
        )

    def test_larger_files_get_higher_weight(self):
        small = self.make_file("small.py", 100)
        large = self.make_file("large.py", 10_000)
        weights = compute_file_weights([small, large])
        w_by_path = {w.file.relative_path: w.weight for w in weights}
        assert w_by_path["large.py"] > w_by_path["small.py"]

    def test_source_files_outweigh_config_of_same_size(self):
        source = self.make_file("app.py", 1000, category="source")
        config = RepoFile(
            absolute_path="/repo/config.json",
            relative_path="config.json",
            extension=".json",
            size_bytes=1000,
            category="config",
        )
        weights = compute_file_weights([source, config])
        w_by_path = {w.file.relative_path: w.weight for w in weights}
        assert w_by_path["app.py"] > w_by_path["config.json"]

    def test_all_weights_are_positive(self):
        files = [self.make_file(f"file{i}.py", 100 * i + 1) for i in range(5)]
        weights = compute_file_weights(files)
        assert all(w.weight > 0 for w in weights)


class TestSampleWeightedFiles:
    def make_weighted_files(self, count: int):
        from incinerator.repo import compute_file_weights
        files = [
            RepoFile(
                absolute_path=f"/repo/file{i}.py",
                relative_path=f"file{i}.py",
                extension=".py",
                size_bytes=(i + 1) * 100,
                category="source",
            )
            for i in range(count)
        ]
        return compute_file_weights(files)

    def test_returns_requested_count(self):
        import random
        weighted = self.make_weighted_files(10)
        sampled = sample_weighted_files(weighted, count=3, random_fn=random.Random(42).random)
        assert len(sampled) == 3

    def test_returns_fewer_if_not_enough_files(self):
        import random
        weighted = self.make_weighted_files(2)
        sampled = sample_weighted_files(weighted, count=10, random_fn=random.Random(42).random)
        assert len(sampled) == 2

    def test_heavier_files_sampled_more_often(self):
        import random
        weighted = self.make_weighted_files(10)
        counts: dict[str, int] = {}
        for seed in range(300):
            sampled = sample_weighted_files(weighted, count=1, random_fn=random.Random(seed).random)
            for f in sampled:
                counts[f.relative_path] = counts.get(f.relative_path, 0) + 1
        # file9.py has ~10x the weight of file0.py, should appear far more often
        assert counts.get("file9.py", 0) > counts.get("file0.py", 0)
