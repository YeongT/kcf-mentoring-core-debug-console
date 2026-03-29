"""Main window layout assembling all panels."""

import os
import socket
import tempfile
import time

from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QPushButton,
    QSpinBox,
    QDialog,
    QMessageBox,
    QButtonGroup,
    QScrollArea,
    QStackedWidget,
)
from PyQt6.QtCore import Qt, QTimer, QPoint
from PyQt6.QtGui import QFont, QShortcut, QKeySequence, QPixmap, QPainter, QColor, QPolygon

from protocol import (
    parse_status,
    parse_camera_frame,
    parse_lidar_frame,
    parse_response,
    DeviceStatus,
    CMD_GET_STATUS,
    CMD_SET_CAMERA_CONFIG,
    CMD_CAMERA_SET_PARAM,
)
from ws_server import DeviceConnection, WebSocketServer
from udp_discovery import UdpDiscoveryListener
import settings

from gui.camera_panel import CameraPanel
from gui.lidar_panel import LidarPanel
from gui.status_panel import StatusPanel
from gui.command_panel import CommandPanel
from gui.log_panel import LogPanel
from gui.device_select_panel import DeviceSelectPanel


class MainWindow(QMainWindow):
    def __init__(self, connection: DeviceConnection, server: WebSocketServer, discovery: UdpDiscoveryListener | None = None):
        super().__init__()
        self._conn = connection
        self._server = server
        self._discovery = discovery
        self.setWindowTitle("Core Device Test Client")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(1200, 920)

        self._settings = settings.load()
        self._status_poll_interval = self._settings.get("status_poll_interval", 5000)
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._poll_status)

        # Uptime / data tracking
        self._connected_at: float = 0
        self._total_bytes: int = 0
        self._uptime_timer = QTimer(self)
        self._uptime_timer.setInterval(1000)
        self._uptime_timer.timeout.connect(self._tick_uptime)

        # For frameless window dragging / resizing
        self._drag_pos: QPoint | None = None
        self._resize_edge: str = ""  # "", "left", "right", "top", "bottom", combos
        self._EDGE_MARGIN = 6

        self._create_arrow_icons()
        self._init_ui()
        self._connect_signals()

    def _create_arrow_icons(self) -> None:
        icon_dir = os.path.join(tempfile.gettempdir(), "kcf_debug_icons")
        os.makedirs(icon_dir, exist_ok=True)
        color = QColor("#B0BEC5")
        arrows = {
            "up": [QPoint(4, 0), QPoint(0, 4), QPoint(8, 4)],
            "dn": [QPoint(0, 0), QPoint(8, 0), QPoint(4, 4)],
        }
        for name, points in arrows.items():
            pix = QPixmap(9, 5)
            pix.fill(QColor(0, 0, 0, 0))
            p = QPainter(pix)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawPolygon(QPolygon(points))
            p.end()
            path = os.path.join(icon_dir, f"{name}.png")
            pix.save(path)
            setattr(self, f"_arrow_{name}", path.replace("\\", "/"))

    def _init_ui(self) -> None:
        central = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setSpacing(6)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # ============================================================
        #  Top bar: [server + settings]  [view modes centered]  [quit]
        # ============================================================
        top_bar = QHBoxLayout()
        top_bar.setSpacing(6)

        # -- Left group --
        left_group = QWidget()
        left_lay = QHBoxLayout(left_group)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(6)

        self._btn_settings = QPushButton("\u2699")
        self._btn_settings.setStyleSheet("padding: 4px 10px; font-size: 16px;")
        self._btn_settings.setToolTip("Settings")
        self._btn_settings.clicked.connect(self._show_settings_dialog)
        left_lay.addWidget(self._btn_settings)

        self._btn_devices = QPushButton("\u25c0 Devices")
        self._btn_devices.setStyleSheet("padding: 4px 10px; font-size: 11px; color: #90CAF9;")
        self._btn_devices.setToolTip("Back to device selection")
        self._btn_devices.clicked.connect(self._show_device_select)
        self._btn_devices.setVisible(False)  # shown only on console page
        left_lay.addWidget(self._btn_devices)

        left_lay.addStretch()
        top_bar.addWidget(left_group, 1)

        # -- Center: view mode selector --
        self._view_mode = "split"
        self._view_group = QButtonGroup(self)
        self._view_group.setExclusive(True)
        view_modes = [
            ("split", "Split View", "1"),
            ("camera", "Camera", "2"),
            ("lidar", "LiDAR", "3"),
        ]
        self._view_buttons: dict[str, QPushButton] = {}
        for mode, label, shortcut_key in view_modes:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFont(QFont("Consolas", 9))
            btn.clicked.connect(lambda _, m=mode: self._set_view_mode(m))
            self._view_group.addButton(btn)
            self._view_buttons[mode] = btn
            top_bar.addWidget(btn)
            sc = QShortcut(QKeySequence(f"Ctrl+{shortcut_key}"), self)
            sc.activated.connect(lambda m=mode: self._set_view_mode(m))
        self._view_buttons["split"].setChecked(True)

        # -- Right group --
        right_group = QWidget()
        right_lay = QHBoxLayout(right_group)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(6)
        right_lay.addStretch()

        btn_quit = QPushButton("\u2715")
        btn_quit.setStyleSheet("padding: 4px 10px; font-size: 14px; color: #888;")
        btn_quit.setToolTip("Quit")
        btn_quit.clicked.connect(self.close)
        right_lay.addWidget(btn_quit)

        top_bar.addWidget(right_group, 1)

        main_layout.addLayout(top_bar)

        # ============================================================
        #  Stacked widget: page 0 = device select, page 1 = console
        # ============================================================
        self._stack = QStackedWidget()

        # --- Page 0: Device Selection ---
        self._device_select = DeviceSelectPanel()
        self._stack.addWidget(self._device_select)  # index 0

        # --- Page 1: Console ---
        console_page = QWidget()
        console_layout = QVBoxLayout()
        console_layout.setSpacing(6)
        console_layout.setContentsMargins(0, 0, 0, 0)

        # Shared panels
        self._camera_panel = CameraPanel()
        self._lidar_panel = LidarPanel()
        self._status_panel = StatusPanel()
        self._command_panel = CommandPanel(self._conn)
        self._command_panel.setMinimumWidth(280)

        # Visualization: horizontal splitter (camera + lidar)
        self._h_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._viz_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._viz_splitter.addWidget(self._camera_panel)
        self._viz_splitter.addWidget(self._lidar_panel)
        self._viz_splitter.setStretchFactor(0, 5)
        self._viz_splitter.setStretchFactor(1, 4)
        self._h_splitter.addWidget(self._viz_splitter)

        # Right sidebar (single-view modes) — scrollable
        self._right_scroll = QScrollArea()
        self._right_scroll.setWidgetResizable(True)
        self._right_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._right_scroll.setStyleSheet("""
            QScrollArea { background: transparent; }
            QScrollBar:vertical {
                background: transparent; width: 6px; margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #444; border-radius: 3px; min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
        """)
        self._right_inner = QWidget()
        self._right_layout = QVBoxLayout()
        self._right_layout.setContentsMargins(6, 4, 2, 4)
        self._right_layout.setSpacing(10)
        self._right_inner.setLayout(self._right_layout)
        self._right_scroll.setWidget(self._right_inner)
        self._right_scroll.setMinimumWidth(300)
        self._right_scroll.setMaximumWidth(380)
        self._h_splitter.addWidget(self._right_scroll)
        self._h_splitter.setStretchFactor(0, 7)
        self._h_splitter.setStretchFactor(1, 3)

        console_layout.addWidget(self._h_splitter, 1)

        # Bottom controls (split-view mode)
        self._bottom_widget = QWidget()
        self._bottom_layout = QHBoxLayout()
        self._bottom_layout.setContentsMargins(0, 4, 0, 0)
        self._bottom_layout.setSpacing(8)
        self._bottom_widget.setLayout(self._bottom_layout)
        self._bottom_widget.setMaximumHeight(280)
        console_layout.addWidget(self._bottom_widget)

        # Log panel
        self._log_panel = LogPanel()
        console_layout.addWidget(self._log_panel, 0)

        console_page.setLayout(console_layout)
        self._stack.addWidget(console_page)  # index 1

        main_layout.addWidget(self._stack, 1)

        # Start on device selection page
        self._stack.setCurrentIndex(0)

        central.setLayout(main_layout)
        self.setCentralWidget(central)

        # ============================================================
        #  Dark theme
        # ============================================================
        stylesheet = """
            QMainWindow {
                background-color: #121212;
                color: #E0E0E0;
                border: 1px solid #444;
                border-radius: 6px;
            }
            QWidget {
                background-color: #121212;
                color: #E0E0E0;
            }
            QDialog, QMessageBox {
                border: 1px solid #555;
                border-radius: 6px;
                padding: 8px;
            }
            QGroupBox {
                border: 1px solid #333;
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 8px;
                font-weight: bold;
                color: #B0BEC5;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QPushButton {
                background-color: #333;
                color: #E0E0E0;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 6px 16px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #444;
            }
            QPushButton:pressed {
                background-color: #555;
            }
            QPushButton:disabled {
                background-color: #1a1a1a;
                color: #3a3a3a;
                border-color: #2a2a2a;
            }
            QSpinBox {
                background-color: #1a1a1a;
                color: #E0E0E0;
                border: 1px solid #444;
                border-radius: 3px;
                padding: 2px;
                padding-right: 18px;
            }
            QSpinBox::up-button {
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 16px;
                border-left: 1px solid #444;
                background-color: #2a2a2a;
                border-top-right-radius: 3px;
            }
            QSpinBox::up-button:hover { background-color: #3a3a3a; }
            QSpinBox::up-button:pressed { background-color: #555; }
            QSpinBox::down-button {
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: 16px;
                border-left: 1px solid #444;
                background-color: #2a2a2a;
                border-bottom-right-radius: 3px;
            }
            QSpinBox::down-button:hover { background-color: #3a3a3a; }
            QSpinBox::down-button:pressed { background-color: #555; }
            QSpinBox::up-arrow {
                image: url(ARROW_UP_PATH);
                width: 9px; height: 5px;
            }
            QSpinBox::down-arrow {
                image: url(ARROW_DN_PATH);
                width: 9px; height: 5px;
            }
            QTextEdit {
                background-color: #0a0a0a;
                color: #E0E0E0;
                border: 1px solid #333;
            }
            QLabel {
                color: #B0BEC5;
            }
            QCheckBox {
                color: #B0BEC5;
                spacing: 4px;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border: 1px solid #555;
                border-radius: 3px;
                background-color: #1a1a1a;
            }
            QCheckBox::indicator:checked {
                background-color: #1565C0;
                border-color: #1976D2;
            }
            QCheckBox::indicator:disabled {
                background-color: #1a1a1a;
                border-color: #2a2a2a;
            }
        """
        stylesheet = stylesheet.replace("ARROW_UP_PATH", self._arrow_up)
        stylesheet = stylesheet.replace("ARROW_DN_PATH", self._arrow_dn)
        self.setStyleSheet(stylesheet)

        # Apply initial view mode
        self._set_view_mode("split")

        # Center on screen
        screen = self.screen().availableGeometry()
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2,
        )

        # Hide view mode buttons until connected
        for btn in self._view_buttons.values():
            btn.setVisible(False)


    # ================================================================
    #  Signals
    # ================================================================

    def _connect_signals(self) -> None:
        conn = self._conn
        conn.device_connected.connect(self._on_connected)
        conn.device_disconnected.connect(self._on_disconnected)
        conn.status_received.connect(self._on_status)
        conn.camera_frame_received.connect(self._on_camera_frame)
        conn.lidar_frame_received.connect(self._on_lidar_frame)
        conn.response_received.connect(self._on_response)
        conn.raw_message_received.connect(self._log_panel.log_raw)
        conn.raw_message_received.connect(self._on_raw_data)
        conn.log_message.connect(self._log_panel.log_text)
        self._command_panel.reset_requested.connect(self._on_reset)
        self._device_select.connect_requested.connect(self._on_connect_device_requested)
        self._server.server_stopped.connect(self._on_server_stopped)
        self._server.server_started.connect(self._on_server_started)

        # UDP Discovery callback (runs in background thread, use QTimer to cross to GUI thread)
        if self._discovery:
            self._discovery_timer = QTimer(self)
            self._discovery_timer.setInterval(1500)
            self._discovery_timer.timeout.connect(self._poll_discovery)
            self._discovery_timer.start()

    # ================================================================
    #  Connection events
    # ================================================================

    def _poll_discovery(self) -> None:
        """Periodically read discovered devices from the listener (thread-safe via QTimer)."""
        if self._discovery:
            devices = self._discovery.devices
            connected = self._conn.device_name if self._conn.connected else ""
            self._device_select.update_devices(devices, connected)

    def _on_connect_device_requested(self, device_name: str, device_ip: str) -> None:
        """User clicked Connect on a discovered device."""
        if not self._server.running:
            self._conn.log_message.emit("Cannot connect: server not running. Start the server first.")
            return

        server_ip = self._get_local_ip()
        server_port = self._server.port

        self._conn.log_message.emit(
            f"Sending CONNECT to {device_name} @ {device_ip} -> {server_ip}:{server_port}"
        )

        if self._discovery:
            if not self._discovery.send_connect(device_ip, server_ip, server_port):
                self._conn.log_message.emit("Failed to send CONNECT packet")

    @staticmethod
    def _get_local_ip() -> str:
        """Get this machine's LAN IP address."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except OSError:
            return "127.0.0.1"

    def _on_connected(self, device_name: str, initial_status: bytes) -> None:
        self._status_panel.set_connected(device_name)
        self._connected_at = time.monotonic()
        self._total_bytes = 0
        self._uptime_timer.start()
        self._restart_status_timer()
        # Switch to console page
        self._stack.setCurrentIndex(1)
        self._btn_devices.setVisible(True)
        for btn in self._view_buttons.values():
            btn.setVisible(True)
        # Apply initial status from INIT handshake if available
        if initial_status:
            self._on_status(initial_status)
        # Request fresh status after connection to get accurate sensor flags
        QTimer.singleShot(500, self._poll_status)

    def _on_disconnected(self) -> None:
        self._status_panel.set_disconnected()
        self._uptime_timer.stop()
        self._status_timer.stop()
        self._lidar_panel.reset()
        # Switch back to device selection
        self._show_device_select()

    def _on_raw_data(self, _direction: str, data: bytes) -> None:
        self._total_bytes += len(data)
        self._status_panel.update_data_total(self._total_bytes)
        if _direction == "RX":
            self._status_panel.update_last_rx()

    def _tick_uptime(self) -> None:
        if self._connected_at > 0:
            elapsed = int(time.monotonic() - self._connected_at)
            self._status_panel.update_uptime(elapsed)

    # ================================================================
    #  Data events
    # ================================================================

    def _on_status(self, data: bytes) -> None:
        status = parse_status(data)
        if status:
            self._status_panel.update_status(status)

    def _on_camera_frame(self, data: bytes) -> None:
        jpeg = parse_camera_frame(data)
        if jpeg:
            self._camera_panel.update_frame(jpeg)

    def _on_lidar_frame(self, data: bytes) -> None:
        frame = parse_lidar_frame(data)
        if frame:
            self._lidar_panel.update_frame(frame)

    def _on_response(self, data: bytes) -> None:
        resp = parse_response(data)
        if not resp:
            return
        # Status response updates the status panel
        if resp.cmd_id == CMD_GET_STATUS and resp.ok and len(resp.payload) >= 17:
            status = DeviceStatus.from_bytes(resp.payload)
            self._status_panel.update_status(status)
        # Clear camera preview on config/param change
        elif resp.cmd_id in (CMD_SET_CAMERA_CONFIG, CMD_CAMERA_SET_PARAM) and resp.ok:
            self._camera_panel.reset()

    # ================================================================
    #  View mode switching
    # ================================================================

    _VIEW_BTN_BASE = "padding: 4px 14px; font-size: 11px; border-radius: 3px;"
    _VIEW_BTN_OFF = _VIEW_BTN_BASE + "background-color: #1a1a1a; color: #666; border: 1px solid #333;"
    _VIEW_BTN_ON = _VIEW_BTN_BASE + "background-color: #1565C0; color: white; border: 1px solid #1976D2;"

    def _set_view_mode(self, mode: str) -> None:
        self._view_mode = mode
        self._view_buttons[mode].setChecked(True)
        for m, btn in self._view_buttons.items():
            btn.setStyleSheet(self._VIEW_BTN_ON if m == mode else self._VIEW_BTN_OFF)

        # Suppress repaints during reparenting to avoid white flash
        self.setUpdatesEnabled(False)

        self._camera_panel.setVisible(mode in ("split", "camera"))
        self._lidar_panel.setVisible(mode in ("split", "lidar"))

        if mode == "split":
            # Full-width viz, controls at bottom
            self._right_scroll.hide()
            self._status_panel.setMaximumWidth(16777215)
            self._command_panel.set_sidebar_mode(False, "split")
            self._bottom_layout.addWidget(self._status_panel, 5)
            self._bottom_layout.addWidget(self._command_panel, 5)
            self._bottom_widget.show()
        else:
            # Single viz + right sidebar
            self._bottom_widget.hide()
            self._status_panel.setMaximumWidth(16777215)  # reset max
            self._command_panel.set_sidebar_mode(True, mode)
            self._right_layout.addWidget(self._status_panel)
            self._right_layout.addWidget(self._command_panel, 1)
            self._right_scroll.show()

        self.setUpdatesEnabled(True)

    # ================================================================
    #  Frameless window dragging
    # ================================================================

    def _edge_at(self, pos) -> str:
        m = self._EDGE_MARGIN
        w, h = self.width(), self.height()
        x, y = int(pos.x()), int(pos.y())
        edge = ""
        if y < m:
            edge += "top"
        elif y > h - m:
            edge += "bottom"
        if x < m:
            edge += "left"
        elif x > w - m:
            edge += "right"
        return edge

    _EDGE_CURSORS = {
        "top": Qt.CursorShape.SizeVerCursor,
        "bottom": Qt.CursorShape.SizeVerCursor,
        "left": Qt.CursorShape.SizeHorCursor,
        "right": Qt.CursorShape.SizeHorCursor,
        "topleft": Qt.CursorShape.SizeFDiagCursor,
        "bottomright": Qt.CursorShape.SizeFDiagCursor,
        "topright": Qt.CursorShape.SizeBDiagCursor,
        "bottomleft": Qt.CursorShape.SizeBDiagCursor,
    }

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        edge = self._edge_at(event.position())
        if edge:
            self._resize_edge = edge
            self._drag_pos = event.globalPosition().toPoint()
            event.accept()
        elif event.position().y() < 40:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        # Resize in progress
        if self._resize_edge and self._drag_pos is not None:
            gp = event.globalPosition().toPoint()
            dx = gp.x() - self._drag_pos.x()
            dy = gp.y() - self._drag_pos.y()
            geo = self.geometry()
            if "right" in self._resize_edge:
                geo.setRight(geo.right() + dx)
            if "bottom" in self._resize_edge:
                geo.setBottom(geo.bottom() + dy)
            if "left" in self._resize_edge:
                geo.setLeft(geo.left() + dx)
            if "top" in self._resize_edge:
                geo.setTop(geo.top() + dy)
            if geo.width() >= self.minimumWidth() and geo.height() >= self.minimumHeight():
                self.setGeometry(geo)
            self._drag_pos = gp
            event.accept()
            return

        # Drag in progress
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return

        # Hover: update cursor
        edge = self._edge_at(event.position())
        if edge in self._EDGE_CURSORS:
            self.setCursor(self._EDGE_CURSORS[edge])
        else:
            self.unsetCursor()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
        self._resize_edge = ""

    def mouseDoubleClickEvent(self, event) -> None:
        if event.position().y() < 40 and not self._edge_at(event.position()):
            if self.isMaximized():
                self.showNormal()
            else:
                self.showMaximized()

    # ================================================================
    #  Settings dialog
    # ================================================================

    def _show_settings_dialog(self) -> None:
        class _SettingsDialog(QDialog):
            """QDialog subclass that blocks Enter from closing."""
            def __init__(self, parent):
                super().__init__(parent)
                self.enter_actions: dict = {}

            def keyPressEvent(self, event):
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    focused = self.focusWidget()
                    # QSpinBox focus is on its internal QLineEdit
                    for widget, action in self.enter_actions.items():
                        if focused is widget or (hasattr(widget, 'lineEdit') and focused is widget.lineEdit()):
                            action()
                            break
                    event.accept()
                    return
                super().keyPressEvent(event)

        dlg = _SettingsDialog(self)
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.FramelessWindowHint)
        dlg.setStyleSheet(self._POPUP_STYLE)
        dlg.setFixedWidth(360)

        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Title bar with close button
        title_bar = QHBoxLayout()
        title_bar.setContentsMargins(12, 8, 8, 4)
        title_label = QLabel("<b>Settings</b>")
        title_bar.addWidget(title_label)
        title_bar.addStretch()
        btn_close = QPushButton("\u2715")
        btn_close.setStyleSheet("padding: 2px 8px; font-size: 13px; color: #888; border: none;")
        btn_close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_close.clicked.connect(dlg.accept)
        title_bar.addWidget(btn_close)
        outer.addLayout(title_bar)

        form = QVBoxLayout()
        form.setContentsMargins(12, 4, 12, 12)
        form.setSpacing(10)

        # --- Status poll section ---
        poll_label = QLabel("<b>Status Poll</b>")
        form.addWidget(poll_label)

        poll_row = QHBoxLayout()
        poll_row.setSpacing(0)
        poll_presets = [("OFF", 0), ("1s", 1000), ("2s", 2000), ("5s", 5000), ("10s", 10000)]
        poll_buttons: list[QPushButton] = []

        _POLL_BTN = "padding: 4px 0; font-size: 11px; border-radius: 0; border: 1px solid #444; min-width: 38px;"
        _POLL_ON = _POLL_BTN + "background-color: #1565C0; color: white; border-color: #1976D2;"
        _POLL_OFF = _POLL_BTN + "background-color: #1a1a1a; color: #888;"
        _POLL_FIRST = " border-top-left-radius: 4px; border-bottom-left-radius: 4px;"
        _POLL_LAST = " border-top-right-radius: 4px; border-bottom-right-radius: 4px;"

        def on_poll_select(ms: int) -> None:
            if ms == self._status_poll_interval:
                return
            self._status_poll_interval = ms
            self._restart_status_timer()
            for b, (_, v) in zip(poll_buttons, poll_presets):
                is_first = b is poll_buttons[0]
                is_last = b is poll_buttons[-1]
                base = _POLL_ON if v == ms else _POLL_OFF
                extra = (_POLL_FIRST if is_first else "") + (_POLL_LAST if is_last else "")
                b.setStyleSheet(base + extra)
            msg = f"Poll interval → {ms // 1000}s" if ms > 0 else "Poll disabled (device push only)"
            self._conn.log_message.emit(f"Settings: {msg}")
            self._save_settings()

        for i, (label, ms) in enumerate(poll_presets):
            btn = QPushButton(label)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            is_active = ms == self._status_poll_interval
            base = _POLL_ON if is_active else _POLL_OFF
            extra = (_POLL_FIRST if i == 0 else "") + (_POLL_LAST if i == len(poll_presets) - 1 else "")
            btn.setStyleSheet(base + extra)
            btn.clicked.connect(lambda _, m=ms: on_poll_select(m))
            poll_buttons.append(btn)
            poll_row.addWidget(btn)

        form.addLayout(poll_row)

        outer.addLayout(form)
        dlg.setLayout(outer)
        dlg.exec()

    # ================================================================
    #  Misc
    # ================================================================

    _POPUP_STYLE = (
        "QMessageBox, QDialog { border: 1px solid #555; border-radius: 6px; padding: 8px; }"
    )

    def closeEvent(self, event) -> None:
        msg = QMessageBox(self)
        msg.setWindowFlags(msg.windowFlags() | Qt.WindowType.FramelessWindowHint)
        msg.setStyleSheet(self._POPUP_STYLE)
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText("Are you sure you want to quit?")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        if msg.exec() == QMessageBox.StandardButton.Yes:
            self._status_timer.stop()
            self._uptime_timer.stop()
            self._server.stop()
            event.accept()
        else:
            event.ignore()

    def _show_device_select(self) -> None:
        """Switch to device selection page."""
        self._stack.setCurrentIndex(0)
        self._btn_devices.setVisible(False)
        for btn in self._view_buttons.values():
            btn.setVisible(False)

    def _on_server_stopped(self) -> None:
        self._status_panel.set_disconnected()
        self._status_timer.stop()
        self._uptime_timer.stop()
        self._show_device_select()

    def _on_server_started(self) -> None:
        pass

    def _save_settings(self) -> None:
        self._settings["status_poll_interval"] = self._status_poll_interval
        self._settings["server_port"] = self._server.port
        settings.save(self._settings)

    def _restart_status_timer(self) -> None:
        self._status_timer.stop()
        if self._status_poll_interval > 0 and self._conn.connected:
            self._status_timer.start(self._status_poll_interval)

    def _poll_status(self) -> None:
        if self._conn.connected:
            self._conn.send_command(CMD_GET_STATUS)

    def _on_reset(self) -> None:
        self._log_panel._clear()
        self._camera_panel.reset()
        self._status_panel.reset()
        self._lidar_panel.reset()
        self._command_panel.reset_lidar_state()
