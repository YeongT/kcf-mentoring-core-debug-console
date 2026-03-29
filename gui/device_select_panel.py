"""Device selection screen shown on startup before connecting to a device."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont


_MONO = QFont("Consolas", 10)
_MONO_SM = QFont("Consolas", 9)


class DeviceSelectPanel(QWidget):
    """Full-screen device selection panel with discovered device list."""

    connect_requested = pyqtSignal(str, str)  # device_name, device_ip

    def __init__(self):
        super().__init__()
        self._device_widgets: dict[str, QWidget] = {}
        self._init_ui()

    def _init_ui(self) -> None:
        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Center content with max width
        center = QWidget()
        center.setMaximumWidth(500)
        layout = QVBoxLayout()
        layout.setSpacing(16)
        layout.setContentsMargins(40, 40, 40, 40)

        # Title
        title = QLabel("Device Selection")
        title.setFont(QFont("Consolas", 18, QFont.Weight.Bold))
        title.setStyleSheet("color: #E0E0E0;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Subtitle
        subtitle = QLabel("Discovered devices on the network")
        subtitle.setFont(_MONO_SM)
        subtitle.setStyleSheet("color: #607D8B;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        layout.addSpacing(8)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #333;")
        sep.setFixedHeight(1)
        layout.addWidget(sep)

        layout.addSpacing(8)

        # Device list container
        self._list_layout = QVBoxLayout()
        self._list_layout.setSpacing(6)
        self._list_layout.setContentsMargins(0, 0, 0, 0)

        self._placeholder = QLabel("Scanning for devices...")
        self._placeholder.setFont(_MONO)
        self._placeholder.setStyleSheet("color: #546E7A;")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._list_layout.addWidget(self._placeholder)

        layout.addLayout(self._list_layout)
        layout.addStretch()

        center.setLayout(layout)

        # Center the content widget
        h_layout = QHBoxLayout()
        h_layout.addStretch()
        h_layout.addWidget(center)
        h_layout.addStretch()
        outer.addStretch()
        outer.addLayout(h_layout)
        outer.addStretch()

        self.setLayout(outer)

    def update_devices(self, devices, connected_device: str = "") -> None:
        """Update the device list with current discoveries."""
        current_names = {d.name for d in devices}

        # Remove stale widgets
        for name in list(self._device_widgets.keys()):
            if name not in current_names:
                widget = self._device_widgets.pop(name)
                self._list_layout.removeWidget(widget)
                widget.deleteLater()

        # Add/update devices
        for device in devices:
            if device.name not in self._device_widgets:
                row = self._create_device_card(device)
                self._device_widgets[device.name] = row
                self._list_layout.addWidget(row)
            else:
                self._update_device_card(device.name, device, connected_device)

        has_devices = len(self._device_widgets) > 0
        self._placeholder.setVisible(not has_devices)

    def _create_device_card(self, device) -> QWidget:
        card = QWidget()
        card.setStyleSheet(
            "QWidget#device_card {"
            "  background-color: #1a1a1a;"
            "  border: 1px solid #333;"
            "  border-radius: 6px;"
            "}"
        )
        card.setObjectName("device_card")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        # Green dot
        dot = QLabel("\u25cf")
        dot.setFont(QFont("Consolas", 12))
        dot.setStyleSheet("color: #4CAF50;")
        dot.setFixedWidth(16)
        layout.addWidget(dot)

        # Info column
        info = QVBoxLayout()
        info.setSpacing(2)
        name_lbl = QLabel(device.name)
        name_lbl.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
        name_lbl.setStyleSheet("color: #E0E0E0;")
        ip_lbl = QLabel(device.ip_address)
        ip_lbl.setFont(_MONO_SM)
        ip_lbl.setStyleSheet("color: #607D8B;")
        info.addWidget(name_lbl)
        info.addWidget(ip_lbl)
        layout.addLayout(info, 1)

        # Connect button
        btn = QPushButton("Connect")
        btn.setFixedSize(90, 32)
        btn.setFont(QFont("Consolas", 10))
        btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #1565C0; color: white;"
            "  border-radius: 4px; border: none;"
            "}"
            "QPushButton:hover { background-color: #1976D2; }"
            "QPushButton:pressed { background-color: #0D47A1; }"
        )
        dev_name = device.name
        dev_ip = device.ip_address
        btn.clicked.connect(lambda: self.connect_requested.emit(dev_name, dev_ip))
        layout.addWidget(btn)

        # Store refs
        card._dot = dot
        card._name_lbl = name_lbl
        card._ip_lbl = ip_lbl
        card._btn = btn
        card._dev_name = device.name
        card._dev_ip = device.ip_address

        return card

    def _update_device_card(self, name: str, device, connected_device: str) -> None:
        card = self._device_widgets.get(name)
        if not card:
            return
        card._ip_lbl.setText(device.ip_address)
        card._dev_ip = device.ip_address
