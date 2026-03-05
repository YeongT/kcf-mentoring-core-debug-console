"""Status panel displaying connection info and DeviceStatus fields."""

from PyQt6.QtWidgets import QGroupBox, QVBoxLayout, QGridLayout, QLabel, QFrame
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from protocol import DeviceStatus, SCAN_IDLE, SCAN_SCANNING


class StatusPanel(QGroupBox):
    def __init__(self):
        super().__init__("Device Status")
        self._labels: dict[str, QLabel] = {}
        self._init_ui()

    def _init_ui(self) -> None:
        outer = QVBoxLayout()
        outer.setSpacing(4)
        outer.setContentsMargins(10, 14, 10, 6)

        mono = QFont("Consolas", 9)

        # --- Connection section ---
        conn_grid = QGridLayout()
        conn_grid.setSpacing(4)
        conn_fields = [
            ("Status", "connection"),
            ("Device", "device"),
            ("Uptime", "uptime"),
            ("Data", "data_total"),
        ]
        for row, (label_text, key) in enumerate(conn_fields):
            name_label = QLabel(label_text)
            name_label.setFont(mono)
            name_label.setStyleSheet("color: #666;")
            name_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

            value_label = QLabel("--")
            value_label.setFont(mono)
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            conn_grid.addWidget(name_label, row, 0)
            conn_grid.addWidget(value_label, row, 1)
            self._labels[key] = value_label

        # Set initial connection state
        self._labels["connection"].setText("DISCONNECTED")
        self._labels["connection"].setStyleSheet("color: #F44336; font-weight: bold;")

        conn_grid.setColumnStretch(1, 1)
        outer.addLayout(conn_grid)

        # --- Separator ---
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #333;")
        outer.addWidget(sep)

        # --- Device status section (2-column grid) ---
        status_grid = QGridLayout()
        status_grid.setSpacing(4)
        status_fields = [
            ("Scan", "scan_state"),
            ("Stream", "streaming"),
            ("Battery", "battery"),
            ("RPM", "lidar_rpm"),
            ("SD Free", "sd_free"),
            ("Frames", "frame_count"),
            ("Duration", "duration"),
        ]
        for i, (label_text, key) in enumerate(status_fields):
            row = i // 2
            col = (i % 2) * 3  # 0 or 3

            name_label = QLabel(label_text)
            name_label.setFont(mono)
            name_label.setStyleSheet("color: #666;")
            name_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

            value_label = QLabel("--")
            value_label.setFont(mono)
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            status_grid.addWidget(name_label, row, col)
            status_grid.addWidget(value_label, row, col + 1)
            self._labels[key] = value_label

        # Add vertical separator between the two columns
        for row in range(4):
            vsep = QLabel("|")
            vsep.setFont(mono)
            vsep.setStyleSheet("color: #333;")
            vsep.setAlignment(Qt.AlignmentFlag.AlignCenter)
            status_grid.addWidget(vsep, row, 2)

        status_grid.setColumnStretch(1, 1)
        status_grid.setColumnStretch(4, 1)
        outer.addLayout(status_grid)

        self.setLayout(outer)

    # --- Connection info updates ---

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

    def update_uptime(self, seconds: int) -> None:
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        self._labels["uptime"].setText(f"{h:02d}:{m:02d}:{s:02d}")

    def update_data_total(self, total_bytes: int) -> None:
        if total_bytes < 1024:
            self._labels["data_total"].setText(f"{total_bytes} B")
        elif total_bytes < 1024 * 1024:
            self._labels["data_total"].setText(f"{total_bytes / 1024:.1f} KB")
        else:
            self._labels["data_total"].setText(f"{total_bytes / (1024 * 1024):.1f} MB")

    # --- Device status updates ---

    def update_status(self, status: DeviceStatus) -> None:
        self._labels["scan_state"].setText(status.scan_state_name)
        if status.scan_state == SCAN_IDLE:
            self._labels["scan_state"].setStyleSheet("color: #4CAF50; font-weight: bold;")
        elif status.scan_state == SCAN_SCANNING:
            self._labels["scan_state"].setStyleSheet("color: #F44336; font-weight: bold;")
        else:
            self._labels["scan_state"].setStyleSheet("color: #FF9800; font-weight: bold;")

        self._labels["lidar_rpm"].setText(str(status.lidar_rpm))
        self._labels["sd_free"].setText(f"{status.sd_free_mb} MB")
        self._labels["frame_count"].setText(str(status.frame_count))
        self._labels["duration"].setText(status.duration_str)
        self._labels["battery"].setText(status.battery_str)
        self._labels["streaming"].setText(status.streaming_str)

        if status.camera_streaming:
            self._labels["streaming"].setStyleSheet("color: #4CAF50; font-weight: bold;")
        else:
            self._labels["streaming"].setStyleSheet("")

    def reset(self) -> None:
        for key, label in self._labels.items():
            if key not in ("connection",):
                label.setText("--")
                label.setStyleSheet("")
