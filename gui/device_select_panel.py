"""Device selection screen shown on startup before connecting to a device."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont


_MONO = QFont("Consolas", 10)
_MONO_SM = QFont("Consolas", 9)

_BTN_CONNECT = (
    "QPushButton {"
    "  background-color: #1565C0; color: white;"
    "  border-radius: 4px; border: none;"
    "}"
    "QPushButton:hover { background-color: #1976D2; }"
    "QPushButton:pressed { background-color: #0D47A1; }"
)
_BTN_CONNECTED = (
    "QPushButton {"
    "  background-color: #2E7D32; color: white;"
    "  border-radius: 4px; border: none;"
    "}"
)
_CARD_NORMAL = (
    "QWidget#device_card {"
    "  background-color: #1a1a1a;"
    "  border: 1px solid #333;"
    "  border-radius: 8px;"
    "}"
    "QWidget#device_card * { background: transparent; }"
)
_CARD_CONNECTED = (
    "QWidget#device_card {"
    "  background-color: #1a2e1a;"
    "  border: 1px solid #2E7D32;"
    "  border-radius: 8px;"
    "}"
    "QWidget#device_card * { background: transparent; }"
)


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
        center.setMaximumWidth(520)
        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(40, 0, 40, 40)

        # Title
        title = QLabel("Core Device Console")
        title.setFont(QFont("Consolas", 16, QFont.Weight.Bold))
        title.setStyleSheet("color: #E0E0E0;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Subtitle with device count
        self._subtitle = QLabel("Scanning for devices...")
        self._subtitle.setFont(_MONO_SM)
        self._subtitle.setStyleSheet("color: #546E7A;")
        self._subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._subtitle)

        layout.addSpacing(4)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #2a2a2a;")
        sep.setFixedHeight(1)
        layout.addWidget(sep)

        layout.addSpacing(4)

        # Device list container
        self._list_layout = QVBoxLayout()
        self._list_layout.setSpacing(8)
        self._list_layout.setContentsMargins(0, 0, 0, 0)

        self._placeholder = QLabel("\u25cc  Waiting for device broadcasts...")
        self._placeholder.setFont(_MONO)
        self._placeholder.setStyleSheet("color: #37474F;")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setMinimumHeight(60)
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
                card = self._create_device_card(device, connected_device)
                self._device_widgets[device.name] = card
                self._list_layout.addWidget(card)
            else:
                self._update_device_card(device.name, device, connected_device)

        count = len(self._device_widgets)
        has_devices = count > 0
        self._placeholder.setVisible(not has_devices)

        if has_devices:
            self._subtitle.setText(f"{count} device{'s' if count > 1 else ''} found on network")
            self._subtitle.setStyleSheet("color: #78909C;")
        else:
            self._subtitle.setText("Scanning for devices...")
            self._subtitle.setStyleSheet("color: #546E7A;")

    def _create_device_card(self, device, connected_device: str = "") -> QWidget:
        is_connected = device.name == connected_device

        card = QWidget()
        card.setObjectName("device_card")
        card.setStyleSheet(_CARD_CONNECTED if is_connected else _CARD_NORMAL)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        # Status dot
        dot = QLabel("\u25cf")
        dot.setFont(QFont("Consolas", 14))
        dot.setStyleSheet("color: #4CAF50;" if is_connected else "color: #78909C;")
        dot.setFixedWidth(18)
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
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

        # Button
        btn = QPushButton("Connected" if is_connected else "Connect")
        btn.setFixedSize(100, 34)
        btn.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        btn.setStyleSheet(_BTN_CONNECTED if is_connected else _BTN_CONNECT)
        btn.setEnabled(not is_connected)

        dev_name = device.name
        dev_ip = device.ip_address
        btn.clicked.connect(lambda: self.connect_requested.emit(dev_name, dev_ip))
        layout.addWidget(btn)

        # Store refs for updates
        card._dot = dot
        card._name_lbl = name_lbl
        card._ip_lbl = ip_lbl
        card._btn = btn

        return card

    def _update_device_card(self, name: str, device, connected_device: str) -> None:
        card = self._device_widgets.get(name)
        if not card:
            return

        is_connected = name == connected_device
        card._ip_lbl.setText(device.ip_address)

        # Update connected state
        card.setStyleSheet(_CARD_CONNECTED if is_connected else _CARD_NORMAL)
        card._dot.setStyleSheet("color: #4CAF50;" if is_connected else "color: #78909C;")

        if is_connected:
            card._btn.setText("Connected")
            card._btn.setEnabled(False)
            card._btn.setStyleSheet(_BTN_CONNECTED)
        else:
            card._btn.setText("Connect")
            card._btn.setEnabled(True)
            card._btn.setStyleSheet(_BTN_CONNECT)
