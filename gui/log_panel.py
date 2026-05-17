"""Protocol log console with hex dump and human-readable mode."""

import struct
import time
from datetime import datetime

from PyQt6.QtWidgets import (
    QGroupBox, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout, QLabel, QApplication,
    QCheckBox,
)
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtCore import Qt, QTimer

from protocol import (
    PREFIX_NAMES,
    PREFIX_INIT,
    PREFIX_INIT_ACK,
    PREFIX_CMD,
    PREFIX_RES,
    PREFIX_STATUS,
    PREFIX_CAMERA,
    PREFIX_LIDAR,
    PREFIX_IMU,
    PREFIX_SD_CHUNK,
    CMD_NAMES,
    CMD_GET_DEBUG_SNAPSHOT,
    CMD_GET_PROTOCOL_INFO,
    CMD_GET_RUNTIME_STATUS,
    CMD_GET_SCAN_STATS,
    CMD_SD_DOWNLOAD,
    CMD_SD_LIST,
    CMD_SET_DEBUG_MODE,
    RESULT_OK,
    SCAN_STATE_NAMES,
    DebugSnapshot,
    INIT_FLAG_START_STREAM,
    ProtocolInfo,
    RuntimeStatus,
    ScanStats,
    format_hex,
    parse_init,
    parse_imu_frame,
    parse_response,
    parse_status,
    parse_sd_chunk,
    parse_lidar_frame,
)


_THROTTLED_RX_PREFIXES = {PREFIX_CAMERA, PREFIX_LIDAR, PREFIX_IMU, PREFIX_SD_CHUNK}
_DATA_LOG_INTERVAL_S = 0.5


