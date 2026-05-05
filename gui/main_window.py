"""Main window with sensor-specific tabs for the debug console."""

from __future__ import annotations

import os
import socket
import tempfile
import time

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QKeySequence, QPainter, QPixmap, QPolygon, QShortcut
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import settings
from protocol import CMD_GET_STATUS, DeviceStatus, parse_camera_frame, parse_imu_frame, parse_lidar_frame, parse_response, parse_status
from udp_discovery import UdpDiscoveryListener
from ws_server import DeviceConnection, WebSocketServer

from gui.camera_panel import CameraPanel
from gui.control_panels import (
    CameraControlPanel,
    ImuControlPanel,
    LidarControlPanel,
    MappingControlPanel,
    OverviewControlPanel,
)
from gui.device_select_panel import DeviceSelectPanel
from gui.imu_panel import ImuPanel
from gui.lidar3d_panel import Lidar3DPanel
from gui.lidar_panel import LidarPanel
from gui.log_panel import LogPanel
from gui.prototype_simulator import PrototypeSimulator
from gui.sd_card_panel import SdCardPanel
from gui.status_panel import StatusPanel


class MainWindow(QMainWindow):
    def __init__(self, connection: DeviceConnection, server: WebSocketServer, discovery: UdpDiscoveryListener | None = None):
        super().__init__()
        self._conn = connection
        self._server = server
        self._discovery = discovery
        self._settings = settings.load()
        self._status_poll_interval = self._settings.get("status_poll_interval", 5000)
        self._connected_at = 0.0
        self._total_bytes = 0
        self._drag_pos: QPoint | None = None
        self._resize_edge = ""
        self._EDGE_MARGIN = 6

        self.setWindowTitle("Core Device Debug Console")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(1320, 940)

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._poll_status)
        self._uptime_timer = QTimer(self)
        self._uptime_timer.setInterval(1000)
        self._uptime_timer.timeout.connect(self._tick_uptime)

        self._tab_indices: dict[str, int] = {}
        self._current_status = DeviceStatus()
        self._demo_mode = False
        self._simulator = PrototypeSimulator(self)

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
            painter = QPainter(pix)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawPolygon(QPolygon(points))
            painter.end()
            path = os.path.join(icon_dir, f"{name}.png")
            pix.save(path)
            setattr(self, f"_arrow_{name}", path.replace("\\", "/"))

    def _init_ui(self) -> None:
        central = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(8, 8, 8, 8)

        top_bar = QHBoxLayout()
        top_bar.setSpacing(6)

        self._btn_settings = QPushButton("\u2699")
        self._btn_settings.setStyleSheet(
            "QPushButton { padding: 4px 8px; font-size: 16px; background: transparent; border: none; } "
            "QPushButton:hover { background-color: #1B2731; border-radius: 4px; }"
        )
        self._btn_settings.clicked.connect(self._show_settings_dialog)
        top_bar.addWidget(self._btn_settings)

        self._btn_devices = QPushButton("\u25c0 Devices")
        self._btn_devices.setStyleSheet(
            "QPushButton { padding: 4px 8px; font-size: 11px; color: #90CAF9; background: transparent; border: none; } "
            "QPushButton:hover { background-color: #1B2731; border-radius: 4px; }"
        )
        self._btn_devices.clicked.connect(self._show_device_select)
        self._btn_devices.setVisible(False)
        top_bar.addWidget(self._btn_devices)

        self._title = QLabel("Sensor Debug Console")
        self._title.setFont(QFont("Consolas", 11))
        self._title.setStyleSheet("color: #CFD8DC;")
        top_bar.addWidget(self._title)
        top_bar.addStretch()

        btn_quit = QPushButton("\u2715")
        btn_quit.setStyleSheet(
            "QPushButton { padding: 4px 8px; font-size: 14px; color: #888; background: transparent; border: none; } "
            "QPushButton:hover { background-color: #3B1D1D; color: #F44336; border-radius: 4px; }"
        )
        btn_quit.clicked.connect(self.close)
        top_bar.addWidget(btn_quit)
        main_layout.addLayout(top_bar)

        self._stack = QStackedWidget()
        self._device_select = DeviceSelectPanel()
        self._stack.addWidget(self._device_select)

        console_page = QWidget()
        console_layout = QVBoxLayout()
        console_layout.setSpacing(8)
        console_layout.setContentsMargins(0, 0, 0, 0)

        self._status_panel = StatusPanel()
        self._dashboard_camera_panel = CameraPanel()
        self._dashboard_lidar_panel = LidarPanel()
        self._dashboard_status_panel = StatusPanel()
        self._dashboard_command_panel = OverviewControlPanel(self._conn)
        self._dashboard_command_panel.setMinimumWidth(280)
        self._camera_panel = CameraPanel()
        self._camera_controls = CameraControlPanel(self._conn)
        self._lidar_panel = LidarPanel()
        self._lidar_controls = LidarControlPanel(self._conn)
        self._imu_panel = ImuPanel()
        self._imu_controls = ImuControlPanel(self._conn, self._imu_panel)
        self._lidar3d_panel = Lidar3DPanel()
        self._map_controls = MappingControlPanel(self._lidar3d_panel, self._toggle_demo)
        self._sd_panel = SdCardPanel(self._conn)
        self._log_panel = LogPanel()

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        dashboard_tab = QWidget()
        dashboard_layout = QVBoxLayout()
        dashboard_layout.setSpacing(8)
        dashboard_layout.setContentsMargins(0, 0, 0, 0)

        dashboard_splitter = QSplitter(Qt.Orientation.Horizontal)
        dashboard_splitter.addWidget(self._dashboard_camera_panel)
        dashboard_splitter.addWidget(self._dashboard_lidar_panel)
        dashboard_splitter.setStretchFactor(0, 5)
        dashboard_splitter.setStretchFactor(1, 4)
        dashboard_layout.addWidget(dashboard_splitter, 1)

        dashboard_bottom = QWidget()
        dashboard_bottom_layout = QHBoxLayout()
        dashboard_bottom_layout.setContentsMargins(0, 0, 0, 0)
        dashboard_bottom_layout.setSpacing(8)
        dashboard_bottom_layout.addWidget(self._dashboard_status_panel, 5)
        dashboard_bottom_layout.addWidget(self._dashboard_command_panel, 5)
        dashboard_bottom.setLayout(dashboard_bottom_layout)
        dashboard_bottom.setMaximumHeight(300)
        dashboard_layout.addWidget(dashboard_bottom, 0)

        dashboard_tab.setLayout(dashboard_layout)
        self._tab_indices["dashboard"] = self._tabs.addTab(dashboard_tab, "Dashboard")

        camera_tab = QWidget()
        camera_layout = QHBoxLayout()
        camera_layout.setSpacing(8)
        camera_layout.setContentsMargins(0, 0, 0, 0)
        camera_layout.addWidget(self._camera_panel, 7)
        camera_layout.addWidget(self._camera_controls, 4)
        camera_tab.setLayout(camera_layout)
        self._tab_indices["camera"] = self._tabs.addTab(camera_tab, "Camera")

        lidar_tab = QWidget()
        lidar_layout = QHBoxLayout()
        lidar_layout.setSpacing(8)
        lidar_layout.setContentsMargins(0, 0, 0, 0)
        lidar_layout.addWidget(self._lidar_panel, 7)
        lidar_layout.addWidget(self._lidar_controls, 4)
        lidar_tab.setLayout(lidar_layout)
        self._tab_indices["lidar2d"] = self._tabs.addTab(lidar_tab, "LiDAR (2D)")

        imu_tab = QWidget()
        imu_layout = QHBoxLayout()
        imu_layout.setSpacing(8)
        imu_layout.setContentsMargins(0, 0, 0, 0)
        imu_layout.addWidget(self._imu_panel, 7)
        imu_layout.addWidget(self._imu_controls, 3)
        imu_tab.setLayout(imu_layout)
        self._tab_indices["imu"] = self._tabs.addTab(imu_tab, "IMU")

        lidar3d_tab = QWidget()
        lidar3d_layout = QHBoxLayout()
        lidar3d_layout.setSpacing(8)
        lidar3d_layout.setContentsMargins(0, 0, 0, 0)
        lidar3d_layout.addWidget(self._lidar3d_panel, 7)
        lidar3d_layout.addWidget(self._map_controls, 3)
        lidar3d_tab.setLayout(lidar3d_layout)
        self._tab_indices["lidar3d"] = self._tabs.addTab(lidar3d_tab, "LiDAR (3D)")
        self._tab_indices["sd"] = self._tabs.addTab(self._sd_panel, "SD Viewer")

        self._console_splitter = QSplitter(Qt.Orientation.Vertical)
        self._console_splitter.addWidget(self._tabs)
        self._console_splitter.addWidget(self._log_panel)
        self._console_splitter.setStretchFactor(0, 5)
        self._console_splitter.setStretchFactor(1, 1)
        console_layout.addWidget(self._console_splitter, 1)
        console_page.setLayout(console_layout)
        self._stack.addWidget(console_page)

        self._stack.setCurrentIndex(0)
        main_layout.addWidget(self._stack, 1)

        central.setLayout(main_layout)
        self.setCentralWidget(central)
        self._apply_styles()
        self._update_sensor_tabs(None)
        self._console_splitter.setSizes([760, 150])

        screen = self.screen().availableGeometry()
        self.move((screen.width() - self.width()) // 2, (screen.height() - self.height()) // 2)

        QShortcut(QKeySequence("Ctrl+1"), self, activated=lambda: self._tabs.setCurrentIndex(self._tab_indices["dashboard"]))
        QShortcut(QKeySequence("Ctrl+2"), self, activated=lambda: self._tabs.setCurrentIndex(self._tab_indices["camera"]))
        QShortcut(QKeySequence("Ctrl+3"), self, activated=lambda: self._tabs.setCurrentIndex(self._tab_indices["lidar2d"]))
        QShortcut(QKeySequence("Ctrl+4"), self, activated=lambda: self._tabs.setCurrentIndex(self._tab_indices["imu"]))
        QShortcut(QKeySequence("Ctrl+5"), self, activated=lambda: self._tabs.setCurrentIndex(self._tab_indices["lidar3d"]))
        QShortcut(QKeySequence("Ctrl+6"), self, activated=lambda: self._tabs.setCurrentIndex(self._tab_indices["sd"]))

    def _apply_styles(self) -> None:
        stylesheet = """
            QMainWindow {
                background-color: #101418;
                color: #E0E0E0;
                border: 1px solid #28313A;
                border-radius: 6px;
            }
            QWidget {
                background-color: #101418;
                color: #E0E0E0;
            }
            QDialog, QMessageBox {
                background-color: #121920;
                border: 1px solid #33414F;
                border-radius: 8px;
                padding: 8px;
            }
            QGroupBox {
                background-color: #121920;
                border: 1px solid #24303B;
                border-radius: 10px;
                margin-top: 12px;
                padding-top: 10px;
                font-weight: bold;
                color: #C7D2DC;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
            QPushButton {
                background-color: #1D2731;
                color: #E5EDF3;
                border: 1px solid #34414D;
                border-radius: 7px;
                padding: 7px 16px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #24313D; border-color: #47627C; }
            QPushButton:pressed { background-color: #2A3946; }
            QPushButton:disabled {
                background-color: #151B20;
                color: #41505B;
                border-color: #202830;
            }
            QSpinBox, QComboBox, QTreeWidget {
                background-color: #0D1318;
                color: #E0E0E0;
                border: 1px solid #34414D;
                border-radius: 7px;
                padding: 4px 6px;
            }
            QSpinBox::up-arrow { image: url(ARROW_UP_PATH); width: 9px; height: 5px; }
            QSpinBox::down-arrow { image: url(ARROW_DN_PATH); width: 9px; height: 5px; }
            QTextEdit { background-color: #091016; color: #E0E0E0; border: 1px solid #24303B; border-radius: 8px; }
            QLabel { color: #B0BEC5; }
            QCheckBox { color: #B0BEC5; spacing: 4px; }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border: 1px solid #455463;
                border-radius: 3px;
                background-color: #0D1318;
            }
            QCheckBox::indicator:checked {
                background-color: #2B6CB0;
                border-color: #58A6FF;
            }
            QTabWidget::pane {
                background: #0F151B;
                border: 1px solid #24303B;
                border-radius: 12px;
                padding: 10px;
                top: -1px;
            }
            QTabBar::tab {
                background: #121A21;
                border: 1px solid #24303B;
                border-bottom: none;
                padding: 9px 18px;
                margin-right: 6px;
                border-top-left-radius: 9px;
                border-top-right-radius: 9px;
                color: #7D93A8;
            }
            QTabBar::tab:selected {
                background: #1B2731;
                color: #E8F3FF;
                border-color: #3B5268;
            }
            QTabBar::tab:disabled {
                color: #465563;
                background: #0E1318;
            }
            QSplitter::handle {
                background-color: #16202A;
            }
            QSplitter::handle:vertical {
                height: 6px;
            }
            QSplitter::handle:horizontal {
                width: 6px;
            }
            QHeaderView::section {
                background-color: #16202A;
                color: #A9B8C6;
                border: none;
                border-right: 1px solid #24303B;
                padding: 6px 8px;
            }
        """
        self.setStyleSheet(stylesheet.replace("ARROW_UP_PATH", self._arrow_up).replace("ARROW_DN_PATH", self._arrow_dn))

    def _connect_signals(self) -> None:
        self._conn.device_connected.connect(self._on_connected)
        self._conn.device_disconnected.connect(self._on_disconnected)
        self._conn.status_received.connect(self._on_status)
        self._conn.camera_frame_received.connect(self._on_camera_frame)
        self._conn.lidar_frame_received.connect(self._on_lidar_frame)
        self._conn.imu_frame_received.connect(self._on_imu_frame)
        self._conn.response_received.connect(self._on_response)
        self._conn.raw_message_received.connect(self._log_panel.log_raw)
        self._conn.raw_message_received.connect(self._on_raw_data)
        self._conn.log_message.connect(self._log_panel.log_text)
        self._simulator.frame_ready.connect(self._on_demo_frame)
        self._simulator.started.connect(self._on_demo_started)
        self._simulator.stopped.connect(self._on_demo_stopped)
        self._dashboard_command_panel.reset_requested.connect(self._on_reset)
        self._device_select.connect_requested.connect(self._on_connect_device_requested)
        self._server.server_stopped.connect(self._on_server_stopped)

        if self._discovery:
            self._discovery_timer = QTimer(self)
            self._discovery_timer.setInterval(1500)
            self._discovery_timer.timeout.connect(self._poll_discovery)
            self._discovery_timer.start()

    def _poll_discovery(self) -> None:
        if self._discovery:
            devices = self._discovery.devices
            connected = self._conn.device_name if self._conn.connected else ""
            self._device_select.update_devices(devices, connected)

    def _on_connect_device_requested(self, device_name: str, device_ip: str) -> None:
        if not self._server.running:
            self._conn.log_message.emit("Cannot connect: server not running.")
            return
        if self._conn.connected and self._conn.device_name == device_name:
            self._stack.setCurrentIndex(1)
            self._btn_devices.setVisible(True)
            return
        if self._conn.connected:
            self._conn.log_message.emit(f"Disconnecting {self._conn.device_name} to switch device...")
            self._conn.disconnect()

        self._sync_handshake_settings()
        server_ip = self._get_local_ip()
        self._conn.log_message.emit(f"Sending CONNECT to {device_name} @ {device_ip} -> {server_ip}:{self._server.port}")
        if self._discovery and not self._discovery.send_connect(device_ip, server_ip, self._server.port):
            self._conn.log_message.emit("Failed to send CONNECT packet")

    def _sync_handshake_settings(self) -> None:
        self._camera_controls.sync_init_settings()
        self._lidar_controls.sync_init_settings()

    @staticmethod
    def _get_local_ip() -> str:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                return sock.getsockname()[0]
        except OSError:
            return "127.0.0.1"

    def _on_connected(self, device_name: str, initial_status: bytes) -> None:
        if self._demo_mode:
            self._stop_demo()
        self._status_panel.set_connected(device_name)
        self._dashboard_status_panel.set_connected(device_name)
        self._imu_panel.set_online(False)
        self._map_controls.set_sensor_state(False, False)
        self._connected_at = time.monotonic()
        self._total_bytes = 0
        self._uptime_timer.start()
        self._restart_status_timer()
        self._stack.setCurrentIndex(1)
        self._btn_devices.setVisible(True)
        if initial_status:
            self._on_status(initial_status)
        QTimer.singleShot(500, self._poll_status)

    def _on_disconnected(self) -> None:
        if self._demo_mode:
            return
        self._title.setText("Sensor Debug Console")
        self._title.setStyleSheet("color: #CFD8DC;")
        self._status_panel.set_disconnected()
        self._dashboard_status_panel.set_disconnected()
        self._uptime_timer.stop()
        self._status_timer.stop()
        self._dashboard_camera_panel.reset()
        self._dashboard_lidar_panel.reset()
        self._camera_panel.reset()
        self._lidar_panel.reset()
        self._imu_panel.reset()
        self._lidar3d_panel.reset()
        self._map_controls.update_snapshot(self._lidar3d_panel.get_snapshot())
        self._map_controls.set_sensor_state(False, False)
        self._sd_panel.reset()
        self._update_sensor_tabs(None)
        self._show_device_select()

    def _on_raw_data(self, direction: str, data: bytes) -> None:
        self._total_bytes += len(data)
        self._status_panel.update_data_total(self._total_bytes)
        self._dashboard_status_panel.update_data_total(self._total_bytes)
        if direction == "RX":
            self._status_panel.update_last_rx()
            self._dashboard_status_panel.update_last_rx()

    def _tick_uptime(self) -> None:
        if self._connected_at > 0:
            elapsed = int(time.monotonic() - self._connected_at)
            self._status_panel.update_uptime(elapsed)
            self._dashboard_status_panel.update_uptime(elapsed)

    def _on_status(self, data: bytes) -> None:
        status = parse_status(data)
        if not status:
            return
        self._current_status = status
        self._status_panel.update_status(status)
        self._dashboard_status_panel.update_status(status)
        self._imu_panel.set_online(status.imu_ok)
        self._map_controls.set_sensor_state(status.lidar_ok, status.imu_ok)
        self._update_sensor_tabs(status)
        self._sd_panel.update_status(status)
        self._sync_tab_meta(status)

    def _on_camera_frame(self, data: bytes) -> None:
        jpeg = parse_camera_frame(data)
        if jpeg:
            self._dashboard_camera_panel.update_frame(jpeg)
            self._camera_panel.update_frame(jpeg)

    def _on_lidar_frame(self, data: bytes) -> None:
        frame = parse_lidar_frame(data)
        if frame:
            self._dashboard_lidar_panel.update_frame(frame)
            self._lidar_panel.update_frame(frame)
            self._lidar3d_panel.update_lidar_frame(frame)
            self._map_controls.update_snapshot(self._lidar3d_panel.get_snapshot())

    def _on_imu_frame(self, data: bytes) -> None:
        frame = parse_imu_frame(data)
        if frame:
            self._imu_panel.update_frame(frame)
            snapshot = self._imu_panel.get_snapshot()
            _roll, _pitch, yaw = self._imu_panel.get_orientation_deg()
            self._lidar3d_panel.set_pose(snapshot["position"][0], snapshot["position"][1])
            self._lidar3d_panel.set_orientation(yaw)
            self._map_controls.update_snapshot(self._lidar3d_panel.get_snapshot())

    def _on_response(self, data: bytes) -> None:
        resp = parse_response(data)
        if not resp:
            return
        if resp.cmd_id == CMD_GET_STATUS and resp.ok and len(resp.payload) >= DeviceStatus.STRUCT_SIZE:
            status = DeviceStatus.from_bytes(resp.payload)
            self._current_status = status
            self._status_panel.update_status(status)
            self._dashboard_status_panel.update_status(status)
            self._imu_panel.set_online(status.imu_ok)
            self._map_controls.set_sensor_state(status.lidar_ok, status.imu_ok)
            self._update_sensor_tabs(status)
            self._sd_panel.update_status(status)
            self._sync_tab_meta(status)

    def _update_sensor_tabs(self, status: DeviceStatus | None) -> None:
        if self._demo_mode:
            states = {
                "dashboard": True,
                "camera": False,
                "lidar2d": True,
                "imu": True,
                "lidar3d": True,
                "sd": False,
            }
        else:
            states = {
                "dashboard": True,
                "camera": bool(status and status.camera_ok),
                "lidar2d": bool(status and status.lidar_ok),
                "imu": bool(status and status.imu_ok),
                "lidar3d": bool(status and status.lidar_ok and status.imu_ok),
                "sd": bool(status and status.sd_ok),
            }
        for key, tab_index in self._tab_indices.items():
            self._tabs.setTabEnabled(tab_index, states[key])
        if not states.get("camera"):
            self._camera_panel.reset()
        if not states.get("lidar2d"):
            self._lidar_panel.reset()
        if not states.get("imu"):
            self._imu_panel.reset()
        if not states.get("lidar3d"):
            self._lidar3d_panel.reset()
        if not states.get("sd"):
            self._sd_panel.reset()
        current_enabled = self._tabs.isTabEnabled(self._tabs.currentIndex())
        if not current_enabled:
            self._tabs.setCurrentIndex(self._tab_indices["dashboard"])

    def _sync_tab_meta(self, status: DeviceStatus | None) -> None:
        meta = {
            "dashboard": ("Dashboard", "Overall overview and quick controls"),
            "camera": ("Camera", "Enabled only when camera is healthy"),
            "lidar2d": ("LiDAR (2D)", "Raw planar scan validation"),
            "imu": ("IMU", "Orientation, acceleration, gyro, and trajectory debug"),
            "lidar3d": ("LiDAR (3D)", "2.5D room-map prototype using LiDAR + IMU"),
            "sd": ("SD Viewer", "Browse and download SD card files"),
        }
        if status:
            meta["imu"] = (
                "IMU",
                f'IMU {"online" if status.imu_ok else "offline"} | raw debug + attitude estimation',
            )
            meta["lidar3d"] = (
                "LiDAR (3D)",
                f'Fusion {"ready" if status.lidar_ok and status.imu_ok else "waiting"} | LiDAR={status.lidar_ok} IMU={status.imu_ok}',
            )
        for key, (title, tooltip) in meta.items():
            idx = self._tab_indices[key]
            self._tabs.setTabText(idx, title)
            self._tabs.setTabToolTip(idx, tooltip)

    def _edge_at(self, pos) -> str:
        margin = self._EDGE_MARGIN
        x, y = int(pos.x()), int(pos.y())
        edge = ""
        if y < margin:
            edge += "top"
        elif y > self.height() - margin:
            edge += "bottom"
        if x < margin:
            edge += "left"
        elif x > self.width() - margin:
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
        if self._resize_edge and self._drag_pos is not None:
            gp = event.globalPosition().toPoint()
            dx = gp.x() - self._drag_pos.x()
            dy = gp.y() - self._drag_pos.y()
            geo = self.geometry()
            new_geo = self.geometry()
            
            if "right" in self._resize_edge:
                new_geo.setRight(max(new_geo.left() + self.minimumWidth(), new_geo.right() + dx))
            if "bottom" in self._resize_edge:
                new_geo.setBottom(max(new_geo.top() + self.minimumHeight(), new_geo.bottom() + dy))
            if "left" in self._resize_edge:
                new_geo.setLeft(min(new_geo.right() - self.minimumWidth(), new_geo.left() + dx))
            if "top" in self._resize_edge:
                new_geo.setTop(min(new_geo.bottom() - self.minimumHeight(), new_geo.top() + dy))
                
            self.setGeometry(new_geo)
            self._drag_pos = gp
            event.accept()
            return

        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return

        edge = self._edge_at(event.position())
        if edge in self._EDGE_CURSORS:
            self.setCursor(self._EDGE_CURSORS[edge])
        else:
            self.unsetCursor()

    def mouseReleaseEvent(self, _event) -> None:
        self._drag_pos = None
        self._resize_edge = ""

    def mouseDoubleClickEvent(self, event) -> None:
        if event.position().y() < 40 and not self._edge_at(event.position()):
            if self.isMaximized():
                self.showNormal()
            else:
                self.showMaximized()

    def _show_settings_dialog(self) -> None:
        class _SettingsDialog(QDialog):
            def __init__(self, parent):
                super().__init__(parent)
                self.enter_actions: dict = {}

            def keyPressEvent(self, event):
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    focused = self.focusWidget()
                    for widget, action in self.enter_actions.items():
                        if focused is widget or (hasattr(widget, "lineEdit") and focused is widget.lineEdit()):
                            action()
                            break
                    event.accept()
                    return
                super().keyPressEvent(event)

        dialog = _SettingsDialog(self)
        dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowType.FramelessWindowHint)
        dialog.setStyleSheet(self._POPUP_STYLE)
        dialog.setFixedWidth(360)

        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        title_bar = QHBoxLayout()
        title_bar.setContentsMargins(12, 8, 8, 4)
        title_bar.addWidget(QLabel("<b>Settings</b>"))
        title_bar.addStretch()
        btn_close = QPushButton("\u2715")
        btn_close.setStyleSheet("padding: 2px 8px; font-size: 13px; color: #888; border: none;")
        btn_close.clicked.connect(dialog.accept)
        title_bar.addWidget(btn_close)
        outer.addLayout(title_bar)

        form = QVBoxLayout()
        form.setContentsMargins(12, 4, 12, 12)
        form.setSpacing(10)
        form.addWidget(QLabel("<b>Status Poll</b>"))

        poll_row = QHBoxLayout()
        poll_presets = [("OFF", 0), ("1s", 1000), ("2s", 2000), ("5s", 5000), ("10s", 10000)]
        poll_buttons: list[QPushButton] = []
        btn_base = "padding: 4px 0; font-size: 11px; border-radius: 0; border: 1px solid #444; min-width: 38px;"
        btn_on = btn_base + "background-color: #1565C0; color: white; border-color: #1976D2;"
        btn_off = btn_base + "background-color: #1a1a1a; color: #888;"

        def on_poll_select(ms: int) -> None:
            self._status_poll_interval = ms
            self._restart_status_timer()
            for button, (_, value) in zip(poll_buttons, poll_presets):
                button.setStyleSheet(btn_on if value == ms else btn_off)
            self._save_settings()

        for label, ms in poll_presets:
            button = QPushButton(label)
            button.setStyleSheet(btn_on if ms == self._status_poll_interval else btn_off)
            button.clicked.connect(lambda _, value=ms: on_poll_select(value))
            poll_buttons.append(button)
            poll_row.addWidget(button)
        form.addLayout(poll_row)

        outer.addLayout(form)
        dialog.setLayout(outer)
        dialog.exec()

    _POPUP_STYLE = "QMessageBox, QDialog { border: 1px solid #555; border-radius: 6px; padding: 8px; }"

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
        self._stack.setCurrentIndex(0)
        self._btn_devices.setVisible(False)

    def _on_server_stopped(self) -> None:
        self._status_panel.set_disconnected()
        self._status_timer.stop()
        self._uptime_timer.stop()
        self._show_device_select()

    def _save_settings(self) -> None:
        self._settings["status_poll_interval"] = self._status_poll_interval
        self._settings["server_port"] = self._server.port
        settings.save(self._settings)

    def _restart_status_timer(self) -> None:
        self._status_timer.stop()
        if self._status_poll_interval > 0 and self._conn.connected:
            self._status_timer.start(self._status_poll_interval)

    def _poll_status(self) -> None:
        if self._conn.connected and not self._demo_mode:
            self._conn.send_command(CMD_GET_STATUS)

    def _toggle_demo(self) -> None:
        if self._demo_mode:
            self._stop_demo()
        else:
            self._start_demo()

    def _start_demo(self) -> None:
        if self._conn.connected:
            self._conn.disconnect()
        self._demo_mode = True
        self._stack.setCurrentIndex(1)
        self._btn_devices.setVisible(True)
        self._status_timer.stop()
        self._uptime_timer.start()
        self._connected_at = time.monotonic()
        self._total_bytes = 0
        self._dashboard_camera_panel.reset()
        self._dashboard_lidar_panel.reset()
        self._camera_panel.reset()
        self._lidar_panel.reset()
        self._imu_panel.reset()
        self._lidar3d_panel.reset()
        self._sd_panel.reset()
        self._status_panel.set_connected("Prototype Simulator")
        self._dashboard_status_panel.set_connected("Prototype Simulator")
        self._map_controls.set_demo_running(True)
        self._map_controls.set_sensor_state(True, True)
        self._update_sensor_tabs(None)
        self._tabs.setCurrentIndex(self._tab_indices["lidar3d"])
        self._simulator.start()

    def _stop_demo(self) -> None:
        self._simulator.stop()

    def _on_demo_started(self) -> None:
        self._map_controls.set_demo_running(True)

    def _on_demo_stopped(self) -> None:
        self._demo_mode = False
        self._map_controls.set_demo_running(False)
        if not self._conn.connected:
            self._status_panel.set_disconnected()
            self._dashboard_status_panel.set_disconnected()
            self._uptime_timer.stop()
            self._dashboard_camera_panel.reset()
            self._dashboard_lidar_panel.reset()
            self._camera_panel.reset()
            self._lidar_panel.reset()
            self._imu_panel.reset()
            self._lidar3d_panel.reset()
            self._map_controls.update_snapshot(self._lidar3d_panel.get_snapshot())
            self._map_controls.set_sensor_state(False, False)
            self._update_sensor_tabs(None)
            self._show_device_select()

    def _on_demo_frame(self, status_data, imu_frame, lidar_frame) -> None:
        if not self._demo_mode:
            return
        status = DeviceStatus(
            scan_state=status_data["scan_state"],
            lidar_rpm=status_data["lidar_rpm"],
            sd_free_mb=0,
            sd_total_mb=0,
            frame_count=status_data["frame_count"],
            scan_duration_ms=status_data["scan_duration_ms"],
            battery_pct=0xFF,
            camera_streaming=status_data["camera_streaming"],
            sensor_flags=status_data["sensor_flags"],
        )
        self._current_status = status
        self._status_panel.update_status(status)
        self._dashboard_status_panel.update_status(status)
        self._update_sensor_tabs(status)
        self._imu_panel.update_frame(imu_frame)
        snapshot = self._imu_panel.get_snapshot()
        _roll, _pitch, yaw = self._imu_panel.get_orientation_deg()
        self._dashboard_lidar_panel.update_frame(lidar_frame)
        self._lidar_panel.update_frame(lidar_frame)
        self._lidar3d_panel.set_pose(snapshot["position"][0], snapshot["position"][1])
        self._lidar3d_panel.set_orientation(yaw)
        self._lidar3d_panel.update_lidar_frame(lidar_frame)
        self._map_controls.set_sensor_state(True, True)
        self._map_controls.update_snapshot(self._lidar3d_panel.get_snapshot())

    def _on_reset(self) -> None:
        self._log_panel._clear()
        self._dashboard_camera_panel.reset()
        self._dashboard_lidar_panel.reset()
        self._dashboard_status_panel.reset()
        self._camera_panel.reset()
        self._status_panel.reset()
        self._lidar_panel.reset()
        self._imu_panel.reset()
        self._lidar3d_panel.reset()
        self._map_controls.update_snapshot(self._lidar3d_panel.get_snapshot())

        self._imu_panel.reset()
        self._lidar3d_panel.reset()
        self._map_controls.update_snapshot(self._lidar3d_panel.get_snapshot())
