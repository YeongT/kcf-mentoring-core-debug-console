"""Persistent session logger for debug-console protocol traffic."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from protocol import PREFIX_CAMERA, PREFIX_IMU, PREFIX_LIDAR, PREFIX_NAMES, PREFIX_SD_CHUNK, format_hex


_THROTTLED_RX_PREFIXES = {PREFIX_CAMERA, PREFIX_LIDAR, PREFIX_IMU, PREFIX_SD_CHUNK}
_DATA_LOG_INTERVAL_S = 0.5


class SessionLogger:
    """Append console events to a per-run log file.

    The GUI log is intentionally capped for responsiveness. This logger keeps a
    durable trace for long board/app/console sessions so failures can be
    inspected after the window is closed.
    """

    def __init__(self, log_dir: str | Path = "logs", max_bytes: int = 20 * 1024 * 1024):
        self._path = Path(log_dir) / f"console_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        self._max_bytes = max_bytes
        self._bytes_written = 0
        self._closed = False
        self._truncated = False
        self._last_data_log: dict[tuple[str, int], float] = {}
        self._data_skip_count: dict[tuple[str, int], int] = {}

        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self._path.open("a", encoding="utf-8", buffering=1)
        self.log_text("Session log opened")

    @property
    def path(self) -> Path:
        return self._path

    def log_text(self, text: str) -> None:
        self._write(f"{self._timestamp()} EVENT {text}")

    def log_raw(self, direction: str, data: bytes) -> None:
        if len(data) == 0:
            return
        prefix = data[0]
        throttle_key = (direction, prefix)
        if direction == "RX" and prefix in _THROTTLED_RX_PREFIXES:
            now = time.monotonic()
            last = self._last_data_log.get(throttle_key, 0.0)
            if now - last < _DATA_LOG_INTERVAL_S:
                self._data_skip_count[throttle_key] = self._data_skip_count.get(throttle_key, 0) + 1
                return
            self._last_data_log[throttle_key] = now

        prefix_name = PREFIX_NAMES.get(prefix, f"0x{prefix:02X}")
        skipped = self._data_skip_count.pop(throttle_key, 0)
        skipped_text = f" (+{skipped} skipped)" if skipped else ""
        self._write(
            f"{self._timestamp()} {direction} [{prefix_name}] "
            f"len={len(data)} {format_hex(data)}{skipped_text}"
        )

    def close(self) -> None:
        if self._closed:
            return
        self.log_text("Session log closed")
        self._closed = True
        self._file.close()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().isoformat(timespec="milliseconds")

    def _write(self, line: str) -> None:
        if self._closed:
            return

        encoded_len = len(line.encode("utf-8")) + 1
        if self._bytes_written + encoded_len > self._max_bytes:
            if not self._truncated:
                marker = f"{self._timestamp()} EVENT session log reached {self._max_bytes} bytes; further lines suppressed"
                self._file.write(marker + "\n")
                self._file.flush()
                self._bytes_written += len(marker.encode("utf-8")) + 1
                self._truncated = True
            return

        self._file.write(line + "\n")
        self._file.flush()
        self._bytes_written += encoded_len
