"""Status panel displaying connection info and DeviceStatus fields."""

from datetime import datetime

from PyQt6.QtWidgets import QGroupBox, QVBoxLayout, QGridLayout, QLabel, QFrame, QHBoxLayout
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from protocol import DeviceStatus, SCAN_IDLE, SCAN_SCANNING

_MONO = QFont("Consolas", 9)
_MONO_SM = QFont("Consolas", 8)
_CLR_DIM = "color: #444;"
_CLR_LABEL = "color: #666;"
_SECTION = "color: #556; font-size: 8px; font-weight: bold; letter-spacing: 1px;"

_DOT_GRAY = "color: #333; font-size: 10px;"
_DOT_GREEN = "color: #4CAF50; font-size: 10px;"
_DOT_RED = "color: #F44336; font-size: 10px;"

_STATUS_OK = "color: #4CAF50; font-size: 9px; font-weight: bold;"
_STATUS_NC = "color: #F44336; font-size: 9px; font-weight: bold;"
_STATUS_GRAY = "color: #333; font-size: 9px;"


def _sep() -> QFrame:
    s = QFrame()
    s.setFrameShape(QFrame.Shape.HLine)
    s.setStyleSheet("color: #2a2a2a;")
    s.setFixedHeight(1)
    return s


def _dot() -> QLabel:
    d = QLabel("\u25cf")
    d.setFont(QFont("Consolas", 9))
    d.setStyleSheet(_DOT_GRAY)
    d.setFixedWidth(12)
    d.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return d


def _kv(key_text: str, small: bool = False) -> tuple[QLabel, QLabel]:
    font = _MONO_SM if small else _MONO
    k = QLabel(key_text)
    k.setFont(font)
    k.setStyleSheet(_CLR_LABEL)
    v = QLabel("--")
    v.setFont(font)
    v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return k, v


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(_SECTION)
    return lbl


