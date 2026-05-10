"""Smoke checks for persistent console session logging."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol import PREFIX_CMD
from session_logger import SessionLogger


def run() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        logger = SessionLogger(tmp, max_bytes=1024)
        logger.log_text("Device connected")
        logger.log_raw("TX", bytes([PREFIX_CMD, 0x01, 0x02]))
        path = logger.path
        logger.close()

        content = path.read_text(encoding="utf-8")
        assert "Device connected" in content
        assert "TX [CMD]" in content
        assert "10 01 02" in content


if __name__ == "__main__":
    run()
    print("session_logger_smoke: ok")
