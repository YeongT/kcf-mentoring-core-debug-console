"""SD card browser and downloader."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFileDialog,
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from protocol import CMD_SD_DOWNLOAD, CMD_SD_LIST, parse_response, parse_sd_chunk, parse_sd_entries
from ws_server import DeviceConnection


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


class SdCardPanel(QGroupBox):
    def __init__(self, connection: DeviceConnection):
        super().__init__("SD Card Viewer")
        self._conn = connection
        self._download_dir = Path.home() / "Downloads"
        self._download_path: str | None = None
        self._download_fp = None
        self._entries_count = 0

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(5000)
        self._refresh_timer.timeout.connect(self.request_refresh)

        self._init_ui()
        self._connect_signals()

    def _init_ui(self) -> None:
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(8, 10, 8, 8)

        top = QHBoxLayout()
        top.setSpacing(6)

        self._btn_refresh = QPushButton("Refresh")
        self._btn_refresh.clicked.connect(self.request_refresh)
        top.addWidget(self._btn_refresh)

        self._auto_refresh = QCheckBox("Auto")
        self._auto_refresh.setChecked(True)
        self._auto_refresh.toggled.connect(self._on_auto_refresh_toggled)
        top.addWidget(self._auto_refresh)

        self._btn_folder = QPushButton("Folder")
        self._btn_folder.clicked.connect(self._choose_folder)
        top.addWidget(self._btn_folder)

        self._btn_download = QPushButton("Download")
        self._btn_download.clicked.connect(self._download_selected)
        self._btn_download.setEnabled(False)
        top.addWidget(self._btn_download)

        top.addStretch()
        self._status = QLabel("No SD listing loaded")
        self._status.setStyleSheet("color: #90A4AE;")
        top.addWidget(self._status)
        layout.addLayout(top)

        self._folder_label = QLabel(str(self._download_dir))
        self._folder_label.setFont(QFont("Consolas", 8))
        self._folder_label.setStyleSheet("color: #78909C;")
        layout.addWidget(self._folder_label)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["Name", "Size", "Path"])
        self._tree.itemSelectionChanged.connect(self._sync_download_state)
        self._tree.setStyleSheet("QTreeWidget { background-color: #0A0E14; border: 1px solid #202A35; }")
        layout.addWidget(self._tree, 1)
        self.setLayout(layout)

    def _connect_signals(self) -> None:
        self._conn.device_connected.connect(self._on_connected)
        self._conn.device_disconnected.connect(self._on_disconnected)
        self._conn.response_received.connect(self._on_response)
        self._conn.sd_chunk_received.connect(self._on_sd_chunk)

    def _on_connected(self, _name: str, _initial_status: bytes) -> None:
        if self._auto_refresh.isChecked():
            self._refresh_timer.start()
        self.request_refresh()

    def _on_disconnected(self) -> None:
        self._refresh_timer.stop()
        self._tree.clear()
        self._entries_count = 0
        self._status.setText("Disconnected")
        self._close_download()
        self._sync_download_state()

    def _on_auto_refresh_toggled(self, checked: bool) -> None:
        if checked and self._conn.connected:
            self._refresh_timer.start()
        else:
            self._refresh_timer.stop()

    def _choose_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Choose download folder", str(self._download_dir))
        if selected:
            self._download_dir = Path(selected)
            self._folder_label.setText(str(self._download_dir))

    def request_refresh(self) -> None:
        if self._conn.connected:
            self._status.setText("Loading SD card tree...")
            self._conn.send_command(CMD_SD_LIST)

    def _on_response(self, data: bytes) -> None:
        resp = parse_response(data)
        if not resp:
            return
        if resp.cmd_id == CMD_SD_LIST:
            if not resp.ok:
                self._status.setText("SD listing failed")
                return
            self._populate_tree(parse_sd_entries(resp.payload))
        elif resp.cmd_id == CMD_SD_DOWNLOAD:
            if not resp.ok:
                self._status.setText("Download request failed")
                self._close_download()
            else:
                self._status.setText("Download started...")

    def _populate_tree(self, entries) -> None:
        self._tree.clear()
        path_items: dict[str, QTreeWidgetItem] = {}
        for entry in entries:
            parent = self._tree.invisibleRootItem()
            current_path = ""
            parts = [part for part in entry.path.split("/") if part]
            for idx, part in enumerate(parts):
                current_path += "/" + part
                if current_path not in path_items:
                    item = QTreeWidgetItem()
                    item.setText(0, part)
                    item.setText(2, current_path)
                    item.setData(0, Qt.ItemDataRole.UserRole, current_path)
                    item.setData(0, Qt.ItemDataRole.UserRole + 1, idx == len(parts) - 1 and not entry.is_dir)
                    if idx == len(parts) - 1:
                        item.setText(1, "" if entry.is_dir else _format_size(entry.size_bytes))
                    parent.addChild(item)
                    path_items[current_path] = item
                parent = path_items[current_path]
        self._tree.expandToDepth(1)
        self._entries_count = len(entries)
        self._status.setText(f"{self._entries_count} entries loaded")
        self._sync_download_state()

    def _download_selected(self) -> None:
        item = self._tree.currentItem()
        if not item:
            return
        path = item.data(0, Qt.ItemDataRole.UserRole)
        is_file = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if not path or not is_file:
            return
        self._close_download()
        self._download_path = path
        self._download_dir.mkdir(parents=True, exist_ok=True)
        target = self._download_dir / Path(path).name
        self._download_fp = target.open("wb")
        self._status.setText(f"Downloading {Path(path).name}...")
        self._conn.send_command(CMD_SD_DOWNLOAD, path.encode("utf-8"))

    def _on_sd_chunk(self, data: bytes) -> None:
        chunk = parse_sd_chunk(data)
        if not chunk or self._download_fp is None:
            return
        self._download_fp.seek(chunk.offset)
        self._download_fp.write(chunk.data)
        received = chunk.offset + len(chunk.data)
        total = max(1, chunk.total_size)
        self._status.setText(f"Downloading... {received}/{total} bytes ({received * 100 // total}%)")
        if chunk.is_eof:
            self._status.setText(f"Download complete: {Path(self._download_path or '').name}")
            self._close_download()

    def _close_download(self) -> None:
        if self._download_fp is not None:
            self._download_fp.close()
            self._download_fp = None
        self._download_path = None

    def _sync_download_state(self) -> None:
        item = self._tree.currentItem()
        is_file = bool(item and item.data(0, Qt.ItemDataRole.UserRole + 1))
        self._btn_download.setEnabled(is_file and self._conn.connected)

    def reset(self) -> None:
        self._tree.clear()
        self._status.setText("No SD listing loaded")
        self._entries_count = 0
        self._close_download()
        self._sync_download_state()
