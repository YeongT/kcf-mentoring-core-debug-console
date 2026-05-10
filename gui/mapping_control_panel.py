"""Control panel for the 2.5D mapping tab."""

from __future__ import annotations

import struct
from typing import Callable

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout

from protocol import (
    CAP_IMU_STREAM_CTRL,
    CMD_GET_PROTOCOL_INFO,
    CMD_GET_STATUS,
    CMD_IMU_SET_PREVIEW,
    CMD_LIDAR_SET_SCAN_MODE,
    CMD_SET_MOTOR_RPM,
    CMD_START_SCAN,
    CMD_STOP_SCAN,
    DeviceStatus,
    ProtocolInfo,
    SCAN_IDLE,
    SCAN_SCANNING,
    SCAN_MODE_EXPRESS,
    SCAN_MODE_NAMES,
    SCAN_MODE_STANDARD,
    parse_response,
    parse_status,
)
from ws_server import DeviceConnection


class MappingControlPanel(QGroupBox):
    _STYLE_OK = "color: #4CAF50; font-weight: bold;"
    _STYLE_WARN = "color: #FF9800; font-weight: bold;"
    _STYLE_ERROR = "color: #F44336; font-weight: bold;"
    _STYLE_IDLE = "color: #90A4AE; font-weight: bold;"
    _STYLE_STOP = (
        "QPushButton { background-color: #3B1D1D; color: #F44336; border: 1px solid #E53935; }"
        "QPushButton:hover { background-color: #4A2525; }"
    )

    def __init__(self, connection: DeviceConnection, map_panel, toggle_demo: Callable[[], None]):
        super().__init__("2.5D Mapping")
        self._conn = connection
        self._map_panel = map_panel
        self._toggle_demo = toggle_demo
        self._demo_running = False
        self._lidar_available = False
        self._imu_available = False
        self._supports_imu_preview_ctrl = False
        self._protocol_known = False
        self._scanning = False
        self._imu_previewing = False
        self._scan_state = SCAN_IDLE
        self._last_lidar_rpm = 0
        self._pending_scan_target: bool | None = None
        self._pending_imu_target: bool | None = None
        self._init_ui()
        self._connect_signals()
        self._sync_controls()
        self.sync_init_settings()

    def _init_ui(self) -> None:
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(10, 14, 10, 10)

        self._status = QLabel("Disconnected")
        self._status.setFont(QFont("Consolas", 10))
        self._status.setStyleSheet(self._STYLE_IDLE)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        grid = QGridLayout()
        self._labels: dict[str, QLabel] = {}
        for row, (title, key) in enumerate((("Frames", "frames"), ("Yaw", "yaw"), ("Window", "window"))):
            label = QLabel(title)
            label.setStyleSheet("color: #78909C;")
            value = QLabel("--")
            value.setFont(QFont("Consolas", 9))
            value.setStyleSheet("color: #CFD8DC;")
            grid.addWidget(label, row, 0)
            grid.addWidget(value, row, 1)
            self._labels[key] = value
        layout.addLayout(grid)

        self._btn_mapping = QPushButton("Start 3D Mapping")
        self._btn_mapping.setStyleSheet("font-weight: bold;")
        self._btn_mapping.clicked.connect(lambda _: self._toggle_mapping())
        layout.addWidget(self._btn_mapping)

        toggle_row = QHBoxLayout()
        self._btn_lidar_scan = QPushButton("Start LiDAR Scan")
        self._btn_lidar_scan.clicked.connect(lambda _: self._toggle_lidar_scan())
        toggle_row.addWidget(self._btn_lidar_scan)

        self._btn_imu_monitor = QPushButton("Start IMU Monitor")
        self._btn_imu_monitor.clicked.connect(lambda _: self._toggle_imu_monitor())
        toggle_row.addWidget(self._btn_imu_monitor)
        layout.addLayout(toggle_row)

        settings_box = QGroupBox("Device Settings")
        settings = QGridLayout()
        settings.setHorizontalSpacing(8)
        settings.setVerticalSpacing(6)
        settings.setContentsMargins(8, 12, 8, 8)

        settings.addWidget(QLabel("RPM"), 0, 0)
        self._rpm = QSpinBox()
        self._rpm.setRange(0, 2000)
        self._rpm.setSingleStep(10)
        self._rpm.setValue(660)
        self._rpm.setSuffix(" RPM")
        self._rpm.valueChanged.connect(self._sync_init_settings)
        settings.addWidget(self._rpm, 0, 1)

        settings.addWidget(QLabel("Scan Mode"), 1, 0)
        self._scan_mode = QComboBox()
        self._scan_mode.addItem(SCAN_MODE_NAMES[SCAN_MODE_STANDARD], SCAN_MODE_STANDARD)
        self._scan_mode.addItem(SCAN_MODE_NAMES[SCAN_MODE_EXPRESS], SCAN_MODE_EXPRESS)
        settings.addWidget(self._scan_mode, 1, 1)

        settings.addWidget(QLabel("IMU Interval"), 2, 0)
        self._imu_interval = QSpinBox()
        self._imu_interval.setRange(20, 1000)
        self._imu_interval.setSingleStep(10)
        self._imu_interval.setValue(50)
        self._imu_interval.setSuffix(" ms")
        settings.addWidget(self._imu_interval, 2, 1)

        self._btn_apply = QPushButton("Apply")
        self._btn_apply.clicked.connect(lambda _: self._apply_settings())
        settings.addWidget(self._btn_apply, 3, 0, 1, 2)
        settings_box.setLayout(settings)
        layout.addWidget(settings_box)

        action_row = QHBoxLayout()
        self._btn_demo = QPushButton("Start Demo")
        self._btn_demo.clicked.connect(self._toggle_demo)
        action_row.addWidget(self._btn_demo)

        self._btn_clear = QPushButton("Clear Map")
        self._btn_clear.clicked.connect(self._map_panel.clear_map)
        action_row.addWidget(self._btn_clear)
        layout.addLayout(action_row)

        layout.addStretch()
        self.setLayout(layout)

    def _connect_signals(self) -> None:
        self._conn.device_connected.connect(self._on_connected)
        self._conn.device_disconnected.connect(self._on_disconnected)
        self._conn.status_received.connect(self._on_status)
        self._conn.response_received.connect(self._on_response)

    def _on_connected(self, _name: str, initial_status: bytes) -> None:
        self._protocol_known = False
        self._supports_imu_preview_ctrl = False
        self._pending_scan_target = None
        self._pending_imu_target = None
        self.sync_init_settings()
        if initial_status:
            self._on_status(initial_status)
        else:
            self._sync_controls()
        self._conn.send_command(CMD_GET_PROTOCOL_INFO)

    def _on_disconnected(self) -> None:
        self._lidar_available = False
        self._imu_available = False
        self._supports_imu_preview_ctrl = False
        self._protocol_known = False
        self._scanning = False
        self._imu_previewing = False
        self._scan_state = SCAN_IDLE
        self._last_lidar_rpm = 0
        self._pending_scan_target = None
        self._pending_imu_target = None
        self._sync_controls()

    def _on_status(self, data: bytes) -> None:
        status = parse_status(data)
        if status:
            self._apply_status(status)

    def _on_response(self, data: bytes) -> None:
        if not self._conn.connected:
            return
        resp = parse_response(data)
        if not resp:
            return

        if resp.cmd_id == CMD_GET_STATUS and resp.ok and len(resp.payload) == DeviceStatus.STRUCT_SIZE:
            try:
                self._apply_status(DeviceStatus.from_bytes(resp.payload))
            except ValueError:
                self._show_status("Status response parse failed", self._STYLE_ERROR)
            return

        if resp.cmd_id == CMD_GET_PROTOCOL_INFO:
            self._protocol_known = True
            if not resp.ok:
                self._supports_imu_preview_ctrl = False
                self._imu_previewing = False
                self._sync_controls()
                self._show_status(f"Protocol info failed: {resp.result_name}", self._STYLE_ERROR)
                return
            info = ProtocolInfo.from_bytes(resp.payload)
            if not info:
                self._supports_imu_preview_ctrl = False
                self._sync_controls()
                self._show_status("Protocol info parse failed", self._STYLE_ERROR)
                return
            self._supports_imu_preview_ctrl = bool(info.capabilities & CAP_IMU_STREAM_CTRL)
            self._imu_previewing = info.imu_preview_enabled if self._supports_imu_preview_ctrl else False
            if info.imu_interval_ms:
                self._imu_interval.setValue(max(20, min(1000, info.imu_interval_ms)))
            self._sync_controls()
            return

        if resp.cmd_id in (CMD_START_SCAN, CMD_STOP_SCAN):
            target = resp.cmd_id == CMD_START_SCAN
            self._pending_scan_target = None
            if resp.ok:
                self._scanning = target
                self._scan_state = SCAN_SCANNING if target else SCAN_IDLE
                self._sync_controls()
                self._show_status(f"LiDAR scan {'ON' if target else 'OFF'}", self._STYLE_OK)
            else:
                self._sync_controls()
                self._show_status(f"LiDAR scan failed: {resp.result_name}", self._STYLE_ERROR)
            return

        if resp.cmd_id == CMD_IMU_SET_PREVIEW:
            target = self._pending_imu_target
            self._pending_imu_target = None
            if resp.ok:
                enabled = target if target is not None else self._imu_previewing
                if len(resp.payload) >= 1:
                    enabled = resp.payload[0] != 0
                if len(resp.payload) >= 3:
                    interval = struct.unpack_from("<H", resp.payload, 1)[0]
                    self._imu_interval.setValue(max(20, min(1000, interval)))
                self._imu_previewing = bool(enabled)
                self._sync_controls()
                self._show_status(f"IMU monitor {'ON' if self._imu_previewing else 'OFF'}", self._STYLE_OK)
            else:
                self._sync_controls()
                self._show_status(f"IMU monitor failed: {resp.result_name}", self._STYLE_ERROR)
            return

        if resp.cmd_id == CMD_SET_MOTOR_RPM:
            if resp.ok:
                self._last_lidar_rpm = self._rpm.value()
                self._sync_controls()
                self._show_status(f"RPM applied: {self._rpm.value()}", self._STYLE_OK)
            else:
                self._show_status(f"RPM failed: {resp.result_name}", self._STYLE_ERROR)
            return

        if resp.cmd_id == CMD_LIDAR_SET_SCAN_MODE:
            if resp.ok:
                if len(resp.payload) >= 1:
                    self._select_scan_mode(resp.payload[0])
                self._sync_controls()
                self._show_status(f"Scan mode applied: {self._scan_mode.currentText()}", self._STYLE_OK)
            else:
                self._show_status(f"Scan mode failed: {resp.result_name}", self._STYLE_ERROR)

    def _apply_status(self, status: DeviceStatus) -> None:
        self._lidar_available = status.lidar_ok
        self._imu_available = status.imu_ok
        self._scan_state = status.scan_state if status.lidar_ok else SCAN_IDLE
        self._scanning = status.scan_state == SCAN_SCANNING if status.lidar_ok else False
        self._last_lidar_rpm = status.lidar_rpm if status.lidar_ok else 0
        if not self._lidar_available:
            self._pending_scan_target = None
            self._scanning = False
        if not self._imu_available:
            self._pending_imu_target = None
            self._imu_previewing = False
        if self._pending_scan_target is not None and self._pending_scan_target == self._scanning:
            self._pending_scan_target = None
        self._sync_controls()

    def _toggle_mapping(self) -> None:
        if not self._can_control_mapping():
            return
        target_enabled = not self._mapping_active()
        if target_enabled:
            self._apply_lidar_settings(include_mode=not self._scanning)
            if not self._scanning:
                self._send_scan(True)
            if not self._imu_previewing:
                self._send_imu_preview(True)
        else:
            if self._scanning:
                self._send_scan(False)
            if self._imu_previewing:
                self._send_imu_preview(False)
        self._sync_controls()

    def _toggle_lidar_scan(self) -> None:
        if self._can_control_lidar():
            self._send_scan(not self._scanning)
            self._sync_controls()

    def _toggle_imu_monitor(self) -> None:
        if self._can_control_imu():
            self._send_imu_preview(not self._imu_previewing)
            self._sync_controls()

    def _apply_settings(self) -> None:
        sent = False
        if self._can_control_lidar():
            sent = self._apply_lidar_settings(include_mode=not self._scanning) or sent
        if self._can_control_imu():
            sent = self._send_imu_preview(self._imu_previewing) or sent
        if sent:
            self._show_status("Applying device settings...", self._STYLE_WARN)
        else:
            self._sync_controls()

    def _apply_lidar_settings(self, include_mode: bool) -> bool:
        sent = False
        if not self._can_control_lidar():
            return False
        self.sync_init_settings()
        sent = self._send(CMD_SET_MOTOR_RPM, struct.pack("<H", self._rpm.value())) or sent
        if include_mode:
            mode = int(self._scan_mode.currentData())
            sent = self._send(CMD_LIDAR_SET_SCAN_MODE, struct.pack("B", mode)) or sent
        return sent

    def _send_scan(self, enabled: bool) -> bool:
        if not self._can_control_lidar():
            return False
        self._pending_scan_target = enabled
        cmd = CMD_START_SCAN if enabled else CMD_STOP_SCAN
        sent = self._send(cmd)
        if not sent:
            self._pending_scan_target = None
        return sent

    def _send_imu_preview(self, enabled: bool) -> bool:
        if not self._can_control_imu():
            return False
        self._pending_imu_target = enabled
        payload = struct.pack("<BH", int(enabled), self._imu_interval.value())
        sent = self._send(CMD_IMU_SET_PREVIEW, payload)
        if not sent:
            self._pending_imu_target = None
        return sent

    def _send(self, cmd_id: int, payload: bytes = b"") -> bool:
        if not self._conn.connected:
            return False
        return self._conn.send_command(cmd_id, payload) is not None

    def _can_control_lidar(self) -> bool:
        return self._conn.connected and self._lidar_available

    def _can_control_imu(self) -> bool:
        return self._conn.connected and self._imu_available and self._supports_imu_preview_ctrl

    def _can_control_mapping(self) -> bool:
        return self._can_control_lidar() and self._can_control_imu()

    def _mapping_active(self) -> bool:
        return self._scanning and self._imu_previewing

    def _sync_controls(self) -> None:
        connected = self._conn.connected
        lidar_ready = self._can_control_lidar()
        imu_ready = self._can_control_imu()
        scan_pending = self._pending_scan_target is not None
        imu_pending = self._pending_imu_target is not None
        command_pending = scan_pending or imu_pending
        mapping_active = self._mapping_active()

        self._btn_mapping.setText("Stop 3D Mapping" if mapping_active else "Start 3D Mapping")
        self._btn_mapping.setEnabled(self._can_control_mapping() and not command_pending)
        self._btn_mapping.setStyleSheet(self._STYLE_STOP if mapping_active else "font-weight: bold;")

        self._btn_lidar_scan.setText("Stop LiDAR Scan" if self._scanning else "Start LiDAR Scan")
        self._btn_lidar_scan.setEnabled(lidar_ready and not scan_pending)

        if connected and self._imu_available and self._protocol_known and not self._supports_imu_preview_ctrl:
            self._btn_imu_monitor.setText("IMU Unsupported")
        else:
            self._btn_imu_monitor.setText("Stop IMU Monitor" if self._imu_previewing else "Start IMU Monitor")
        self._btn_imu_monitor.setEnabled(imu_ready and not imu_pending)

        self._rpm.setEnabled(lidar_ready)
        self._scan_mode.setEnabled(lidar_ready and not self._scanning)
        self._imu_interval.setEnabled(imu_ready)
        self._btn_apply.setEnabled((lidar_ready or imu_ready) and not command_pending)
        self._sync_status_label()

    def _sync_status_label(self) -> None:
        if self._demo_running:
            self._show_status("Demo fusion input live", self._STYLE_OK)
        elif not self._conn.connected:
            self._show_status("Disconnected", self._STYLE_IDLE)
        elif not self._lidar_available and not self._imu_available:
            self._show_status("Waiting for fusion input", self._STYLE_WARN)
        elif self._lidar_available and self._imu_available and not self._protocol_known:
            self._show_status("Fusion input ready; probing IMU control", self._STYLE_WARN)
        elif self._lidar_available and self._imu_available and not self._supports_imu_preview_ctrl:
            self._show_status("IMU monitor control unsupported", self._STYLE_WARN)
        elif self._mapping_active():
            self._show_status(f"3D mapping live | RPM {self._last_lidar_rpm}", self._STYLE_OK)
        elif self._lidar_available and self._imu_available:
            self._show_status("Fusion input ready", self._STYLE_OK)
        elif self._lidar_available:
            self._show_status("Partial input: LiDAR only", self._STYLE_WARN)
        else:
            self._show_status("Partial input: IMU only", self._STYLE_WARN)

    def _show_status(self, text: str, style: str) -> None:
        self._status.setText(text)
        self._status.setStyleSheet(style)

    def _select_scan_mode(self, mode: int) -> None:
        index = self._scan_mode.findData(mode)
        if index >= 0:
            self._scan_mode.setCurrentIndex(index)

    def sync_init_settings(self) -> None:
        settings = self._conn.init_ack_settings
        settings.motor_rpm = self._rpm.value()
        self._conn.init_ack_settings = settings

    def _sync_init_settings(self) -> None:
        self.sync_init_settings()

    def set_demo_running(self, running: bool) -> None:
        self._demo_running = running
        self._btn_demo.setText("Stop Demo" if running else "Start Demo")
        self._sync_controls()

    def set_sensor_state(self, lidar_ok: bool, imu_ok: bool) -> None:
        self._lidar_available = lidar_ok
        self._imu_available = imu_ok
        if not lidar_ok:
            self._scanning = False
            self._pending_scan_target = None
        if not imu_ok:
            self._imu_previewing = False
            self._pending_imu_target = None
        self._sync_controls()

    def update_snapshot(self, snapshot: dict) -> None:
        self._labels["frames"].setText(str(snapshot["frames"]))
        self._labels["yaw"].setText(f'{snapshot["yaw_deg"]:.1f} deg')
        self._labels["window"].setText(f'{snapshot["horizon_s"]:.1f} s')

