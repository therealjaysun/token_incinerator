from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class FileLogger:
    def __init__(self, log_path: Optional[str] = None) -> None:
        if log_path is None:
            log_path = str(Path.home() / ".incinerator" / "incinerator.log")
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        self._log_path = log_path

    def log(self, event: dict) -> None:
        entry = {"timestamp": datetime.now(tz=timezone.utc).isoformat(), **event}
        with open(self._log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")


class StderrLogger:
    def log(self, event: dict) -> None:
        entry = {"timestamp": datetime.now(tz=timezone.utc).isoformat(), **event}
        print(json.dumps(entry), file=sys.stderr)
