"""Compact control panels for dashboard and sensor-specific tabs."""

from __future__ import annotations

import struct
import time
from typing import Callable

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from protocol import (
    CAMERA_EFFECTS,
    CAMERA_PARAM_AEC_VALUE,
    CAMERA_PARAM_BRIGHTNESS,
    CAMERA_PARAM_CONTRAST,
    CAMERA_PARAM_EFFECT,
    CAMERA_PARAM_EXPOSURE,
    CAMERA_PARAM_HMIRROR,
    CAMERA_PARAM_SATURATION,
    CAMERA_PARAM_VFLIP,
    CAMERA_PARAM_WHITEBAL,
    CAMERA_QUALITIES,
    CAMERA_RESOLUTIONS,
    CMD_CAMERA_GET_INFO,
    CMD_CAMERA_SET_PARAM,
    CMD_CAPTURE_FRAME,
    CMD_GET_DEVICE_INFO,
    CMD_GET_PROTOCOL_INFO,
    CMD_GET_STATUS,
    CMD_IMU_SET_PREVIEW,
    CMD_LIDAR_GET_HEALTH,
    CMD_LIDAR_GET_INFO,
    CMD_LIDAR_RESET,
    CMD_LIDAR_SET_SCAN_MODE,
    CMD_REBOOT,
    CMD_SET_CAMERA_CONFIG,
    CMD_SET_MOTOR_RPM,
    CMD_START_SCAN,
    CMD_START_STREAM,
    CMD_STOP_SCAN,
    CMD_STOP_STREAM,
    CMD_TIME_SYNC,
    DEFAULT_CAMERA_QUALITY,
    DEFAULT_CAMERA_RESOLUTION,
    DeviceInfo,
    CameraInfo,
    INIT_FLAG_START_STREAM,
    LidarHealth,
    LidarInfo,
    ProtocolInfo,
    SCAN_IDLE,
    SCAN_MODE_EXPRESS,
    SCAN_MODE_STANDARD,
    TimeSyncInfo,
    parse_response,
    parse_status,
)
from ws_server import DeviceConnection


