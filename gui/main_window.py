"""Main window layout assembling all panels."""

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
    QDialogButtonBox,
    QFormLayout,
    QMessageBox,
    QButtonGroup,
)
from PyQt6.QtCore import Qt, QTimer, QPoint
from PyQt6.QtGui import QFont, QShortcut, QKeySequence

from protocol import (
    parse_status,
    parse_camera_frame,
    parse_lidar_frame,
    parse_response,
    DeviceStatus,
    InitAckSettings,
    INIT_FLAG_START_STREAM,
    CMD_GET_STATUS,
)
from ws_server import DeviceConnection, WebSocketServer

from gui.camera_panel import CameraPanel
from gui.lidar_panel import LidarPanel
from gui.status_panel import StatusPanel
from gui.command_panel import CommandPanel
from gui.log_panel import LogPanel


class MainWindow(QMainWindow):
    def __init__(self, connection: DeviceConnection, server: WebSocketServer):
        super().__init__()
        self._conn = connection
        self._server = server
        self.setWindowTitle("Core Device Test Client")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(1200, 920)

        self._status_poll_interval = 2000  # ms, 0 = off (device pushes)
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

        self._init_ui()
        self._connect_signals()

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

        self._server_label = QLabel("Server: OFF")
        self._server_label.setFont(QFont("Consolas", 9))
        self._server_label.setStyleSheet("color: #F44336;")
        left_lay.addWidget(self._server_label)

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
        #  Shared panels (reparented on view switch)
        # ============================================================
        self._camera_panel = CameraPanel()
        self._lidar_panel = LidarPanel()
        self._status_panel = StatusPanel()
        self._command_panel = CommandPanel(self._conn)
        self._command_panel.setMinimumWidth(280)

        # ============================================================
        #  Visualization: horizontal splitter (camera + lidar)
        # ============================================================
        self._h_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._viz_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._viz_splitter.addWidget(self._camera_panel)
        self._viz_splitter.addWidget(self._lidar_panel)
        self._viz_splitter.setStretchFactor(0, 5)
        self._viz_splitter.setStretchFactor(1, 4)
        self._h_splitter.addWidget(self._viz_splitter)

        # Right sidebar (single-view modes)
        self._right_widget = QWidget()
        self._right_layout = QVBoxLayout()
        self._right_layout.setContentsMargins(6, 4, 6, 4)
        self._right_layout.setSpacing(10)
        self._right_widget.setLayout(self._right_layout)
        self._right_widget.setMinimumWidth(280)
        self._right_widget.setMaximumWidth(360)
        self._h_splitter.addWidget(self._right_widget)
        self._h_splitter.setStretchFactor(0, 7)
        self._h_splitter.setStretchFactor(1, 3)

        main_layout.addWidget(self._h_splitter, 1)

        # Bottom controls (split-view mode)
        self._bottom_widget = QWidget()
        self._bottom_layout = QHBoxLayout()
        self._bottom_layout.setContentsMargins(0, 4, 0, 0)
        self._bottom_layout.setSpacing(8)
        self._bottom_widget.setLayout(self._bottom_layout)
        self._bottom_widget.setMaximumHeight(180)
        main_layout.addWidget(self._bottom_widget)

        # ============================================================
        #  Log panel
        # ============================================================
        self._log_panel = LogPanel()
        main_layout.addWidget(self._log_panel, 0)

        central.setLayout(main_layout)
        self.setCentralWidget(central)

        # ============================================================
        #  Dark theme
        # ============================================================
        self.setStyleSheet("""
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
                padding: 3px;
            }
            QTextEdit {
                background-color: #0a0a0a;
                color: #E0E0E0;
                border: 1px solid #333;
            }
            QLabel {
                color: #B0BEC5;
            }
        """)

        # Apply initial view mode
        self._set_view_mode("split")

        # Center on screen
        screen = self.screen().availableGeometry()
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2,
        )

        # Open settings on first launch
        QTimer.singleShot(0, self._show_settings_dialog)

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

    # ================================================================
    #  Connection events
    # ================================================================

    def _on_connected(self, device_name: str, initial_status: bytes) -> None:
        self._status_panel.set_connected(device_name)
        self._connected_at = time.monotonic()
        self._total_bytes = 0
        self._uptime_timer.start()
        self._restart_status_timer()
        # Apply initial status from INIT handshake if available
        if initial_status:
            self._on_status(initial_status)

    def _on_disconnected(self) -> None:
        self._status_panel.set_disconnected()
        self._uptime_timer.stop()
        self._status_timer.stop()

    def _on_raw_data(self, _direction: str, data: bytes) -> None:
        self._total_bytes += len(data)
        self._status_panel.update_data_total(self._total_bytes)

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
        if resp.cmd_id == CMD_GET_STATUS and resp.ok and len(resp.payload) >= 17:
            status = DeviceStatus.from_bytes(resp.payload)
            self._status_panel.update_status(status)

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

        self._camera_panel.setVisible(mode in ("split", "camera"))
        self._lidar_panel.setVisible(mode in ("split", "lidar"))

        if mode == "split":
            # Full-width viz, controls at bottom
            self._right_widget.hide()
            self._status_panel.setMaximumWidth(16777215)
            self._command_panel.set_sidebar_mode(False)
            self._bottom_layout.addWidget(self._status_panel, 6)
            self._bottom_layout.addWidget(self._command_panel, 4)
            self._bottom_widget.show()
        else:
            # Single viz + right sidebar
            self._bottom_widget.hide()
            self._status_panel.setMaximumWidth(16777215)  # reset max
            self._command_panel.set_sidebar_mode(True)
            self._right_layout.addWidget(self._status_panel)
            self._right_layout.addWidget(self._command_panel, 1)
            self._right_widget.show()

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
        dlg.setFixedWidth(300)

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
        form.addWidget(QLabel("<b>Status Poll</b>"))
        poll_row = QHBoxLayout()
        poll_row.addWidget(QLabel("Interval:"))
        poll_spin = QSpinBox()
        poll_spin.setRange(0, 10)
        poll_spin.setValue(self._status_poll_interval // 1000)
        poll_spin.setSuffix(" sec")
        poll_spin.setToolTip("0 = disabled (device push only)")
        poll_spin.setSpecialValueText("OFF")
        poll_row.addWidget(poll_spin)

        btn_apply_poll = QPushButton("Apply")
        btn_apply_poll.setStyleSheet("padding: 2px 10px; font-size: 11px;")
        poll_row.addWidget(btn_apply_poll)

        poll_status = QLabel()
        poll_status.setFont(QFont("Consolas", 8))
        poll_status.setFixedHeight(14)
        poll_row.addWidget(poll_status)

        def on_apply_poll() -> None:
            new_val = poll_spin.value() * 1000
            if new_val == self._status_poll_interval:
                return
            self._status_poll_interval = new_val
            self._restart_status_timer()
            if new_val > 0:
                msg = f"Poll interval → {poll_spin.value()}s"
            else:
                msg = "Poll disabled (device push only)"
            poll_status.setText(msg)
            poll_status.setStyleSheet("color: #4CAF50;")
            self._conn.log_message.emit(f"Settings: {msg}")
            QTimer.singleShot(2000, lambda: poll_status.setText(""))

        btn_apply_poll.clicked.connect(on_apply_poll)
        dlg.enter_actions[poll_spin] = on_apply_poll
        form.addLayout(poll_row)

        # --- Separator ---
        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: #333;")
        form.addWidget(sep)

        # --- Server section ---
        form.addWidget(QLabel("<b>Server</b>"))
        server_row = QHBoxLayout()
        server_row.addWidget(QLabel("Port:"))
        port_spin = QSpinBox()
        port_spin.setRange(1024, 65535)
        port_spin.setValue(self._server.port)
        server_row.addWidget(port_spin)

        btn_server = QPushButton()
        if self._server.running:
            btn_server.setText("Stop Server")
            btn_server.setStyleSheet("background-color: #F44336; color: white;")
        else:
            btn_server.setText("Start Server")
            btn_server.setStyleSheet("background-color: #4CAF50; color: white;")

        def set_running_ui() -> None:
            if btn_server.isVisible():
                btn_server.setText("Stop Server")
                btn_server.setStyleSheet("background-color: #F44336; color: white;")
                btn_server.setEnabled(True)
                port_spin.setEnabled(True)
            self._update_server_label()
            self._conn.log_message.emit(f"Server started on port {self._server.port}")

        def set_stopped_ui(error: str = "") -> None:
            if btn_server.isVisible():
                btn_server.setText("Start Server")
                btn_server.setStyleSheet("background-color: #4CAF50; color: white;")
                btn_server.setEnabled(True)
                port_spin.setEnabled(True)
            self._update_server_label()

        self._server.server_started.connect(set_running_ui)
        self._server.server_failed.connect(set_stopped_ui)

        def _start_server() -> None:
            self._server.port = port_spin.value()
            btn_server.setEnabled(False)
            port_spin.setEnabled(False)
            btn_server.setText("Starting...")
            self._server.start()

        def _stop_server() -> None:
            self._server.stop()
            set_stopped_ui()

        def on_server_click() -> None:
            if self._server.running:
                _stop_server()
            else:
                _start_server()

        def on_port_changed() -> None:
            new_port = port_spin.value()
            if new_port == self._server.port and self._server.running:
                return
            if self._server.running:
                self._server.stop()
            # Brief delay to let the old socket release
            QTimer.singleShot(100, _start_server)

        btn_server.clicked.connect(on_server_click)
        dlg.enter_actions[port_spin] = on_port_changed
        server_row.addWidget(btn_server)
        form.addLayout(server_row)

        outer.addLayout(form)
        dlg.setLayout(outer)

        def on_dialog_finished() -> None:
            self._server.server_started.disconnect(set_running_ui)
            self._server.server_failed.disconnect(set_stopped_ui)

        dlg.finished.connect(on_dialog_finished)
        port_spin.setFocus()
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

    def _update_server_label(self) -> None:
        if self._server.running:
            self._server_label.setText(f"Server: ON (port {self._server.port})")
            self._server_label.setStyleSheet("color: #4CAF50;")
        else:
            self._server_label.setText("Server: OFF")
            self._server_label.setStyleSheet("color: #F44336;")

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
        self._lidar_panel._canvas._points = []
        self._lidar_panel._canvas.update()
        self._lidar_panel._frame_count = 0
        self._lidar_panel._info_label.setText("Points: -- | Frames: 0")