def _describe_message(direction: str, data: bytes) -> str:
    """Return a human-readable one-line description of a binary message."""
    if len(data) == 0:
        return "(empty)"

    prefix = data[0]

    if prefix == PREFIX_INIT and len(data) >= 3:
        init = parse_init(data)
        if init:
            return (
                f"INIT from '{init.device_name}' "
                f"(v{init.protocol_version}, "
                f"scan={init.status.scan_state_name}, "
                f"rpm={init.status.lidar_rpm}, "
                f"stream={init.status.streaming_str})"
            )

    if prefix == PREFIX_INIT_ACK and len(data) >= 8:
        push_ms = struct.unpack_from("<H", data, 1)[0]
        stream_ms = struct.unpack_from("<H", data, 3)[0]
        rpm = struct.unpack_from("<H", data, 5)[0]
        flags = data[7]
        parts = [f"push={push_ms}ms"]
        if flags & INIT_FLAG_START_STREAM:
            parts.append(f"stream={stream_ms}ms")
        if rpm > 0:
            parts.append(f"rpm={rpm}")
        return f"INIT_ACK ({', '.join(parts)})"

    if prefix == PREFIX_CMD and len(data) >= 3:
        cmd_name = CMD_NAMES.get(data[1], f"0x{data[1]:02X}")
        seq = data[2]
        extra = ""
        if data[1] == 0x04 and len(data) >= 5:  # SET_MOTOR_RPM
            rpm = struct.unpack_from("<H", data, 3)[0]
            extra = f" rpm={rpm}"
        elif data[1] == 0x05 and len(data) >= 5:  # START_STREAM
            interval = struct.unpack_from("<H", data, 3)[0]
            extra = f" interval={interval}ms"
        elif data[1] == CMD_SET_DEBUG_MODE and len(data) >= 4:
            extra = f" enabled={int(data[3] != 0)}"
        return f"CMD {cmd_name} seq={seq}{extra}"

    if prefix == PREFIX_RES and len(data) >= 4:
        resp = parse_response(data)
        if resp:
            result_str = "OK" if resp.ok else "ERROR"
            extra = ""
            if resp.ok and resp.cmd_id == 0x01 and len(resp.payload) >= 17:  # GET_STATUS
                from protocol import DeviceStatus
                st = DeviceStatus.from_bytes(resp.payload)
                extra = (
                    f" scan={st.scan_state_name}, rpm={st.lidar_rpm}, "
                    f"frames={st.frame_count}, stream={st.streaming_str}"
                )
            elif resp.ok and resp.cmd_id == CMD_GET_PROTOCOL_INFO:
                info = ProtocolInfo.from_bytes(resp.payload)
                if info:
                    extra = f" v{info.version}, caps={info.capability_str}"
            elif resp.ok and resp.cmd_id == CMD_GET_RUNTIME_STATUS:
                status = RuntimeStatus.from_bytes(resp.payload)
                if status:
                    scan = SCAN_STATE_NAMES.get(status.scan_state, str(status.scan_state))
                    extra = (
                        f" scan={scan}, debug={int(status.debug_mode_enabled)}, "
                        f"heap={status.free_heap // 1024}K, rssi={status.wifi_rssi}dBm"
                    )
            elif resp.ok and resp.cmd_id == CMD_GET_SCAN_STATS:
                stats = ScanStats.from_bytes(resp.payload)
                if stats:
                    extra = (
                        f" session={stats.scan_session_id}, lidar={stats.lidar_frame_count}, "
                        f"imu={stats.imu_batch_count}, ws_fail={stats.ws_send_failure_count}"
                    )
            elif resp.ok and resp.cmd_id == CMD_SET_DEBUG_MODE:
                if resp.payload:
                    extra = f" debug={int(resp.payload[0] != 0)}"
            elif resp.ok and resp.cmd_id == CMD_GET_DEBUG_SNAPSHOT:
                snapshot = DebugSnapshot.from_bytes(resp.payload)
                if snapshot:
                    extra = (
                        f" debug={int(snapshot.debug_mode_enabled)}, "
                        f"ws_fail={snapshot.ws_binary_send_failures}, "
                        f"sd_err={snapshot.sd_write_error_count}"
                    )
            return f"RES {resp.cmd_name} seq={resp.seq} {result_str}{extra}"

    if prefix == PREFIX_STATUS:
        status = parse_status(data)
        if status:
            return (
                f"STATUS scan={status.scan_state_name}, "
                f"rpm={status.lidar_rpm}, "
                f"sd={status.sd_free_mb}MB, "
                f"frames={status.frame_count}, "
                f"stream={status.streaming_str}"
            )

    if prefix == PREFIX_CAMERA:
        size = len(data) - 1
        return f"CAMERA {size:,} bytes (JPEG)"

    if prefix == PREFIX_LIDAR:
        frame = parse_lidar_frame(data)
        if frame:
            return f"LIDAR {len(frame.points)} points"

    if prefix == PREFIX_IMU:
        frame = parse_imu_frame(data)
        if frame:
            return f"IMU {len(frame.samples)} samples"

    if prefix == PREFIX_SD_CHUNK:
        chunk = parse_sd_chunk(data)
        if chunk:
            return (
                f"SD_CHUNK transfer={chunk.transfer_id} "
                f"offset={chunk.offset} size={len(chunk.data)} eof={int(chunk.is_eof)}"
            )

    prefix_name = PREFIX_NAMES.get(prefix, f"0x{prefix:02X}")
    return f"{prefix_name} ({len(data)} bytes)"