class OverviewControlPanel(QGroupBox):
    reset_requested = pyqtSignal()

    def __init__(self, connection: DeviceConnection):
        super().__init__("Dashboard Controls")
        self._conn = connection
        self._init_ui()
        self._connect_signals()

    def _init_ui(self) -> None:
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(10, 14, 10, 10)

        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)

        buttons = [
            ("Get Status", lambda: self._conn.send_command(CMD_GET_STATUS)),
            ("Device Info", lambda: self._conn.send_command(CMD_GET_DEVICE_INFO)),
            ("Reconnect", self._conn.disconnect),
            ("Reboot", lambda: self._conn.send_command(CMD_REBOOT)),
            ("Reset View", self.reset_requested.emit),
        ]
        for idx, (title, callback) in enumerate(buttons):
            button = QPushButton(title)
            button.clicked.connect(callback)
            grid.addWidget(button, idx // 2, idx % 2)
        layout.addLayout(grid)

        self._info = QLabel("Status refresh, reconnect, and generic device actions live here.")
        self._info.setWordWrap(True)
        self._info.setStyleSheet("color: #90A4AE;")
        layout.addWidget(self._info)

        self._device_info = QLabel("--")
        self._device_info.setFont(QFont("Consolas", 8))
        self._device_info.setStyleSheet("color: #78909C;")
        self._device_info.setWordWrap(True)
        layout.addWidget(self._device_info)
        self.setLayout(layout)

    def _connect_signals(self) -> None:
        self._conn.response_received.connect(self._on_response)
        self._conn.device_disconnected.connect(self.reset)

    def _on_response(self, data: bytes) -> None:
        resp = parse_response(data)
        if not resp or resp.cmd_id != CMD_GET_DEVICE_INFO or not resp.ok:
            return
        info = DeviceInfo.from_bytes(resp.payload)
        if not info:
            return
        self._device_info.setText(
            f"{info.device_name} | RSSI {info.wifi_rssi} dBm | Heap {info.free_heap // 1024}K | "
            f"PSRAM {info.psram_free // (1024 * 1024)}M free"
        )

    def reset(self) -> None:
        self._device_info.setText("--")


class CameraControlPanel(QGroupBox):
    def __init__(self, connection: DeviceConnection):
        super().__init__("Camera Tasks")
        self._conn = connection
        self._streaming = False
        self._enabled = False
        self._init_ui()
        self._connect_signals()

    def _init_ui(self) -> None:
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(10, 14, 10, 10)

        row = QHBoxLayout()
        self._btn_stream = QPushButton("Start Stream")
        self._btn_stream.clicked.connect(self._toggle_stream)
        row.addWidget(self._btn_stream)
        self._btn_capture = QPushButton("Capture")
        self._btn_capture.clicked.connect(lambda: self._conn.send_command(CMD_CAPTURE_FRAME))
        row.addWidget(self._btn_capture)
        self._btn_info = QPushButton("Cam Info")
        self._btn_info.clicked.connect(lambda: self._conn.send_command(CMD_CAMERA_GET_INFO))
        row.addWidget(self._btn_info)
        layout.addLayout(row)

        cfg = QGridLayout()
        cfg.addWidget(QLabel("Interval"), 0, 0)
        self._interval = QSpinBox()
        self._interval.setRange(10, 1000)
        self._interval.setValue(50)
        self._interval.setSuffix(" ms")
        self._interval.valueChanged.connect(self._sync_init_settings)
        cfg.addWidget(self._interval, 0, 1)

        cfg.addWidget(QLabel("Resolution"), 1, 0)
        self._resolution = QComboBox()
        for name, value in CAMERA_RESOLUTIONS.items():
            self._resolution.addItem(name, value)
        self._resolution.setCurrentText(DEFAULT_CAMERA_RESOLUTION)
        self._resolution.currentIndexChanged.connect(self._sync_init_settings)
        cfg.addWidget(self._resolution, 1, 1)

        cfg.addWidget(QLabel("Quality"), 2, 0)
        self._quality = QComboBox()
        for name, value in CAMERA_QUALITIES.items():
            self._quality.addItem(name, value)
        self._quality.setCurrentText(DEFAULT_CAMERA_QUALITY)
        self._quality.currentIndexChanged.connect(self._sync_init_settings)
        cfg.addWidget(self._quality, 2, 1)

        self._btn_apply = QPushButton("Apply Config")
        self._btn_apply.clicked.connect(self._apply_config)
        cfg.addWidget(self._btn_apply, 3, 0, 1, 2)
        layout.addLayout(cfg)

        advanced = QGridLayout()
        advanced.addWidget(QLabel("Brightness"), 0, 0)
        self._brightness = QSpinBox()
        self._brightness.setRange(-2, 2)
        self._brightness.valueChanged.connect(lambda v: self._send_param(CAMERA_PARAM_BRIGHTNESS, v))
        advanced.addWidget(self._brightness, 0, 1)

        advanced.addWidget(QLabel("Contrast"), 1, 0)
        self._contrast = QSpinBox()
        self._contrast.setRange(-2, 2)
        self._contrast.valueChanged.connect(lambda v: self._send_param(CAMERA_PARAM_CONTRAST, v))
        advanced.addWidget(self._contrast, 1, 1)

        advanced.addWidget(QLabel("Saturation"), 2, 0)
        self._saturation = QSpinBox()
        self._saturation.setRange(-2, 2)
        self._saturation.valueChanged.connect(lambda v: self._send_param(CAMERA_PARAM_SATURATION, v))
        advanced.addWidget(self._saturation, 2, 1)

        advanced.addWidget(QLabel("AEC"), 3, 0)
        self._aec = QSpinBox()
        self._aec.setRange(0, 1200)
        self._aec.setSingleStep(50)
        self._aec.setValue(300)
        self._aec.valueChanged.connect(lambda v: self._send_param(CAMERA_PARAM_AEC_VALUE, v))
        advanced.addWidget(self._aec, 3, 1)

        advanced.addWidget(QLabel("Effect"), 4, 0)
        self._effect = QComboBox()
        for value, name in CAMERA_EFFECTS.items():
            self._effect.addItem(name, value)
        self._effect.currentIndexChanged.connect(
            lambda: self._send_param(CAMERA_PARAM_EFFECT, int(self._effect.currentData()))
        )
        advanced.addWidget(self._effect, 4, 1)

        checks = QHBoxLayout()
        for text, param, checked in (
            ("WB", CAMERA_PARAM_WHITEBAL, True),
            ("AE", CAMERA_PARAM_EXPOSURE, True),
            ("H-Mirror", CAMERA_PARAM_HMIRROR, False),
            ("V-Flip", CAMERA_PARAM_VFLIP, False),
        ):
            box = QCheckBox(text)
            box.setChecked(checked)
            box.toggled.connect(lambda value, p=param: self._send_param(p, int(value)))
            checks.addWidget(box)
        checks.addStretch()

        layout.addLayout(advanced)
        layout.addLayout(checks)

        self._info_label = QLabel("Camera tab is enabled only when the sensor is healthy.")
        self._info_label.setStyleSheet("color: #90A4AE;")
        self._info_label.setWordWrap(True)
        layout.addWidget(self._info_label)

        self.setLayout(layout)
        self._set_controls_enabled(False)
        self.sync_init_settings()

    def _connect_signals(self) -> None:
        self._conn.device_connected.connect(self._on_connected)
        self._conn.device_disconnected.connect(self._on_disconnected)
        self._conn.status_received.connect(self._on_status)
        self._conn.response_received.connect(self._on_response)

    def _on_connected(self, _name: str, _initial_status: bytes) -> None:
        self.sync_init_settings()
        self._conn.send_command(CMD_CAMERA_GET_INFO)

    def _on_disconnected(self) -> None:
        self._streaming = False
        self._enabled = False
        self._set_controls_enabled(False)
        self._btn_stream.setText("Start Stream")
        self._info_label.setText("Camera disconnected")

    def _on_status(self, data: bytes) -> None:
        status = parse_status(data)
        if not status:
            return
        self._enabled = status.camera_ok
        self._streaming = bool(status.camera_streaming)
        self._set_controls_enabled(self._enabled)
        self._btn_stream.setText("Stop Stream" if self._streaming else "Start Stream")
        self._info_label.setText("Streaming active" if self._streaming else "Camera ready")
        self.sync_init_settings()

    def _on_response(self, data: bytes) -> None:
        resp = parse_response(data)
        if not resp:
            return
        if resp.cmd_id == CMD_CAMERA_GET_INFO and resp.ok:
            info = CameraInfo.from_bytes(resp.payload)
            if info:
                self._info_label.setText(
                    f"{info.model or 'Camera'} | res={info.resolution} | quality={info.quality} | "
                    f"stream={'ON' if info.streaming else 'OFF'}"
                )
        elif resp.cmd_id == CMD_START_STREAM and resp.ok:
            self._streaming = True
            self._btn_stream.setText("Stop Stream")
            self.sync_init_settings()
        elif resp.cmd_id == CMD_STOP_STREAM and resp.ok:
            self._streaming = False
            self._btn_stream.setText("Start Stream")
            self.sync_init_settings()

    def _toggle_stream(self) -> None:
        if not self._enabled:
            return
        if self._streaming:
            self._conn.send_command(CMD_STOP_STREAM)
        else:
            self._conn.send_command(CMD_START_STREAM, struct.pack("<H", self._interval.value()))
        self.sync_init_settings()

    def _apply_config(self) -> None:
        self._conn.send_command(
            CMD_SET_CAMERA_CONFIG,
            struct.pack("BB", int(self._resolution.currentData()), int(self._quality.currentData())),
        )
        self.sync_init_settings()

    def _send_param(self, param_id: int, value: int) -> None:
        if self._enabled and self._conn.connected:
            self._conn.send_command(CMD_CAMERA_SET_PARAM, struct.pack("<Bh", param_id, value))

    def sync_init_settings(self) -> None:
        settings = self._conn.init_ack_settings
        settings.stream_interval_ms = self._interval.value()
        settings.camera_resolution = int(self._resolution.currentData())
        settings.camera_quality = int(self._quality.currentData())
        if self._streaming:
            settings.flags |= INIT_FLAG_START_STREAM
        else:
            settings.flags &= ~INIT_FLAG_START_STREAM
        self._conn.init_ack_settings = settings

    def _sync_init_settings(self) -> None:
        self.sync_init_settings()

    def _set_controls_enabled(self, enabled: bool) -> None:
        for child_type in (QPushButton, QSpinBox, QComboBox, QCheckBox):
            for child in self.findChildren(child_type):
                child.setEnabled(enabled)


class LidarControlPanel(QGroupBox):
    def __init__(self, connection: DeviceConnection):
        super().__init__("LiDAR 2D Tasks")
        self._conn = connection
        self._enabled = False
        self._scanning = False
        self._init_ui()
        self._connect_signals()

    def _init_ui(self) -> None:
        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(10, 14, 10, 10)

        # 1. Main Action Row
        actions = QHBoxLayout()
        self._btn_scan = QPushButton("Start Scan")
        self._btn_scan.setStyleSheet("font-weight: bold;")
        self._btn_scan.clicked.connect(lambda _: self._toggle_scan())
        actions.addWidget(self._btn_scan, 1)
        
        self._btn_reset = QPushButton("Reset")
        self._btn_reset.clicked.connect(lambda _: self._conn.send_command(CMD_LIDAR_RESET))
        actions.addWidget(self._btn_reset)
        
        self._btn_info = QPushButton("Probe")
        self._btn_info.clicked.connect(lambda _: self._probe())
        actions.addWidget(self._btn_info)
        layout.addLayout(actions)

        # 2. RPM Control Box
        rpm_box = QGroupBox("Motor RPM Control")
        rpm_layout = QVBoxLayout()
        rpm_layout.setContentsMargins(8, 12, 8, 8)
        rpm_layout.setSpacing(6)
        
        rpm_presets = QHBoxLayout()
        rpm_presets.setSpacing(4)
        for val in [0, 400, 600, 800]:
            btn = QPushButton(str(val))
            btn.setStyleSheet("padding: 4px; font-size: 10px;")
            btn.clicked.connect(lambda _, v=val: self._set_rpm(v))
            rpm_presets.addWidget(btn)
        rpm_layout.addLayout(rpm_presets)
        
        rpm_slider_row = QHBoxLayout()
        self._rpm = QSpinBox()
        self._rpm.setRange(0, 2000)
        self._rpm.setValue(660)
        self._rpm.setSingleStep(10)
        self._rpm.setSuffix(" RPM")
        self._rpm.valueChanged.connect(self._sync_init_settings)
        rpm_slider_row.addWidget(self._rpm, 1)
        
        self._btn_rpm = QPushButton("Apply")
        self._btn_rpm.clicked.connect(lambda _: self._set_rpm())
        rpm_slider_row.addWidget(self._btn_rpm)
        rpm_layout.addLayout(rpm_slider_row)
        rpm_box.setLayout(rpm_layout)
        layout.addWidget(rpm_box)

        # 3. Scan Mode Selection
        mode_box = QGroupBox("Scan Mode")
        mode_layout = QHBoxLayout()
        mode_layout.setContentsMargins(8, 12, 8, 8)
        
        self._mode_btn_std = QPushButton("Standard")
        self._mode_btn_std.setCheckable(True)
        self._mode_btn_std.setChecked(True)
        self._mode_btn_std.clicked.connect(lambda _: self._set_mode(SCAN_MODE_STANDARD))
        
        self._mode_btn_exp = QPushButton("Express")
        self._mode_btn_exp.setCheckable(True)
        self._mode_btn_exp.clicked.connect(lambda _: self._set_mode(SCAN_MODE_EXPRESS))
        
        mode_layout.addWidget(self._mode_btn_std)
        mode_layout.addWidget(self._mode_btn_exp)
        mode_box.setLayout(mode_layout)
        layout.addWidget(mode_box)

        # 4. Device Information & Health Panel
        info_box = QGroupBox("Device Metrics")
        info_layout = QGridLayout()
        info_layout.setContentsMargins(8, 12, 8, 8)
        info_layout.setVerticalSpacing(4)
        
        info_layout.addWidget(QLabel("Health:"), 0, 0)
        self._health = QLabel("--")
        self._health.setFont(QFont("Consolas", 9))
        info_layout.addWidget(self._health, 0, 1)
        
        info_layout.addWidget(QLabel("Model:"), 1, 0)
        self._info_model = QLabel("--")
        self._info_model.setFont(QFont("Consolas", 8))
        self._info_model.setStyleSheet("color: #CFD8DC;")
        info_layout.addWidget(self._info_model, 1, 1)
        
        info_layout.addWidget(QLabel("Serial:"), 2, 0)
        self._info_serial = QLabel("--")
        self._info_serial.setFont(QFont("Consolas", 8))
        self._info_serial.setStyleSheet("color: #78909C;")
        info_layout.addWidget(self._info_serial, 2, 1)
        
        info_box.setLayout(info_layout)
        layout.addWidget(info_box)

        layout.addStretch()
        self.setLayout(layout)
        self._set_controls_enabled(False)
        self.sync_init_settings()

    def _connect_signals(self) -> None:
        self._conn.device_connected.connect(self._on_connected)
        self._conn.device_disconnected.connect(self._on_disconnected)
        self._conn.status_received.connect(self._on_status)
        self._conn.response_received.connect(self._on_response)

    def _on_connected(self, _name: str, _initial_status: bytes) -> None:
        self.sync_init_settings()
        self._probe()

    def _on_disconnected(self) -> None:
        self._enabled = False
        self._scanning = False
        self._btn_scan.setText("Start Scan")
        self._set_controls_enabled(False)
        self._health.setText("--")
        self._info_model.setText("--")
        self._info_serial.setText("--")

    def _on_status(self, data: bytes) -> None:
        status = parse_status(data)
        if not status:
            return
        self._enabled = status.lidar_ok
        self._scanning = status.scan_state != SCAN_IDLE
        self._set_controls_enabled(self._enabled)
        self._btn_scan.setText("Stop Scan" if self._scanning else "Start Scan")

    def _on_response(self, data: bytes) -> None:
        resp = parse_response(data)
        if not resp:
            return
        if resp.cmd_id == CMD_LIDAR_GET_INFO and resp.ok:
            info = LidarInfo.from_bytes(resp.payload)
            if info:
                self._info_model.setText(f"M:{info.major_model} | FW:{info.firmware_str} | HW:{info.hardware}")
                self._info_serial.setText(info.serial)
        elif resp.cmd_id == CMD_LIDAR_GET_HEALTH and resp.ok:
            health = LidarHealth.from_bytes(resp.payload)
            if health:
                self._health.setText(f"{health.status_name} (err={health.error_code})")
                color = "#4CAF50" if health.is_ok else "#FF9800"
                self._health.setStyleSheet(f"color: {color}; font-weight: bold;")
        elif resp.cmd_id == CMD_START_SCAN and resp.ok:
            self._scanning = True
            self._btn_scan.setText("Stop Scan")
        elif resp.cmd_id == CMD_STOP_SCAN and resp.ok:
            self._scanning = False
            self._btn_scan.setText("Start Scan")

    def _toggle_scan(self) -> None:
        if not self._enabled:
            return
        self._conn.send_command(CMD_STOP_SCAN if self._scanning else CMD_START_SCAN)

    def _set_rpm(self, val: int | None = None) -> None:
        if not self._enabled:
            return
        if val is not None:
            self._rpm.setValue(val)
        self._conn.send_command(CMD_SET_MOTOR_RPM, struct.pack("<H", self._rpm.value()))
        self.sync_init_settings()

    def _set_mode(self, mode: int) -> None:
        if not self._enabled:
            return
        # Sync UI button states
        self._mode_btn_std.setChecked(mode == SCAN_MODE_STANDARD)
        self._mode_btn_exp.setChecked(mode == SCAN_MODE_EXPRESS)
        
        if not self._scanning:
            self._conn.send_command(CMD_LIDAR_SET_SCAN_MODE, struct.pack("B", mode))

    def _probe(self) -> None:
        if self._conn.connected:
            self._conn.send_command(CMD_LIDAR_GET_INFO)
            self._conn.send_command(CMD_LIDAR_GET_HEALTH)

    def sync_init_settings(self) -> None:
        settings = self._conn.init_ack_settings
        settings.motor_rpm = self._rpm.value()
        self._conn.init_ack_settings = settings

    def _sync_init_settings(self) -> None:
        self.sync_init_settings()

    def _set_controls_enabled(self, enabled: bool) -> None:
        for child_type in (QPushButton, QSpinBox, QComboBox):
            for child in self.findChildren(child_type):
                child.setEnabled(enabled)


class ImuControlPanel(QGroupBox):
    def __init__(self, connection: DeviceConnection, imu_panel):
        super().__init__("IMU Console")
        self._conn = connection
        self._imu_panel = imu_panel
        self._last_sync_host_ms = 0
        self._init_ui()
        self._connect_signals()

    def _connect_signals(self) -> None:
        self._imu_panel.metrics_updated.connect(self._update_metrics)
        self._imu_panel.state_changed.connect(self._update_state)
        self._conn.device_connected.connect(self._on_connected)
        self._conn.device_disconnected.connect(self._on_disconnected)
        self._conn.response_received.connect(self._on_response)

    def _init_ui(self) -> None:
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(10, 14, 10, 10)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        self._labels: dict[str, QLabel] = {}
        items = [
            ("Rate", "rate"),
            ("Age", "age"),
            ("Roll", "roll"),
            ("Pitch", "pitch"),
            ("Yaw", "yaw"),
            ("Accel", "accel"),
            ("Gyro", "gyro"),
            ("Position", "position"),
        ]
        for row, (title, key) in enumerate(items):
            label = QLabel(title)
            label.setStyleSheet("color: #78909C;")
            value = QLabel("--")
            value.setFont(QFont("Consolas", 9))
            value.setStyleSheet("color: #CFD8DC;")
            grid.addWidget(label, row, 0)
            grid.addWidget(value, row, 1)
            self._labels[key] = value
        layout.addLayout(grid)

        action_row = QHBoxLayout()
        self._btn_zero_yaw = QPushButton("Zero Yaw")
        self._btn_zero_yaw.clicked.connect(lambda _: self._imu_panel.zero_yaw())
        action_row.addWidget(self._btn_zero_yaw)
        self._btn_clear_trail = QPushButton("Clear Trail")
        self._btn_clear_trail.clicked.connect(lambda _: self._imu_panel.clear_trail())
        action_row.addWidget(self._btn_clear_trail)
        layout.addLayout(action_row)

        self._btn_reset = QPushButton("Reset Filter")
        self._btn_reset.clicked.connect(lambda _: self._imu_panel.reset_filter())
        layout.addWidget(self._btn_reset)

        protocol_box = QGroupBox("Protocol")
        protocol_layout = QVBoxLayout()
        protocol_layout.setSpacing(6)

        preview_row = QHBoxLayout()
        rate_lbl = QLabel("Rate:")
        rate_lbl.setStyleSheet("color: #78909C; font-size: 11px;")
        preview_row.addWidget(rate_lbl)
        self._preview_interval = QSpinBox()
        self._preview_interval.setRange(20, 1000)
        self._preview_interval.setValue(50)
        self._preview_interval.setSuffix(" ms")
        preview_row.addWidget(self._preview_interval)
        
        self._btn_toggle_preview = QPushButton("Start Monitor")
        self._btn_toggle_preview.clicked.connect(lambda _: self._toggle_preview())
        preview_row.addWidget(self._btn_toggle_preview)
        protocol_layout.addLayout(preview_row)

        protocol_actions = QHBoxLayout()
        self._btn_protocol = QPushButton("Protocol Info")
        self._btn_protocol.clicked.connect(lambda _: self._conn.send_command(CMD_GET_PROTOCOL_INFO))
        protocol_actions.addWidget(self._btn_protocol)
        self._btn_time_sync = QPushButton("Time Sync")
        self._btn_time_sync.clicked.connect(lambda _: self._request_time_sync())
        protocol_actions.addWidget(self._btn_time_sync)
        protocol_layout.addLayout(protocol_actions)

        self._protocol_info = QLabel("Protocol: --")
        self._protocol_info.setFont(QFont("Consolas", 8))
        self._protocol_info.setStyleSheet("color: #78909C;")
        self._protocol_info.setWordWrap(True)
        protocol_layout.addWidget(self._protocol_info)
        protocol_box.setLayout(protocol_layout)
        layout.addWidget(protocol_box)

        layout.addStretch()
        self.setLayout(layout)
        self._set_protocol_controls_enabled(False)

    def _on_connected(self, _name: str, _initial_status: bytes) -> None:
        self._set_protocol_controls_enabled(True)
        self._conn.send_command(CMD_GET_PROTOCOL_INFO)

    def _on_disconnected(self) -> None:
        self._set_protocol_controls_enabled(False)
        self._protocol_info.setText("Protocol: --")

    def _on_response(self, data: bytes) -> None:
        resp = parse_response(data)
        if not resp:
            return
        if resp.cmd_id == CMD_GET_PROTOCOL_INFO:
            if not resp.ok:
                self._protocol_info.setText(f"Protocol info failed: {resp.result_name}")
                return
            info = ProtocolInfo.from_bytes(resp.payload)
            if not info:
                self._protocol_info.setText("Protocol info parse failed")
                return
            self._is_previewing = info.imu_preview_enabled
            self._sync_preview_button()
            if info.imu_interval_ms:
                self._preview_interval.setValue(max(20, min(1000, info.imu_interval_ms)))
            self._protocol_info.setText(
                f"Protocol v{info.version} | IMU {'ON' if info.imu_preview_enabled else 'OFF'} "
                f"@ {info.imu_interval_ms} ms\nCaps: {info.capability_str}"
            )
        elif resp.cmd_id == CMD_TIME_SYNC:
            if not resp.ok:
                self._protocol_info.setText(f"Time sync failed: {resp.result_name}")
                return
            sync = TimeSyncInfo.from_bytes(resp.payload)
            if not sync:
                self._protocol_info.setText("Time sync parse failed")
                return
            host_now_ms = int(time.monotonic() * 1000)
            elapsed = max(0, host_now_ms - self._last_sync_host_ms) if self._last_sync_host_ms else 0
            self._protocol_info.setText(
                f"Device time {sync.device_time_us / 1_000_000:.3f}s | tick {sync.device_tick_ms} ms | "
                f"RTT~{elapsed} ms"
            )
        elif resp.cmd_id == CMD_IMU_SET_PREVIEW:
            self._sync_preview_button()
            if not resp.ok:
                self._protocol_info.setText(f"IMU preview failed: {resp.result_name}")
                return
            if len(resp.payload) >= 3:
                enabled = resp.payload[0] != 0
                interval = struct.unpack_from("<H", resp.payload, 1)[0]
                self._is_previewing = enabled
                self._sync_preview_button()
                self._preview_interval.setValue(max(20, min(1000, interval)))
                self._protocol_info.setText(f"IMU preview {'ON' if enabled else 'OFF'} @ {interval} ms")

    def _toggle_preview(self) -> None:
        new_state = not self._is_previewing
        self._btn_toggle_preview.setEnabled(False)
        payload = struct.pack("<BH", int(new_state), self._preview_interval.value())
        self._conn.send_command(CMD_IMU_SET_PREVIEW, payload)

    def _sync_preview_button(self) -> None:
        self._btn_toggle_preview.setEnabled(True)
        self._btn_toggle_preview.setText("Stop Monitor" if self._is_previewing else "Start Monitor")
        if self._is_previewing:
            self._btn_toggle_preview.setStyleSheet(
                "QPushButton { background-color: #3B1D1D; color: #F44336; border: 1px solid #E53935; }"
                "QPushButton:hover { background-color: #4A2525; }"
            )
        else:
            self._btn_toggle_preview.setStyleSheet("")

    def _request_time_sync(self) -> None:
        self._last_sync_host_ms = int(time.monotonic() * 1000)
        self._conn.send_command(CMD_TIME_SYNC)

    def _set_protocol_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self._preview_interval,
            self._btn_toggle_preview,
            self._btn_protocol,
            self._btn_time_sync,
        ):
            widget.setEnabled(enabled)

    def _update_state(self, online: bool, message: str) -> None:
        # Status header removed to clean up duplicate UI. Logic preserved for future needs if any.
        pass

    def _update_metrics(self, snapshot: dict) -> None:
        age_text = "--" if snapshot["age_ms"] is None else f'{snapshot["age_ms"]} ms'
        self._labels["rate"].setText(f'{snapshot["sample_rate_hz"]:.1f} Hz')
        self._labels["age"].setText(age_text)
        self._labels["roll"].setText(f'{snapshot["roll_deg"]:.1f} deg')
        self._labels["pitch"].setText(f'{snapshot["pitch_deg"]:.1f} deg')
        self._labels["yaw"].setText(f'{snapshot["yaw_deg"]:.1f} deg')
        self._labels["accel"].setText(
            f'{snapshot["accel"][0]:+.2f}, {snapshot["accel"][1]:+.2f}, {snapshot["accel"][2]:+.2f} g'
        )
        self._labels["gyro"].setText(
            f'{snapshot["gyro"][0]:+.1f}, {snapshot["gyro"][1]:+.1f}, {snapshot["gyro"][2]:+.1f} dps'
        )
        self._labels["position"].setText(
            f'{snapshot["position"][0]:+.2f}, {snapshot["position"][1]:+.2f}, {snapshot["position"][2]:+.2f} m'
        )


