from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from incinerator.schemas import DaemonConfig

_PID_FILENAME = "incinerator.pid"
_CONFIG_FILENAME = "incinerator_config.json"
_DAEMON_ENV_VAR = "INCINERATOR_DAEMON"


class PidFileManager:
    def __init__(self, state_dir: Optional[str] = None) -> None:
        if state_dir is None:
            state_dir = str(Path.home() / ".incinerator")
        self._state_dir = Path(state_dir)
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._pid_file = self._state_dir / _PID_FILENAME
        self._config_file = self._state_dir / _CONFIG_FILENAME

    def write(self, pid: int, config: DaemonConfig) -> None:
        self._pid_file.write_text(str(pid))
        self._config_file.write_text(config.model_dump_json())

    def read(self) -> Optional[dict]:
        if not self._pid_file.exists():
            return None
        try:
            pid = int(self._pid_file.read_text().strip())
            config = DaemonConfig.model_validate_json(self._config_file.read_text())
            return {"pid": pid, "config": config}
        except (ValueError, FileNotFoundError, Exception):
            return None

    def remove(self) -> None:
        self._pid_file.unlink(missing_ok=True)
        self._config_file.unlink(missing_ok=True)

    def is_process_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # process exists but we don't have permission to signal it


def is_daemon_process() -> bool:
    return os.environ.get(_DAEMON_ENV_VAR) == "1"


def fork_daemon(config: DaemonConfig, state_dir: Optional[str] = None) -> int:
    log_dir = Path.home() / ".incinerator"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "incinerator.log"

    env = {**os.environ, _DAEMON_ENV_VAR: "1"}
    if state_dir:
        env["INCINERATOR_STATE_DIR"] = state_dir

    with open(log_file, "a") as log_fh:
        child = subprocess.Popen(
            [sys.executable, "-m", "incinerator.cli", "__daemon__", config.model_dump_json()],
            stdout=log_fh,
            stderr=log_fh,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )
    child.poll()  # Don't wait — just detach
    return child.pid