class LogPanel(QGroupBox):
    MAX_LINES = 1000

    def __init__(self):
        super().__init__("Protocol Log")
        self._line_count = 0
        self._plain_lines: list[str] = []
        self._verbose = True
        self._last_data_log: dict[tuple[str, int], float] = {}
        self._data_skip_count: dict[tuple[str, int], int] = {}
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout()

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(QFont("Consolas", 9))
        self._text.setMinimumHeight(120)
        layout.addWidget(self._text)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        self._status_label = QLabel()
        self._status_label.setFont(QFont("Consolas", 8))
        self._status_label.setStyleSheet("color: #666;")
        btn_row.addWidget(self._status_label)

        btn_row.addStretch()

        self._verbose_check = QCheckBox("Verbose")
        self._verbose_check.setChecked(True)
        self._verbose_check.setToolTip("Show raw hex bytes (unchecked = human-readable)")
        self._verbose_check.toggled.connect(self._on_verbose_toggled)
        btn_row.addWidget(self._verbose_check)

        btn_copy = QPushButton("Copy")
        btn_copy.setStyleSheet("padding: 2px 10px; font-size: 11px;")
        btn_copy.setToolTip("Copy visible log lines")
        btn_copy.clicked.connect(self._copy_visible)
        btn_row.addWidget(btn_copy)

        btn_clear = QPushButton("Clear")
        btn_clear.setStyleSheet("padding: 2px 10px; font-size: 11px;")
        btn_clear.clicked.connect(self._clear)
        btn_row.addWidget(btn_clear)

        layout.addLayout(btn_row)
        self.setLayout(layout)

    def _on_verbose_toggled(self, checked: bool) -> None:
        self._verbose = checked

    def _clear(self) -> None:
        self._text.clear()
        self._line_count = 0
        self._plain_lines.clear()

    def _copy_visible(self) -> None:
        """Copy only the lines currently visible in the viewport."""
        viewport = self._text.viewport()
        top_pos = self._text.cursorForPosition(viewport.rect().topLeft())
        bot_pos = self._text.cursorForPosition(viewport.rect().bottomLeft())
        first = top_pos.blockNumber()
        last = bot_pos.blockNumber()
        if first <= last and first < len(self._plain_lines):
            lines = self._plain_lines[first:last + 1]
            QApplication.clipboard().setText("\n".join(lines))
            count = len(lines)
            self._status_label.setText(f"Copied {count} lines")
            self._status_label.setStyleSheet("color: #4CAF50;")
            QTimer.singleShot(2000, lambda: (
                self._status_label.setText(""),
                self._status_label.setStyleSheet("color: #666;"),
            ))

    def log_raw(self, direction: str, data: bytes) -> None:
        if len(data) == 0:
            return

        prefix = data[0]
        prefix_name = PREFIX_NAMES.get(prefix, f"0x{prefix:02X}")
        throttle_key = (direction, prefix)
        if direction == "RX" and prefix in _THROTTLED_RX_PREFIXES:
            now = time.monotonic()
            last = self._last_data_log.get(throttle_key, 0.0)
            if now - last < _DATA_LOG_INTERVAL_S:
                self._data_skip_count[throttle_key] = self._data_skip_count.get(throttle_key, 0) + 1
                return
            self._last_data_log[throttle_key] = now

        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        color = "#4FC3F7" if direction == "TX" else "#A5D6A7"

        if self._verbose:
            hex_str = format_hex(data)
            detail = hex_str
        else:
            detail = _describe_message(direction, data)

        skipped = self._data_skip_count.pop(throttle_key, 0)
        if skipped:
            detail = f"{detail} (+{skipped} skipped)"

        plain = f"{ts} {direction} [{prefix_name}] {detail}"
        html = f'<span style="color: gray;">{ts}</span> '
        html += f'<span style="color: {color}; font-weight: bold;">{direction}</span> '
        html += f'<span style="color: #FFD54F;">[{prefix_name}]</span> '
        html += f'<span style="color: #E0E0E0;">{detail}</span>'

        self._append_html(html, plain)

    def log_text(self, text: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        plain = f"{ts} {text}"
        html = f'<span style="color: gray;">{ts}</span> '
        html += f'<span style="color: #CE93D8;">{text}</span>'
        self._append_html(html, plain)

    def _append_html(self, html: str, plain: str = "") -> None:
        if self._line_count >= self.MAX_LINES:
            cursor = self._text.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.movePosition(QTextCursor.MoveOperation.Down, QTextCursor.MoveMode.KeepAnchor, 100)
            cursor.removeSelectedText()
            self._line_count -= 100
            self._plain_lines = self._plain_lines[100:]

        self._text.append(html)
        self._plain_lines.append(plain)
        self._line_count += 1
        self._text.moveCursor(QTextCursor.MoveOperation.End)
