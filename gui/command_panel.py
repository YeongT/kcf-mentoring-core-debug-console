"""Command panel with buttons for all device commands."""

import struct

from PyQt6.QtWidgets import (
    QGroupBox,
    QGridLayout,
    QVBoxLayout,
    QPushButton,
    QSpinBox,
    QLabel,
    QHBoxLayout,
    QWidget,
    QComboBox,
    QCheckBox,
)
from PyQt6.QtCore import pyqtSignal

from protocol import (
    CMD_GET_STATUS,
    CMD_START_SCAN,
    CMD_STOP_SCAN,
    CMD_SET_MOTOR_RPM,
    CMD_START_STREAM,
    CMD_STOP_STREAM,
    CMD_CAPTURE_FRAME,
    CMD_SET_CAMERA_CONFIG,
    CMD_GET_DEVICE_INFO,
    CMD_REBOOT,
    CMD_LIDAR_GET_INFO,
    CMD_LIDAR_GET_HEALTH,
    CMD_LIDAR_RESET,
    CMD_LIDAR_SET_SCAN_MODE,
    SCAN_MODE_STANDARD,
    SCAN_MODE_EXPRESS,
    CMD_CAMERA_GET_INFO,
    CMD_CAMERA_SET_PARAM,
    CAMERA_PARAM_BRIGHTNESS,
    CAMERA_PARAM_CONTRAST,
    CAMERA_PARAM_SATURATION,
    CAMERA_PARAM_EFFECT,
    CAMERA_PARAM_WHITEBAL,
    CAMERA_PARAM_EXPOSURE,
    CAMERA_PARAM_AEC_VALUE,
    CAMERA_PARAM_HMIRROR,
    CAMERA_PARAM_VFLIP,
    CAMERA_EFFECTS,
    CMD_NAMES,
    INIT_FLAG_START_STREAM,
    SCAN_IDLE,
    SCAN_SCANNING,
    SCAN_MODE_NAMES,
    parse_status,
    parse_response,
    LidarInfo,
    LidarHealth,
    CameraInfo,
    DeviceInfo,
    build_camera_set_param,
    CAMERA_RESOLUTIONS,
    CAMERA_QUALITIES,
    DEFAULT_CAMERA_RESOLUTION,
    DEFAULT_CAMERA_QUALITY,
)
from ws_server import DeviceConnection


_STYLE_DISABLED = "background-color: #1a1a1a; color: #3a3a3a; border-color: #2a2a2a;"
_STYLE_SCAN_OFF = "background-color: #4CAF50; color: white;"
_STYLE_SCAN_ON = "background-color: #F44336; color: white;"
_STYLE_STREAM_OFF = "background-color: #2196F3; color: white;"
_STYLE_STREAM_ON = "background-color: #F44336; color: white;"


