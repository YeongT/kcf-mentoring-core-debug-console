"""Protocol log console with hex dump."""

from datetime import datetime

from PyQt6.QtWidgets import QGroupBox, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtCore import Qt

from protocol import PREFIX_NAMES, format_hex


class LogPanel(QGroupBox):
    MAX_LINES = 1000

    def __init__(self):
        super().__init__("Protocol Log")
        self._line_count = 0
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout()

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(QFont("Consolas", 9))
        self._text.setMinimumHeight(120)
        layout.addWidget(self._text)

        btn_row = QHBoxLayout()
        btn_clear = QPushButton("Clear")
        btn_clear.clicked.connect(self._clear)
        btn_row.addStretch()
        btn_row.addWidget(btn_clear)
        layout.addLayout(btn_row)

        self.setLayout(layout)

    def _clear(self) -> None:
        self._text.clear()
        self._line_count = 0

    def log_raw(self, direction: str, data: bytes) -> None:
        if len(data) == 0:
            return

        prefix = data[0]
        prefix_name = PREFIX_NAMES.get(prefix, f"0x{prefix:02X}")
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        color = "#4FC3F7" if direction == "TX" else "#A5D6A7"
        hex_str = format_hex(data)

        html = f'<span style="color: gray;">{ts}</span> '
        html += f'<span style="color: {color}; font-weight: bold;">{direction}</span> '
        html += f'<span style="color: #FFD54F;">[{prefix_name}]</span> '
        html += f'<span style="color: #E0E0E0;">{hex_str}</span>'

        self._append_html(html)

    def log_text(self, text: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        html = f'<span style="color: gray;">{ts}</span> '
        html += f'<span style="color: #CE93D8;">{text}</span>'
        self._append_html(html)

    def _append_html(self, html: str) -> None:
        if self._line_count >= self.MAX_LINES:
            cursor = self._text.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.movePosition(QTextCursor.MoveOperation.Down, QTextCursor.MoveMode.KeepAnchor, 100)
            cursor.removeSelectedText()
            self._line_count -= 100

        self._text.append(html)
        self._line_count += 1
        self._text.moveCursor(QTextCursor.MoveOperation.End)