class StatusPanel(QGroupBox):
    def __init__(self):
        super().__init__("Device Status")
        self._labels: dict[str, QLabel] = {}
        self._dots: dict[str, QLabel] = {}
        self._status_labels: dict[str, QLabel] = {}  # "OK" / "N/C" text
        self._init_ui()

    def _init_ui(self) -> None:
        outer = QVBoxLayout()
        outer.setSpacing(2)
        outer.setContentsMargins(8, 12, 8, 4)

        # ═══ CONNECTION ═══════════════════════════════
        outer.addWidget(_section_label("CONNECTION"))

        conn_grid = QGridLayout()
        conn_grid.setSpacing(1)
        conn_grid.setContentsMargins(0, 0, 0, 0)
        for row, (txt, key) in enumerate([("Status", "connection"), ("Device", "device")]):
            k, v = _kv(txt)
            conn_grid.addWidget(k, row, 0)
            conn_grid.addWidget(v, row, 1)
            self._labels[key] = v
        conn_grid.setColumnStretch(1, 1)
        outer.addLayout(conn_grid)

        # Uptime / Data / Last RX — compact single row
        meta = QHBoxLayout()
        meta.setSpacing(0)
        meta.setContentsMargins(0, 0, 0, 0)
        for txt, key, w in [("Up", "uptime", 58), ("\u2502 RX", "data_total", 56), ("\u2502 Last", "last_rx", 76)]:
            k = QLabel(txt)
            k.setFont(_MONO_SM)
            k.setStyleSheet(_CLR_DIM)
            v = QLabel("--")
            v.setFont(_MONO_SM)
            v.setStyleSheet("color: #777;")
            v.setFixedWidth(w)
            v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            meta.addWidget(k)
            meta.addSpacing(3)
            meta.addWidget(v)
            meta.addSpacing(2)
            self._labels[key] = v
        meta.addStretch()
        outer.addLayout(meta)

        self._labels["connection"].setText("DISCONNECTED")
        self._labels["connection"].setStyleSheet("color: #F44336; font-weight: bold;")

        outer.addWidget(_sep())

        # ═══ SENSORS ══════════════════════════════════
        outer.addWidget(_section_label("SENSORS"))

        sensor_grid = QGridLayout()
        sensor_grid.setSpacing(1)
        sensor_grid.setContentsMargins(0, 0, 0, 0)

        # Each sensor: dot | name | status_text | value_label | value
        sensors = [
            # (dot_key, name, value_key, value_suffix)
            ("lidar",  "LiDAR",  "lidar_rpm", "RPM"),
            ("camera", "Camera", "streaming",  None),
            ("imu",    "IMU",     None,         None),
            ("sd",     "SD",     "sd_free",    "Free"),
        ]

        for row, (dot_key, name, val_key, suffix) in enumerate(sensors):
            d = _dot()
            self._dots[dot_key] = d

            name_lbl = QLabel(name)
            name_lbl.setFont(_MONO_SM)
            name_lbl.setStyleSheet(_CLR_LABEL)
            name_lbl.setFixedWidth(46)

            status_lbl = QLabel("--")
            status_lbl.setFont(_MONO_SM)
            status_lbl.setStyleSheet(_STATUS_GRAY)
            status_lbl.setFixedWidth(24)
            self._status_labels[dot_key] = status_lbl

            sensor_grid.addWidget(d, row, 0)
            sensor_grid.addWidget(name_lbl, row, 1)
            sensor_grid.addWidget(status_lbl, row, 2)

            if val_key:
                if suffix:
                    sfx = QLabel(suffix)
                    sfx.setFont(_MONO_SM)
                    sfx.setStyleSheet(_CLR_DIM)
                    sensor_grid.addWidget(sfx, row, 3)
                v = QLabel("--")
                v.setFont(_MONO_SM)
                v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                sensor_grid.addWidget(v, row, 4)
                self._labels[val_key] = v

        sensor_grid.setColumnStretch(4, 1)

        # Battery row (no dot, just label + value)
        batt_row = len(sensors)
        batt_icon = QLabel("\u26a1")
        batt_icon.setFont(_MONO_SM)
        batt_icon.setStyleSheet("color: #FF9800;")
        batt_icon.setFixedWidth(12)
        batt_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        batt_name = QLabel("Battery")
        batt_name.setFont(_MONO_SM)
        batt_name.setStyleSheet(_CLR_LABEL)
        batt_name.setFixedWidth(46)
        _, batt_v = _kv("", small=True)
        self._labels["battery"] = batt_v
        sensor_grid.addWidget(batt_icon, batt_row, 0)
        sensor_grid.addWidget(batt_name, batt_row, 1)
        sensor_grid.addWidget(batt_v, batt_row, 2, 1, 3)

        outer.addLayout(sensor_grid)

        outer.addWidget(_sep())

        # ═══ SCAN ═════════════════════════════════════
        outer.addWidget(_section_label("SCAN"))

        scan_grid = QGridLayout()
        scan_grid.setSpacing(1)
        scan_grid.setContentsMargins(0, 0, 0, 0)

        for col_off, items in enumerate([
            [("State", "scan_state"), ("Frames", "frame_count")],
            [("Duration", "duration")],
        ]):
            for row, (txt, key) in enumerate(items):
                k, v = _kv(txt, small=True)
                base = col_off * 3
                scan_grid.addWidget(k, row, base)
                scan_grid.addWidget(v, row, base + 1)
                self._labels[key] = v

        # vsep
        for row in range(2):
            vs = QLabel("\u2502")
            vs.setFont(_MONO_SM)
            vs.setStyleSheet(_CLR_DIM)
            vs.setAlignment(Qt.AlignmentFlag.AlignCenter)
            scan_grid.addWidget(vs, row, 2)

        scan_grid.setColumnStretch(1, 1)
        scan_grid.setColumnStretch(4, 1)
        outer.addLayout(scan_grid)

        outer.addStretch()
        self.setLayout(outer)

    # ── Connection info updates ──

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
            d.setStyleSheet(_DOT_GRAY)
        for s in self._status_labels.values():
            s.setText("--")
            s.setStyleSheet(_STATUS_GRAY)

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

    # ── Device status updates ──

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
        self._labels["lidar_rpm"].setText(str(status.lidar_rpm))
        self._labels["sd_free"].setText(f"{status.sd_free_mb} MB")
        self._labels["streaming"].setText(status.streaming_str)
        if status.camera_streaming:
            self._labels["streaming"].setStyleSheet("color: #4CAF50; font-weight: bold;")
        else:
            self._labels["streaming"].setStyleSheet("")

        # Sensor health: dot + status text
        for key, ok in [
            ("lidar", status.lidar_ok),
            ("camera", status.camera_ok),
            ("imu", status.imu_ok),
            ("sd", status.sd_ok),
        ]:
            self._dots[key].setStyleSheet(_DOT_GREEN if ok else _DOT_RED)
            self._status_labels[key].setText("OK" if ok else "N/C")
            self._status_labels[key].setStyleSheet(_STATUS_OK if ok else _STATUS_NC)

    def reset(self) -> None:
        for key, label in self._labels.items():
            if key not in ("connection", "device"):
                label.setText("--")
                label.setStyleSheet("")
        for d in self._dots.values():
            d.setStyleSheet(_DOT_GRAY)
        for s in self._status_labels.values():
            s.setText("--")
            s.setStyleSheet(_STATUS_GRAY)