class MappingControlPanel(QGroupBox):
    def __init__(self, map_panel, toggle_demo: Callable[[], None]):
        super().__init__("2.5D Mapping")
        self._map_panel = map_panel
        self._toggle_demo = toggle_demo
        self._demo_running = False
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(10, 14, 10, 10)

        self._status = QLabel("Waiting for fusion input")
        self._status.setFont(QFont("Consolas", 10))
        self._status.setStyleSheet("color: #FF9800; font-weight: bold;")
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

        self._btn_demo = QPushButton("Start Demo")
        self._btn_demo.clicked.connect(self._toggle_demo)
        layout.addWidget(self._btn_demo)

        self._btn_clear = QPushButton("Clear Map")
        self._btn_clear.clicked.connect(self._map_panel.clear_map)
        layout.addWidget(self._btn_clear)

        layout.addStretch()
        self.setLayout(layout)

    def set_demo_running(self, running: bool) -> None:
        self._demo_running = running
        self._btn_demo.setText("Stop Demo" if running else "Start Demo")

    def set_sensor_state(self, lidar_ok: bool, imu_ok: bool) -> None:
        if lidar_ok and imu_ok:
            self._status.setText("Fusion input live")
            self._status.setStyleSheet("color: #4CAF50; font-weight: bold;")
        elif lidar_ok or imu_ok:
            self._status.setText("Partial input only")
            self._status.setStyleSheet("color: #FF9800; font-weight: bold;")
        else:
            self._status.setText("Waiting for fusion input")
            self._status.setStyleSheet("color: #FF9800; font-weight: bold;")

    def update_snapshot(self, snapshot: dict) -> None:
        self._labels["frames"].setText(str(snapshot["frames"]))
        self._labels["yaw"].setText(f'{snapshot["yaw_deg"]:.1f} deg')
        self._labels["window"].setText(f'{snapshot["horizon_s"]:.1f} s')
