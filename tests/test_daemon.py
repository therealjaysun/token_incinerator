import json
import os
from pathlib import Path

import pytest

from incinerator.daemon import PidFileManager
from incinerator.schemas import DaemonConfig


def make_config(**kwargs) -> DaemonConfig:
    defaults = dict(repo_path="/repo")
    defaults.update(kwargs)
    return DaemonConfig(**defaults)


class TestPidFileManager:
    def test_write_then_read_returns_pid_and_config(self, tmp_path: Path):
        mgr = PidFileManager(state_dir=str(tmp_path))
        config = make_config(repo_path="/my/repo", rate_per_hour=3000)
        mgr.write(pid=12345, config=config)
        result = mgr.read()
        assert result is not None
        assert result["pid"] == 12345
        assert result["config"].repo_path == "/my/repo"
        assert result["config"].rate_per_hour == 3000

    def test_read_returns_none_when_no_pid_file(self, tmp_path: Path):
        mgr = PidFileManager(state_dir=str(tmp_path))
        assert mgr.read() is None

    def test_remove_clears_pid_file(self, tmp_path: Path):
        mgr = PidFileManager(state_dir=str(tmp_path))
        mgr.write(pid=999, config=make_config())
        mgr.remove()
        assert mgr.read() is None

    def test_is_process_alive_for_current_process(self, tmp_path: Path):
        mgr = PidFileManager(state_dir=str(tmp_path))
        assert mgr.is_process_alive(os.getpid()) is True

    def test_is_process_alive_returns_false_for_dead_pid(self, tmp_path: Path):
        mgr = PidFileManager(state_dir=str(tmp_path))
        assert mgr.is_process_alive(99999999) is False

    def test_write_overwrites_existing_pid_file(self, tmp_path: Path):
        mgr = PidFileManager(state_dir=str(tmp_path))
        mgr.write(pid=111, config=make_config())
        mgr.write(pid=222, config=make_config(rate_per_hour=9000))
        result = mgr.read()
        assert result is not None
        assert result["pid"] == 222
        assert result["config"].rate_per_hour == 9000