class CommandPanel(QGroupBox):
    reset_requested = pyqtSignal()

    def __init__(self, connection: DeviceConnection):
        super().__init__("Commands")
        self._conn = connection
        self._scanning = False
        self._streaming = False
        self._reconnecting = False
        self._init_ui()
        self._set_enabled(False)
        connection.device_connected.connect(self._on_connected)
        connection.device_disconnected.connect(self._on_disconnected)
        connection.status_received.connect(self._on_status)
        connection.response_received.connect(self._on_response)

    def _init_ui(self) -> None:
        layout = QVBoxLayout()
        layout.setSpacing(6)
        layout.setContentsMargins(10, 14, 10, 6)

        # Button container (grid switches between 3x2 and 2x3)
        self._btn_container = QWidget()
        layout.addWidget(self._btn_container, 0)

        self._btn_stream = QPushButton("Start Stream")
        self._btn_stream.setStyleSheet(_STYLE_STREAM_OFF)
        self._btn_stream.clicked.connect(self._toggle_stream)

        self._btn_scan = QPushButton("Start Scan")
        self._btn_scan.setStyleSheet(_STYLE_SCAN_OFF)
        self._btn_scan.clicked.connect(self._toggle_scan)

        self._btn_status = QPushButton("Get Status")
        self._btn_status.clicked.connect(lambda: self._send(CMD_GET_STATUS))

        self._btn_capture = QPushButton("Capture")
        self._btn_capture.clicked.connect(lambda: self._send(CMD_CAPTURE_FRAME))

        self._btn_reconnect = QPushButton("Reconnect")
        self._btn_reconnect.clicked.connect(self._do_reconnect)

        self._btn_reset = QPushButton("Reset")
        self._btn_reset.setStyleSheet("background-color: #FF9800; color: white;")
        self._btn_reset.clicked.connect(self.reset_requested.emit)

        self._btn_apply_camera = QPushButton("Apply")
        self._btn_apply_camera.clicked.connect(self._send_camera_config)

        # --- Separator ---
        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: #333;")
        layout.addWidget(sep)

        # Params container (layout switches between wide/narrow)
        self._params_container = QWidget()
        layout.addWidget(self._params_container, 0)

        self._lbl_interval = QLabel("Interval")
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(10, 1000)
        self._interval_spin.setValue(50)
        self._interval_spin.setSingleStep(10)
        self._interval_spin.setSuffix(" ms")
        self._interval_spin.setToolTip("Camera stream frame interval (lower = faster)")
        self._interval_spin.valueChanged.connect(self._on_interval_changed)

        self._lbl_rpm = QLabel("RPM")
        self._rpm_spin = QSpinBox()
        self._rpm_spin.setRange(0, 2000)
        self._rpm_spin.setValue(660)
        self._rpm_spin.setSingleStep(10)
        self._btn_rpm = QPushButton("Set")
        self._btn_rpm.clicked.connect(self._send_rpm)

        # Camera config controls
        self._lbl_resolution = QLabel("Resolution")
        self._resolution_combo = QComboBox()
        for name in CAMERA_RESOLUTIONS:
            self._resolution_combo.addItem(name, CAMERA_RESOLUTIONS[name])
        self._resolution_combo.setCurrentText(DEFAULT_CAMERA_RESOLUTION)

        self._lbl_quality = QLabel("Quality")
        self._quality_combo = QComboBox()
        for name in CAMERA_QUALITIES:
            self._quality_combo.addItem(name, CAMERA_QUALITIES[name])
        self._quality_combo.setCurrentText(DEFAULT_CAMERA_QUALITY)

        self._params_vsep = QLabel()
        self._params_vsep.setFixedWidth(1)
        self._params_vsep.setStyleSheet("background-color: #333;")

        self._params_hsep = QLabel()
        self._params_hsep.setFixedHeight(1)
        self._params_hsep.setStyleSheet("background-color: #333;")

        self._params_hsep2 = QLabel()
        self._params_hsep2.setFixedHeight(1)
        self._params_hsep2.setStyleSheet("background-color: #333;")

        # --- Camera Advanced Controls ---
        self._camera_adv_container = QWidget()
        layout.addWidget(self._camera_adv_container, 0)

        self._brightness_spin = QSpinBox()
        self._brightness_spin.setRange(-2, 2)
        self._brightness_spin.setValue(0)
        self._brightness_spin.valueChanged.connect(
            lambda v: self._send_camera_param(CAMERA_PARAM_BRIGHTNESS, v)
        )

        self._contrast_spin = QSpinBox()
        self._contrast_spin.setRange(-2, 2)
        self._contrast_spin.setValue(0)
        self._contrast_spin.valueChanged.connect(
            lambda v: self._send_camera_param(CAMERA_PARAM_CONTRAST, v)
        )

        self._saturation_spin = QSpinBox()
        self._saturation_spin.setRange(-2, 2)
        self._saturation_spin.setValue(0)
        self._saturation_spin.valueChanged.connect(
            lambda v: self._send_camera_param(CAMERA_PARAM_SATURATION, v)
        )

        self._effect_combo = QComboBox()
        for val, name in CAMERA_EFFECTS.items():
            self._effect_combo.addItem(name, val)
        self._effect_combo.currentIndexChanged.connect(
            lambda: self._send_camera_param(
                CAMERA_PARAM_EFFECT, self._effect_combo.currentData()
            )
        )

        self._whitebal_check = QCheckBox("White Balance")
        self._whitebal_check.setChecked(True)
        self._whitebal_check.toggled.connect(
            lambda v: self._send_camera_param(CAMERA_PARAM_WHITEBAL, int(v))
        )

        self._exposure_check = QCheckBox("Auto Exposure")
        self._exposure_check.setChecked(True)
        self._exposure_check.toggled.connect(
            lambda v: self._send_camera_param(CAMERA_PARAM_EXPOSURE, int(v))
        )

        self._aec_spin = QSpinBox()
        self._aec_spin.setRange(0, 1200)
        self._aec_spin.setValue(300)
        self._aec_spin.setSingleStep(50)
        self._aec_spin.valueChanged.connect(
            lambda v: self._send_camera_param(CAMERA_PARAM_AEC_VALUE, v)
        )

        self._hmirror_check = QCheckBox("H-Mirror")
        self._hmirror_check.toggled.connect(
            lambda v: self._send_camera_param(CAMERA_PARAM_HMIRROR, int(v))
        )

        self._vflip_check = QCheckBox("V-Flip")
        self._vflip_check.toggled.connect(
            lambda v: self._send_camera_param(CAMERA_PARAM_VFLIP, int(v))
        )

        self._btn_camera_info = QPushButton("Cam Info")
        self._btn_camera_info.clicked.connect(lambda: self._send(CMD_CAMERA_GET_INFO))

        # --- LiDAR Controls ---
        self._lidar_ctrl_container = QWidget()
        layout.addWidget(self._lidar_ctrl_container, 0)

        self._btn_lidar_info = QPushButton("Info")
        self._btn_lidar_info.clicked.connect(lambda: self._send(CMD_LIDAR_GET_INFO))

        self._btn_lidar_health = QPushButton("Health")
        self._btn_lidar_health.clicked.connect(lambda: self._send(CMD_LIDAR_GET_HEALTH))

        self._btn_lidar_reset = QPushButton("Reset")
        self._btn_lidar_reset.clicked.connect(lambda: self._send(CMD_LIDAR_RESET))

        # RPM preset buttons
        self._rpm_presets: list[QPushButton] = []
        for rpm_val in (330, 660, 1000, 1500):
            btn = QPushButton(str(rpm_val))
            btn.setToolTip(f"Set RPM to {rpm_val}")
            btn.clicked.connect(lambda _, r=rpm_val: self._send_rpm_preset(r))
            self._rpm_presets.append(btn)

        # Inline status labels
        self._lidar_health_label = QLabel("Health: --")
        self._lidar_health_label.setStyleSheet("color: #888; font-size: 10px;")
        self._lidar_info_label = QLabel("Model: -- | FW: -- | HW: --")
        self._lidar_info_label.setStyleSheet("color: #888; font-size: 10px;")
        self._lidar_info_label.setWordWrap(True)

        # Scan mode selector
        self._scan_mode = SCAN_MODE_STANDARD
        self._btn_scan_standard = QPushButton("Standard")
        self._btn_scan_standard.setCheckable(True)
        self._btn_scan_standard.setChecked(True)
        self._btn_scan_standard.clicked.connect(lambda: self._set_scan_mode(SCAN_MODE_STANDARD))

        self._btn_scan_express = QPushButton("Express")
        self._btn_scan_express.setCheckable(True)
        self._btn_scan_express.clicked.connect(lambda: self._set_scan_mode(SCAN_MODE_EXPRESS))

        self._scan_mode_buttons = [self._btn_scan_standard, self._btn_scan_express]

        # --- Device Controls (shown in all sidebar views) ---
        self._btn_device_info = QPushButton("Dev Info")
        self._btn_device_info.clicked.connect(lambda: self._send(CMD_GET_DEVICE_INFO))

        self._btn_reboot = QPushButton("Reboot")
        self._btn_reboot.setStyleSheet("background-color: #D32F2F; color: white;")
        self._btn_reboot.clicked.connect(lambda: self._send(CMD_REBOOT))

        self._sidebar_mode = False
        self._current_view = "split"
        self._apply_button_grid()
        self._apply_params_layout()

        layout.addStretch(1)
        self.setLayout(layout)

    def _on_connected(self, _name: str, _initial_status: bytes) -> None:
        self._reconnecting = False
        self._btn_reconnect.setText("Reconnect")
        self._btn_reconnect.setStyleSheet("")
        self._set_enabled(True)
        # Sync UI settings into INIT_ACK for this and future connections
        self._sync_init_settings()
        # Apply initial status from INIT handshake
        if _initial_status:
            self._on_status(_initial_status)

    def _on_disconnected(self) -> None:
        self._scanning = False
        self._streaming = False
        self._sync_init_settings()
        self._btn_scan.setText("Start Scan")
        self._btn_stream.setText("Start Stream")
        self.reset_lidar_state()
        self._set_enabled(False)
        if self._reconnecting:
            self._btn_reconnect.setText("Reconnecting...")
            self._btn_reconnect.setStyleSheet("background-color: #FF9800; color: white;")

    def _on_status(self, data: bytes) -> None:
        status = parse_status(data)
        if not status:
            return
        self._scanning = status.scan_state == SCAN_SCANNING
        self._streaming = bool(status.camera_streaming)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        if self._scanning:
            self._btn_scan.setText("Stop Scan")
            self._btn_scan.setStyleSheet(_STYLE_SCAN_ON)
        else:
            self._btn_scan.setText("Start Scan")
            self._btn_scan.setStyleSheet(_STYLE_SCAN_OFF)
        self._btn_scan.setEnabled(True)

        if self._streaming:
            self._btn_stream.setText("Stop Stream")
            self._btn_stream.setStyleSheet(_STYLE_STREAM_ON)
        else:
            self._btn_stream.setText("Start Stream")
            self._btn_stream.setStyleSheet(_STYLE_STREAM_OFF)
        self._btn_stream.setEnabled(True)

    def _set_enabled(self, enabled: bool) -> None:
        for child in self.findChildren(QPushButton):
            child.setEnabled(enabled)
        for child in self.findChildren(QSpinBox):
            child.setEnabled(enabled)
        for child in self.findChildren(QComboBox):
            child.setEnabled(enabled)
        for child in self.findChildren(QCheckBox):
            child.setEnabled(enabled)
        if not enabled:
            self._btn_stream.setStyleSheet(_STYLE_DISABLED)
            self._btn_scan.setStyleSheet(_STYLE_DISABLED)

    def set_sidebar_mode(self, sidebar: bool, view: str = "split") -> None:
        if sidebar == self._sidebar_mode and view == self._current_view:
            return
        self._sidebar_mode = sidebar
        self._current_view = view
        self._apply_button_grid()
        self._apply_params_layout()
        # Re-apply connection state after layout rebuild
        if not self._conn.connected:
            self._set_enabled(False)
        else:
            self._sync_buttons()

    def _apply_button_grid(self) -> None:
        old = self._btn_container.layout()
        if old is not None:
            while old.count():
                old.takeAt(0)
            QWidget().setLayout(old)

        grid = QGridLayout()
        grid.setSpacing(4)
        grid.setContentsMargins(0, 0, 0, 0)

        view = self._current_view
        if view == "camera":
            # Camera-specific buttons only
            buttons = [
                self._btn_stream, self._btn_capture,
                self._btn_status, self._btn_reconnect,
            ]
        elif view == "lidar":
            # LiDAR-specific buttons only
            buttons = [
                self._btn_scan, self._btn_status,
                self._btn_reboot, self._btn_reconnect,
            ]
        else:
            # Split: all main buttons including Reboot
            buttons = [
                self._btn_stream, self._btn_scan, self._btn_status,
                self._btn_capture, self._btn_reboot, self._btn_reconnect,
            ]

        # Hide buttons not in current view
        all_action_buttons = [
            self._btn_stream, self._btn_scan, self._btn_status,
            self._btn_capture, self._btn_reconnect, self._btn_reset,
            self._btn_reboot,
        ]
        for btn in all_action_buttons:
            btn.setVisible(btn in buttons)

        if self._sidebar_mode:
            cols = 2
        else:
            cols = 3
        for i, btn in enumerate(buttons):
            grid.addWidget(btn, i // cols, i % cols)

        self._btn_container.setLayout(grid)

    def _apply_params_layout(self) -> None:
        # Clear existing layouts
        for container in (self._params_container, self._camera_adv_container, self._lidar_ctrl_container):
            old = container.layout()
            if old is not None:
                while old.count():
                    old.takeAt(0)
                QWidget().setLayout(old)

        view = self._current_view
        show_camera = view in ("split", "camera")
        show_lidar = view in ("split", "lidar")
        is_camera_sidebar = self._sidebar_mode and view == "camera"
        is_lidar_sidebar = self._sidebar_mode and view == "lidar"

        # Camera basic params
        for w in [self._lbl_interval, self._interval_spin,
                  self._lbl_resolution, self._resolution_combo,
                  self._lbl_quality, self._quality_combo, self._btn_apply_camera]:
            w.setVisible(show_camera)

        # LiDAR basic params (RPM spinner only in split or lidar view)
        for w in [self._lbl_rpm, self._rpm_spin, self._btn_rpm]:
            w.setVisible(show_lidar)

        # Camera advanced controls only in camera sidebar
        for w in [self._brightness_spin, self._contrast_spin, self._saturation_spin,
                  self._effect_combo, self._whitebal_check, self._exposure_check,
                  self._aec_spin, self._hmirror_check, self._vflip_check,
                  self._btn_camera_info]:
            w.setVisible(is_camera_sidebar)

        # LiDAR extended controls only in lidar sidebar
        for w in [self._btn_lidar_info, self._btn_lidar_health, self._btn_lidar_reset,
                  self._lidar_health_label, self._lidar_info_label,
                  *self._rpm_presets, *self._scan_mode_buttons]:
            w.setVisible(is_lidar_sidebar)

        # Device info button: in camera/lidar sidebar bottom rows
        self._btn_device_info.setVisible(is_camera_sidebar or is_lidar_sidebar)

        self._camera_adv_container.setVisible(is_camera_sidebar)
        self._lidar_ctrl_container.setVisible(is_lidar_sidebar)

        if self._sidebar_mode:
            # --- Params section (vertical layout for sidebar) ---
            vbox = QVBoxLayout()
            vbox.setContentsMargins(0, 0, 0, 0)
            vbox.setSpacing(4)
            self._params_vsep.hide()
            self._params_hsep.hide()
            self._params_hsep2.hide()

            if show_camera:
                for lbl, widget in [(self._lbl_interval, self._interval_spin),
                                    (self._lbl_resolution, self._resolution_combo)]:
                    row = QHBoxLayout()
                    row.setSpacing(8)
                    row.addWidget(lbl)
                    row.addWidget(widget)
                    row.addStretch()
                    vbox.addLayout(row)
                row_q = QHBoxLayout()
                row_q.setSpacing(8)
                row_q.addWidget(self._lbl_quality)
                row_q.addWidget(self._quality_combo)
                row_q.addWidget(self._btn_apply_camera)
                row_q.addStretch()
                vbox.addLayout(row_q)

            if show_lidar:
                row_rpm = QHBoxLayout()
                row_rpm.setSpacing(8)
                row_rpm.addWidget(self._lbl_rpm)
                row_rpm.addWidget(self._rpm_spin)
                row_rpm.addWidget(self._btn_rpm)
                row_rpm.addStretch()
                vbox.addLayout(row_rpm)

            self._params_container.setLayout(vbox)

            # --- Camera advanced section ---
            if is_camera_sidebar:
                adv = QVBoxLayout()
                adv.setContentsMargins(0, 0, 0, 0)
                adv.setSpacing(3)

                sep = QLabel()
                sep.setFixedHeight(1)
                sep.setStyleSheet("background-color: #333;")
                adv.addWidget(sep)

                lbl = QLabel("Sensor Controls")
                lbl.setStyleSheet("color: #888; font-size: 10px; font-weight: bold;")
                adv.addLayout(self._make_param_row(lbl, None))

                adv.addLayout(self._make_param_row(QLabel("Brightness"), self._brightness_spin))
                adv.addLayout(self._make_param_row(QLabel("Contrast"), self._contrast_spin))
                adv.addLayout(self._make_param_row(QLabel("Saturation"), self._saturation_spin))
                adv.addLayout(self._make_param_row(QLabel("Effect"), self._effect_combo))
                adv.addLayout(self._make_param_row(QLabel("AEC Value"), self._aec_spin))

                checks_row = QHBoxLayout()
                checks_row.setSpacing(8)
                checks_row.addWidget(self._whitebal_check)
                checks_row.addWidget(self._exposure_check)
                checks_row.addStretch()
                adv.addLayout(checks_row)

                checks_row2 = QHBoxLayout()
                checks_row2.setSpacing(8)
                checks_row2.addWidget(self._hmirror_check)
                checks_row2.addWidget(self._vflip_check)
                checks_row2.addStretch()
                adv.addLayout(checks_row2)

                btn_row = QHBoxLayout()
                btn_row.setSpacing(4)
                btn_row.addWidget(self._btn_camera_info)
                btn_row.addWidget(self._btn_device_info)
                btn_row.addStretch()
                adv.addLayout(btn_row)

                self._camera_adv_container.setLayout(adv)

            # --- LiDAR controls section ---
            if is_lidar_sidebar:
                lctrl = QVBoxLayout()
                lctrl.setContentsMargins(0, 0, 0, 0)
                lctrl.setSpacing(4)

                sep = QLabel()
                sep.setFixedHeight(1)
                sep.setStyleSheet("background-color: #333;")
                lctrl.addWidget(sep)

                lbl = QLabel("LiDAR Controls")
                lbl.setStyleSheet("color: #888; font-size: 10px; font-weight: bold;")
                lctrl.addLayout(self._make_param_row(lbl, None))

                # RPM presets
                rpm_lbl = QLabel("RPM")
                rpm_lbl.setStyleSheet("color: #666; font-size: 9px;")
                lctrl.addWidget(rpm_lbl)
                rpm_row = QHBoxLayout()
                rpm_row.setSpacing(0)
                for i, btn in enumerate(self._rpm_presets):
                    extra = (self._GRP_FIRST if i == 0 else "") + (self._GRP_LAST if i == len(self._rpm_presets) - 1 else "")
                    btn.setStyleSheet(self._GRP_BTN + f"min-width: 36px;{extra}")
                    rpm_row.addWidget(btn)
                rpm_row.addStretch()
                lctrl.addLayout(rpm_row)

                # Scan mode
                mode_lbl = QLabel("Mode")
                mode_lbl.setStyleSheet("color: #666; font-size: 9px;")
                lctrl.addWidget(mode_lbl)
                mode_row = QHBoxLayout()
                mode_row.setSpacing(0)
                for i, btn in enumerate(self._scan_mode_buttons):
                    is_active = btn.isChecked()
                    base = self._GRP_ON if is_active else self._GRP_BTN
                    extra = (self._GRP_FIRST if i == 0 else "") + (self._GRP_LAST if i == len(self._scan_mode_buttons) - 1 else "")
                    btn.setStyleSheet(base + f"min-width: 56px;{extra}")
                    mode_row.addWidget(btn)
                mode_row.addStretch()
                lctrl.addLayout(mode_row)

                # Query buttons
                btn_row1 = QHBoxLayout()
                btn_row1.setSpacing(3)
                btn_row1.addWidget(self._btn_lidar_info)
                btn_row1.addWidget(self._btn_lidar_health)
                btn_row1.addWidget(self._btn_lidar_reset)
                lctrl.addLayout(btn_row1)

                # Inline status display
                sep2 = QLabel()
                sep2.setFixedHeight(1)
                sep2.setStyleSheet("background-color: #333;")
                lctrl.addWidget(sep2)

                lctrl.addWidget(self._lidar_health_label)
                lctrl.addWidget(self._lidar_info_label)

                # Device info at bottom
                sep3 = QLabel()
                sep3.setFixedHeight(1)
                sep3.setStyleSheet("background-color: #333;")
                lctrl.addWidget(sep3)

                bottom_row = QHBoxLayout()
                bottom_row.setSpacing(3)
                bottom_row.addWidget(self._btn_device_info)
                bottom_row.addStretch()
                lctrl.addLayout(bottom_row)

                self._lidar_ctrl_container.setLayout(lctrl)
        else:
            # Split mode: all params in horizontal rows
            vbox = QVBoxLayout()
            vbox.setContentsMargins(0, 0, 0, 0)
            vbox.setSpacing(4)
            row1 = QHBoxLayout()
            row1.setSpacing(8)
            row1.addWidget(self._lbl_interval)
            row1.addWidget(self._interval_spin)
            self._params_vsep.show()
            self._params_hsep.hide()
            self._params_hsep2.hide()
            row1.addWidget(self._params_vsep)
            row1.addWidget(self._lbl_rpm)
            row1.addWidget(self._rpm_spin)
            row1.addWidget(self._btn_rpm)
            vbox.addLayout(row1)
            row2 = QHBoxLayout()
            row2.setSpacing(8)
            row2.addWidget(self._lbl_resolution)
            row2.addWidget(self._resolution_combo)
            row2.addWidget(self._lbl_quality)
            row2.addWidget(self._quality_combo)
            row2.addWidget(self._btn_apply_camera)
            vbox.addLayout(row2)
            self._params_container.setLayout(vbox)

    @staticmethod
    def _make_param_row(label: QLabel, widget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(label)
        if widget is not None:
            row.addWidget(widget)
        row.addStretch()
        return row

    def _on_interval_changed(self, value: int) -> None:
        if self._streaming:
            self._conn.log_message.emit(f"User command: START_STREAM interval={value}ms")
            self._conn.send_command(CMD_START_STREAM, struct.pack("<H", value))
        self._sync_init_settings()

    def _sync_init_settings(self) -> None:
        """Update INIT_ACK settings so next reconnect uses current values."""
        s = self._conn.init_ack_settings
        s.stream_interval_ms = self._interval_spin.value()
        s.motor_rpm = self._rpm_spin.value()
        s.camera_resolution = self._resolution_combo.currentData()
        s.camera_quality = self._quality_combo.currentData()
        if self._streaming:
            s.flags |= INIT_FLAG_START_STREAM
        else:
            s.flags &= ~INIT_FLAG_START_STREAM
        self._conn.init_ack_settings = s

    def _on_response(self, data: bytes) -> None:
        resp = parse_response(data)
        if not resp:
            return

        # Scan state
        if resp.cmd_id == CMD_START_SCAN:
            self._scanning = resp.ok
            self._sync_buttons()
        elif resp.cmd_id == CMD_STOP_SCAN:
            if resp.ok:
                self._scanning = False
            self._sync_buttons()

        # Stream state
        elif resp.cmd_id == CMD_START_STREAM:
            self._streaming = resp.ok
            self._sync_buttons()
        elif resp.cmd_id == CMD_STOP_STREAM:
            if resp.ok:
                self._streaming = False
            self._sync_buttons()

        # LiDAR info/health
        elif resp.cmd_id == CMD_LIDAR_GET_INFO and resp.ok:
            info = LidarInfo.from_bytes(resp.payload)
            if info:
                self.update_lidar_info(info)
                self._conn.log_message.emit(
                    f"LidarInfo: model={info.major_model} FW={info.firmware_str} "
                    f"HW={info.hardware} Serial={info.serial}"
                )
        elif resp.cmd_id == CMD_LIDAR_GET_HEALTH and resp.ok:
            health = LidarHealth.from_bytes(resp.payload)
            if health:
                self.update_lidar_health(health)
                self._conn.log_message.emit(
                    f"LidarHealth: {health.status_name} (error_code={health.error_code})"
                )
        elif resp.cmd_id == CMD_LIDAR_SET_SCAN_MODE and resp.ok:
            if len(resp.payload) >= 1:
                mode = resp.payload[0]
                name = SCAN_MODE_NAMES.get(mode, f"Unknown({mode})")
                self._conn.log_message.emit(f"Scan mode set to: {name}")

        # Camera info
        elif resp.cmd_id == CMD_CAMERA_GET_INFO and resp.ok:
            info = CameraInfo.from_bytes(resp.payload)
            if info:
                self._conn.log_message.emit(
                    f"CameraInfo: {info.model} | res={info.resolution} "
                    f"quality={info.quality} streaming={'ON' if info.streaming else 'OFF'}"
                )

        # Device info
        elif resp.cmd_id == CMD_GET_DEVICE_INFO and resp.ok:
            info = DeviceInfo.from_bytes(resp.payload)
            if info:
                self._conn.log_message.emit(
                    f"DeviceInfo: {info.device_name} | chip={info.chip_model} "
                    f"cores={info.chip_cores} rev={info.chip_revision} | "
                    f"heap={info.free_heap // 1024}K/{info.min_free_heap // 1024}K | "
                    f"PSRAM={info.psram_total // (1024*1024)}M free={info.psram_free // (1024*1024)}M | "
                    f"RSSI={info.wifi_rssi}dBm"
                )

    def _toggle_scan(self) -> None:
        self._btn_scan.setEnabled(False)
        if self._scanning:
            self._send(CMD_STOP_SCAN)
        else:
            self._send(CMD_START_SCAN)

    def _toggle_stream(self) -> None:
        self._btn_stream.setEnabled(False)
        if self._streaming:
            self._send(CMD_STOP_STREAM)
        else:
            interval = self._interval_spin.value()
            self._conn.log_message.emit(f"User command: START_STREAM interval={interval}ms")
            self._conn.send_command(CMD_START_STREAM, struct.pack("<H", interval))
        self._sync_init_settings()

    def _do_reconnect(self) -> None:
        self._reconnecting = True
        self._btn_reconnect.setText("Reconnecting...")
        self._btn_reconnect.setEnabled(False)
        self._conn.disconnect()

    def _send(self, cmd_id: int) -> None:
        name = CMD_NAMES.get(cmd_id, f"0x{cmd_id:02X}")
        self._conn.log_message.emit(f"User command: {name}")
        self._conn.send_command(cmd_id)

    def _send_camera_config(self) -> None:
        res_val = self._resolution_combo.currentData()
        qual_val = self._quality_combo.currentData()
        res_name = self._resolution_combo.currentText()
        qual_name = self._quality_combo.currentText()
        self._conn.log_message.emit(
            f"User command: SET_CAMERA_CONFIG resolution={res_name}, quality={qual_name}"
        )
        self._conn.send_command(
            CMD_SET_CAMERA_CONFIG, struct.pack("BB", res_val, qual_val)
        )
        self._sync_init_settings()

    def _send_rpm(self) -> None:
        rpm = self._rpm_spin.value()
        self._conn.log_message.emit(f"User command: SET_MOTOR_RPM rpm={rpm}")
        self._conn.send_command(CMD_SET_MOTOR_RPM, struct.pack("<H", rpm))
        self._sync_init_settings()

    def _send_rpm_preset(self, rpm: int) -> None:
        self._rpm_spin.setValue(rpm)
        self._send_rpm()

    _GRP_BTN = "padding: 3px 0; font-size: 10px; border-radius: 0; border: 1px solid #444;"
    _GRP_ON = _GRP_BTN + "background-color: #1565C0; color: white; border-color: #1976D2;"
    _GRP_FIRST = " border-top-left-radius: 4px; border-bottom-left-radius: 4px;"
    _GRP_LAST = " border-top-right-radius: 4px; border-bottom-right-radius: 4px;"

    def _set_scan_mode(self, mode: int) -> None:
        self._scan_mode = mode
        self._btn_scan_standard.setChecked(mode == SCAN_MODE_STANDARD)
        self._btn_scan_express.setChecked(mode == SCAN_MODE_EXPRESS)
        for i, btn in enumerate(self._scan_mode_buttons):
            is_active = btn.isChecked()
            base = self._GRP_ON if is_active else self._GRP_BTN
            extra = (self._GRP_FIRST if i == 0 else "") + (self._GRP_LAST if i == len(self._scan_mode_buttons) - 1 else "")
            btn.setStyleSheet(base + f"min-width: 56px;{extra}")
        # Send command to device
        if self._conn.connected:
            from protocol import SCAN_MODE_NAMES
            name = SCAN_MODE_NAMES.get(mode, str(mode))
            self._conn.log_message.emit(f"User command: LIDAR_SET_SCAN_MODE mode={name}")
            self._conn.send_command(CMD_LIDAR_SET_SCAN_MODE, struct.pack("B", mode))

    def reset_lidar_state(self) -> None:
        self._lidar_health_label.setText("Health: --")
        self._lidar_health_label.setStyleSheet("color: #888; font-size: 10px;")
        self._lidar_info_label.setText("Model: -- | FW: -- | HW: --")

    def update_lidar_info(self, info) -> None:
        self._lidar_info_label.setText(
            f"Model: {info.major_model} | FW: {info.firmware_str} | HW: {info.hardware}\n"
            f"Serial: {info.serial}"
        )

    def update_lidar_health(self, health) -> None:
        color_map = {"Good": "#4CAF50", "Warning": "#FF9800"}
        color = color_map.get(health.status_name, "#F44336")
        self._lidar_health_label.setText(f"Health: {health.status_name}")
        self._lidar_health_label.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: bold;")

    def _send_camera_param(self, param_id: int, value: int) -> None:
        if not self._conn.connected:
            return
        from protocol import CAMERA_PARAM_NAMES
        name = CAMERA_PARAM_NAMES.get(param_id, f"0x{param_id:02X}")
        self._conn.log_message.emit(f"User command: CAMERA_SET_PARAM {name}={value}")
        self._conn.send_command(CMD_CAMERA_SET_PARAM, struct.pack("<Bh", param_id, value))
