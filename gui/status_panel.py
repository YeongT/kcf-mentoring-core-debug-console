"""Status panel displaying connection info and DeviceStatus fields."""

from datetime import datetime

from PyQt6.QtWidgets import (
    QGroupBox, QVBoxLayout, QGridLayout, QLabel, QFrame, QHBoxLayout, QPushButton, QWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from protocol import DeviceStatus, SCAN_IDLE, SCAN_SCANNING

_MONO = QFont("Consolas", 9)
_MONO_SM = QFont("Consolas", 8)
_CLR_DIM = "color: #444;"
_CLR_LABEL = "color: #78909C;"
_CLR_VALUE = "color: #CFD8DC;"
_SECTION = "color: #546E7A; font-size: 8px; font-weight: bold; letter-spacing: 2px;"


def _sep() -> QFrame:
    s = QFrame()
    s.setFrameShape(QFrame.Shape.HLine)
    s.setStyleSheet("color: #1e1e1e;")
    s.setFixedHeight(1)
    return s


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(_SECTION)
    lbl.setContentsMargins(0, 4, 0, 2)
    return lbl


def _label(text: str = "--", style: str = _CLR_VALUE) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(_MONO_SM)
    lbl.setStyleSheet(style)
    return lbl


def _val_label(text: str = "--", align_right: bool = True) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(_MONO_SM)
    lbl.setStyleSheet(_CLR_VALUE)
    if align_right:
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return lbl


class StatusPanel(QGroupBox):
    connect_device_requested = pyqtSignal(str, str)  # device_name, device_ip

    def __init__(self):
        super().__init__("Device Status")
        self._labels: dict[str, QLabel] = {}
        self._dots: dict[str, QLabel] = {}
        self._status_labels: dict[str, QLabel] = {}
        self._device_widgets: dict[str, QWidget] = {}
        self._connected_device: str = ""
        self._init_ui()

    def _init_ui(self) -> None:
        outer = QVBoxLayout()
        outer.setSpacing(4)
        outer.setContentsMargins(10, 14, 10, 6)

        # ═══ CONNECTION ═══════════════════════════════
        outer.addWidget(_section_label("CONNECTION"))

        conn_grid = QGridLayout()
        conn_grid.setSpacing(2)
        conn_grid.setContentsMargins(4, 0, 4, 0)

        conn_grid.addWidget(_label("Status", _CLR_LABEL), 0, 0)
        v = _val_label("DISCONNECTED")
        v.setStyleSheet("color: #F44336; font-weight: bold;")
        conn_grid.addWidget(v, 0, 1)
        self._labels["connection"] = v

        conn_grid.addWidget(_label("Device", _CLR_LABEL), 1, 0)
        v = _val_label("--")
        conn_grid.addWidget(v, 1, 1)
        self._labels["device"] = v

        conn_grid.setColumnStretch(1, 1)
        outer.addLayout(conn_grid)

        # Uptime / Data / Last RX — compact row
        meta = QHBoxLayout()
        meta.setSpacing(0)
        meta.setContentsMargins(4, 1, 4, 0)
        for txt, key, w in [("Up", "uptime", 58), ("\u2502 RX", "data_total", 58), ("\u2502 Last", "last_rx", 90)]:
            k = _label(txt, _CLR_DIM)
            v = QLabel("--")
            v.setFont(_MONO_SM)
            v.setStyleSheet("color: #607D8B;")
            v.setFixedWidth(w)
            v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            meta.addWidget(k)
            meta.addSpacing(4)
            meta.addWidget(v)
            meta.addSpacing(4)
            self._labels[key] = v
        meta.addStretch()
        outer.addLayout(meta)

        outer.addSpacing(2)
        outer.addWidget(_sep())

        # ═══ SENSORS — 2x4 grid ══════════════════════
        outer.addWidget(_section_label("SENSORS"))

        sensor_grid = QGridLayout()
        sensor_grid.setSpacing(2)
        sensor_grid.setContentsMargins(4, 0, 4, 0)
        # Columns: [dot][name][status] | [dot][name][status]
        #          0    1     2    3      4    5     6

        sensors_left = [
            ("lidar", "LiDAR", "lidar_val"),
            ("imu", "IMU", None),
        ]
        sensors_right = [
            ("camera", "Camera", "camera_val"),
            ("sd", "SD Card", "sd_val"),
        ]

        for row, (key, name, val_key) in enumerate(sensors_left):
            dot = QLabel("\u25cf")
            dot.setFont(QFont("Consolas", 10))
            dot.setStyleSheet("color: #333;")
            dot.setFixedWidth(14)
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._dots[key] = dot

            name_lbl = _label(name, _CLR_LABEL)
            name_lbl.setFixedWidth(50)

            status_lbl = _label("--", "color: #333;")
            status_lbl.setFixedWidth(28)
            self._status_labels[key] = status_lbl

            sensor_grid.addWidget(dot, row, 0)
            sensor_grid.addWidget(name_lbl, row, 1)
            sensor_grid.addWidget(status_lbl, row, 2)

            if val_key:
                v = _val_label("--")
                sensor_grid.addWidget(v, row, 3)
                self._labels[val_key] = v

        # Vertical separator
        for row in range(2):
            vs = QLabel("\u2502")
            vs.setFont(_MONO_SM)
            vs.setStyleSheet(_CLR_DIM)
            vs.setAlignment(Qt.AlignmentFlag.AlignCenter)
            vs.setFixedWidth(10)
            sensor_grid.addWidget(vs, row, 4)

        for row, (key, name, val_key) in enumerate(sensors_right):
            dot = QLabel("\u25cf")
            dot.setFont(QFont("Consolas", 10))
            dot.setStyleSheet("color: #333;")
            dot.setFixedWidth(14)
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._dots[key] = dot

            name_lbl = _label(name, _CLR_LABEL)
            name_lbl.setFixedWidth(56)

            status_lbl = _label("--", "color: #333;")
            status_lbl.setFixedWidth(28)
            self._status_labels[key] = status_lbl

            sensor_grid.addWidget(dot, row, 5)
            sensor_grid.addWidget(name_lbl, row, 6)
            sensor_grid.addWidget(status_lbl, row, 7)

            if val_key:
                v = _val_label("--")
                sensor_grid.addWidget(v, row, 8)
                self._labels[val_key] = v

        sensor_grid.setColumnStretch(3, 1)
        sensor_grid.setColumnStretch(8, 1)
        outer.addLayout(sensor_grid)

        # Battery row
        batt_row = QHBoxLayout()
        batt_row.setContentsMargins(4, 1, 4, 0)
        batt_icon = QLabel("\u26a1")
        batt_icon.setFont(_MONO_SM)
        batt_icon.setStyleSheet("color: #FF9800;")
        batt_icon.setFixedWidth(14)
        batt_name = _label("Battery", _CLR_LABEL)
        batt_val = _val_label("--")
        self._labels["battery"] = batt_val
        batt_row.addWidget(batt_icon)
        batt_row.addWidget(batt_name)
        batt_row.addStretch()
        batt_row.addWidget(batt_val)
        outer.addLayout(batt_row)

        outer.addSpacing(2)
        outer.addWidget(_sep())

        # ═══ SCAN ═════════════════════════════════════
        outer.addWidget(_section_label("SCAN"))

        scan_grid = QGridLayout()
        scan_grid.setSpacing(2)
        scan_grid.setContentsMargins(4, 0, 4, 0)

        scan_items = [
            ("State", "scan_state", 0, 0),
            ("Duration", "duration", 0, 3),
            ("Frames", "frame_count", 1, 0),
        ]
        for txt, key, row, col in scan_items:
            k = _label(txt, _CLR_LABEL)
            v = _val_label("--")
            scan_grid.addWidget(k, row, col)
            scan_grid.addWidget(v, row, col + 1)
            self._labels[key] = v

        # Vertical separator between State/Duration
        for row in range(2):
            vs = QLabel("\u2502")
            vs.setFont(_MONO_SM)
            vs.setStyleSheet(_CLR_DIM)
            vs.setAlignment(Qt.AlignmentFlag.AlignCenter)
            vs.setFixedWidth(10)
            scan_grid.addWidget(vs, row, 2)

        scan_grid.setColumnStretch(1, 1)
        scan_grid.setColumnStretch(4, 1)
        outer.addLayout(scan_grid)

        outer.addSpacing(2)
        outer.addWidget(_sep())

        # ═══ DISCOVERY ══════════════════════════════════
        outer.addWidget(_section_label("DISCOVERY"))
        self._discovery_container = QVBoxLayout()
        self._discovery_container.setSpacing(2)
        self._discovery_container.setContentsMargins(4, 0, 4, 0)
        self._discovery_placeholder = _label("Scanning...", "color: #607D8B;")
        self._discovery_container.addWidget(self._discovery_placeholder)
        outer.addLayout(self._discovery_container)

        outer.addStretch()
        self.setLayout(outer)

    # ── Connection ──

    def set_connected(self, device_name: str) -> None:
        self._labels["connection"].setText("CONNECTED")
        self._labels["connection"].setStyleSheet("color: #4CAF50; font-weight: bold;")
        self._labels["device"].setText(device_name)

    def set_disconnected(self) -> None:
        self._labels["connection"].setText("DISCONNECTED")
        self._labels["connection"].setStyleSheet("color: #F44336; font-weight: bold;")
        self._labels["device"].setText("--")
        self._labels["uptime"].setText("--")
        self._labels["data_total"].setText("--")
        for d in self._dots.values():
            d.setStyleSheet("color: #333;")
        for s in self._status_labels.values():
            s.setText("--")
            s.setStyleSheet("color: #333;")

    def update_uptime(self, seconds: int) -> None:
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        self._labels["uptime"].setText(f"{h:02d}:{m:02d}:{s:02d}")

    def update_last_rx(self) -> None:
        self._labels["last_rx"].setText(datetime.now().strftime("%H:%M:%S.%f")[:-3])

    def update_data_total(self, total_bytes: int) -> None:
        if total_bytes < 1024:
            self._labels["data_total"].setText(f"{total_bytes} B")
        elif total_bytes < 1024 * 1024:
            self._labels["data_total"].setText(f"{total_bytes / 1024:.1f} KB")
        else:
            self._labels["data_total"].setText(f"{total_bytes / (1024 * 1024):.1f} MB")

    # ── Status ──

    def update_status(self, status: DeviceStatus) -> None:
        # Scan
        self._labels["scan_state"].setText(status.scan_state_name)
        if status.scan_state == SCAN_IDLE:
            self._labels["scan_state"].setStyleSheet("color: #4CAF50; font-weight: bold;")
        elif status.scan_state == SCAN_SCANNING:
            self._labels["scan_state"].setStyleSheet("color: #F44336; font-weight: bold;")
        else:
            self._labels["scan_state"].setStyleSheet("color: #FF9800; font-weight: bold;")

        self._labels["frame_count"].setText(str(status.frame_count))
        self._labels["duration"].setText(status.duration_str)
        self._labels["battery"].setText(status.battery_str)

        # Sensor values
        self._labels["lidar_val"].setText(f"{status.lidar_rpm} RPM")
        self._labels["sd_val"].setText(f"{status.sd_free_mb} MB")

        streaming_text = status.streaming_str
        self._labels["camera_val"].setText(streaming_text)
        if status.camera_streaming:
            self._labels["camera_val"].setStyleSheet("color: #4CAF50; font-weight: bold;")
        else:
            self._labels["camera_val"].setStyleSheet(_CLR_VALUE)

        # Sensor health dots + status text
        for key, ok in [
            ("lidar", status.lidar_ok),
            ("camera", status.camera_ok),
            ("imu", status.imu_ok),
            ("sd", status.sd_ok),
        ]:
            self._dots[key].setStyleSheet("color: #4CAF50;" if ok else "color: #F44336;")
            self._status_labels[key].setText("OK" if ok else "N/C")
            self._status_labels[key].setStyleSheet(
                "color: #4CAF50; font-weight: bold;" if ok else "color: #F44336; font-weight: bold;"
            )

    def update_discovered_devices(self, devices, connected_device: str = "") -> None:
        """Update the discovery section with found devices as clickable rows."""
        self._connected_device = connected_device
        current_names = {d.name for d in devices}

        # Remove stale widgets
        for name in list(self._device_widgets.keys()):
            if name not in current_names:
                widget = self._device_widgets.pop(name)
                self._discovery_container.removeWidget(widget)
                widget.deleteLater()

        # Add/update devices
        for device in devices:
            if device.name not in self._device_widgets:
                row = self._create_device_row(device)
                self._device_widgets[device.name] = row
                self._discovery_container.addWidget(row)
            else:
                self._update_device_row(device.name, device, connected_device)

        # Show/hide placeholder
        has_devices = len(self._device_widgets) > 0
        self._discovery_placeholder.setVisible(not has_devices)

    def _create_device_row(self, device) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(4)

        dot = QLabel("\u25cf")
        dot.setFont(QFont("Consolas", 8))
        dot.setStyleSheet("color: #4CAF50;")
        dot.setFixedWidth(12)

        name_lbl = _label(device.name, _CLR_VALUE)
        ip_lbl = _label(device.ip_address, "color: #607D8B;")

        btn = QPushButton("Connect")
        btn.setFixedSize(62, 20)
        btn.setFont(QFont("Consolas", 8))
        btn.setStyleSheet(
            "background-color: #1565C0; color: white; border-radius: 2px; padding: 1px 4px;"
        )
        # Capture values for the lambda
        dev_name = device.name
        dev_ip = device.ip_address
        btn.clicked.connect(lambda: self.connect_device_requested.emit(dev_name, dev_ip))

        is_connected = device.name == self._connected_device
        if is_connected:
            btn.setText("Connected")
            btn.setEnabled(False)
            btn.setStyleSheet(
                "background-color: #2E7D32; color: white; border-radius: 2px; padding: 1px 4px;"
            )

        layout.addWidget(dot)
        layout.addWidget(name_lbl)
        layout.addWidget(ip_lbl)
        layout.addStretch()
        layout.addWidget(btn)

        # Store refs for updating
        row._dot = dot
        row._name_lbl = name_lbl
        row._ip_lbl = ip_lbl
        row._btn = btn
        row._dev_name = device.name
        row._dev_ip = device.ip_address

        return row

    def _update_device_row(self, name: str, device, connected_device: str) -> None:
        row = self._device_widgets.get(name)
        if not row:
            return
        row._ip_lbl.setText(device.ip_address)
        row._dev_ip = device.ip_address
        is_connected = name == connected_device
        if is_connected:
            row._btn.setText("Connected")
            row._btn.setEnabled(False)
            row._btn.setStyleSheet(
                "background-color: #2E7D32; color: white; border-radius: 2px; padding: 1px 4px;"
            )
        else:
            row._btn.setText("Connect")
            row._btn.setEnabled(True)
            row._btn.setStyleSheet(
                "background-color: #1565C0; color: white; border-radius: 2px; padding: 1px 4px;"
            )

    def reset(self) -> None:
        for key, label in self._labels.items():
            if key not in ("connection", "device"):
                label.setText("--")
                label.setStyleSheet(_CLR_VALUE)
        for d in self._dots.values():
            d.setStyleSheet("color: #333;")
        for s in self._status_labels.values():
            s.setText("--")
            s.setStyleSheet("color: #333;")
