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
    SCAN_IDLE,
    SCAN_SCANNING,
    parse_status,
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
        self._init_ui()
        self._set_enabled(False)
        connection.device_connected.connect(lambda _: self._set_enabled(True))
        connection.device_disconnected.connect(self._on_disconnected)
        connection.status_received.connect(self._on_status)

    def _init_ui(self) -> None:
        layout = QVBoxLayout()
        layout.setSpacing(6)
        layout.setContentsMargins(10, 14, 10, 6)

        # Primary actions: Stream + Scan (full-width, prominent)
        action_grid = QGridLayout()
        action_grid.setSpacing(4)

        self._btn_stream = QPushButton("Start Stream")
        self._btn_stream.setStyleSheet(_STYLE_STREAM_OFF)
        self._btn_stream.clicked.connect(self._toggle_stream)
        action_grid.addWidget(self._btn_stream, 0, 0)

        self._btn_scan = QPushButton("Start Scan")
        self._btn_scan.setStyleSheet(_STYLE_SCAN_OFF)
        self._btn_scan.clicked.connect(self._toggle_scan)
        action_grid.addWidget(self._btn_scan, 0, 1)

        btn_status = QPushButton("Get Status")
        btn_status.clicked.connect(lambda: self._send(CMD_GET_STATUS))
        action_grid.addWidget(btn_status, 1, 0)

        btn_capture = QPushButton("Capture")
        btn_capture.clicked.connect(lambda: self._send(CMD_CAPTURE_FRAME))
        action_grid.addWidget(btn_capture, 1, 1)

        self._btn_reconnect = QPushButton("Reconnect")
        self._btn_reconnect.setStyleSheet("background-color: #616161; color: white;")
        self._btn_reconnect.clicked.connect(self._do_reconnect)
        action_grid.addWidget(self._btn_reconnect, 2, 0)

        btn_reset = QPushButton("Reset")
        btn_reset.setStyleSheet("background-color: #FF9800; color: white;")
        btn_reset.clicked.connect(self.reset_requested.emit)
        action_grid.addWidget(btn_reset, 2, 1)

        layout.addLayout(action_grid, 4)

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

        self._params_vsep = QLabel()
        self._params_vsep.setFixedWidth(1)
        self._params_vsep.setStyleSheet("background-color: #333;")

        self._params_hsep = QLabel()
        self._params_hsep.setFixedHeight(1)
        self._params_hsep.setStyleSheet("background-color: #333;")

        self._sidebar_mode = False
        self._apply_params_layout()

        self.setLayout(layout)

    def _on_disconnected(self) -> None:
        self._scanning = False
        self._streaming = False
        self._set_enabled(False)
        self._sync_buttons()
        self._btn_reconnect.setText("Reconnect")
        self._btn_reconnect.setStyleSheet("background-color: #616161; color: white;")

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
        if not enabled:
            self._btn_stream.setStyleSheet(_STYLE_DISABLED)
            self._btn_scan.setStyleSheet(_STYLE_DISABLED)
            self._btn_reconnect.setStyleSheet(_STYLE_DISABLED)

    def set_sidebar_mode(self, sidebar: bool) -> None:
        if sidebar == self._sidebar_mode:
            return
        self._sidebar_mode = sidebar
        self._apply_params_layout()

    def _apply_params_layout(self) -> None:
        old = self._params_container.layout()
        if old is not None:
            # Detach all widgets from old layout
            while old.count():
                old.takeAt(0)
            QWidget().setLayout(old)  # discard old layout

        if self._sidebar_mode:
            vbox = QVBoxLayout()
            vbox.setContentsMargins(0, 0, 0, 0)
            vbox.setSpacing(4)
            row1 = QHBoxLayout()
            row1.setSpacing(8)
            row1.addWidget(self._lbl_interval)
            row1.addWidget(self._interval_spin)
            row1.addStretch()
            vbox.addLayout(row1)
            self._params_hsep.show()
            self._params_vsep.hide()
            vbox.addWidget(self._params_hsep)
            row2 = QHBoxLayout()
            row2.setSpacing(8)
            row2.addWidget(self._lbl_rpm)
            row2.addWidget(self._rpm_spin)
            row2.addWidget(self._btn_rpm)
            row2.addStretch()
            vbox.addLayout(row2)
            self._params_container.setLayout(vbox)
        else:
            hbox = QHBoxLayout()
            hbox.setContentsMargins(0, 0, 0, 0)
            hbox.setSpacing(8)
            hbox.addWidget(self._lbl_interval)
            hbox.addWidget(self._interval_spin)
            self._params_vsep.show()
            self._params_hsep.hide()
            hbox.addWidget(self._params_vsep)
            hbox.addWidget(self._lbl_rpm)
            hbox.addWidget(self._rpm_spin)
            hbox.addWidget(self._btn_rpm)
            self._params_container.setLayout(hbox)

    def _on_interval_changed(self, value: int) -> None:
        if self._streaming:
            self._conn.send_command(CMD_START_STREAM, struct.pack("<H", value))

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
            self._conn.send_command(CMD_START_STREAM, struct.pack("<H", interval))

    def _do_reconnect(self) -> None:
        self._btn_reconnect.setText("Reconnecting...")
        self._btn_reconnect.setEnabled(False)
        self._btn_reconnect.setStyleSheet(_STYLE_DISABLED)
        self._conn.disconnect()

    def _send(self, cmd_id: int) -> None:
        self._conn.send_command(cmd_id)

    def _send_rpm(self) -> None:
        rpm = self._rpm_spin.value()
        self._conn.send_command(CMD_SET_MOTOR_RPM, struct.pack("<H", rpm))
