"""Camera panel displaying JPEG frames from the device."""

import time

from PyQt6.QtWidgets import QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QImage, QFont, QTransform


class CameraPanel(QGroupBox):
    def __init__(self):
        super().__init__("Camera Preview")
        self._frame_count = 0
        self._last_fps_time = time.monotonic()
        self._fps_frames = 0
        self._fps = 0.0
        self._flip_h = False
        self._flip_v = False
        self._rotation = 0
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout()
        layout.setSpacing(4)

        self._image_label = QLabel("No camera feed")
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setMinimumSize(320, 240)
        self._image_label.setStyleSheet("background-color: #1a1a1a; color: #666; border: 1px solid #333;")
        layout.addWidget(self._image_label, 1)

        # Bottom bar: transform controls (left) + stats (right)
        bar = QHBoxLayout()
        bar.setSpacing(4)
        bar.setContentsMargins(0, 2, 0, 0)

        btn_style = "padding: 2px 8px; font-size: 11px;"

        self._btn_flip_h = QPushButton("\u2194 H")
        self._btn_flip_h.setCheckable(True)
        self._btn_flip_h.setStyleSheet(btn_style)
        self._btn_flip_h.setToolTip("Horizontal flip")
        self._btn_flip_h.clicked.connect(self._on_flip_h)
        bar.addWidget(self._btn_flip_h)

        self._btn_flip_v = QPushButton("\u2195 V")
        self._btn_flip_v.setCheckable(True)
        self._btn_flip_v.setStyleSheet(btn_style)
        self._btn_flip_v.setToolTip("Vertical flip")
        self._btn_flip_v.clicked.connect(self._on_flip_v)
        bar.addWidget(self._btn_flip_v)

        self._btn_rotate = QPushButton("\u21bb 0\u00b0")
        self._btn_rotate.setStyleSheet(btn_style)
        self._btn_rotate.setToolTip("Rotate 90\u00b0 clockwise")
        self._btn_rotate.clicked.connect(self._on_rotate)
        bar.addWidget(self._btn_rotate)

        bar.addStretch()

        self._info_label = QLabel("FPS: -- | Size: -- | Frames: 0")
        self._info_label.setFont(QFont("Consolas", 8))
        self._info_label.setStyleSheet("color: #666;")
        bar.addWidget(self._info_label)

        layout.addLayout(bar)
        self.setLayout(layout)

    _STYLE_OFF = "padding: 2px 8px; font-size: 11px;"
    _STYLE_ON = "padding: 2px 8px; font-size: 11px; background-color: #1565C0; color: white; border: 1px solid #1976D2;"

    def _on_flip_h(self) -> None:
        self._flip_h = self._btn_flip_h.isChecked()
        self._btn_flip_h.setStyleSheet(self._STYLE_ON if self._flip_h else self._STYLE_OFF)

    def _on_flip_v(self) -> None:
        self._flip_v = self._btn_flip_v.isChecked()
        self._btn_flip_v.setStyleSheet(self._STYLE_ON if self._flip_v else self._STYLE_OFF)

    def _on_rotate(self) -> None:
        self._rotation = (self._rotation + 90) % 360
        self._btn_rotate.setText(f"\u21bb {self._rotation}\u00b0")

    def update_frame(self, jpeg_data: bytes) -> None:
        image = QImage()
        if not image.loadFromData(jpeg_data, "JPEG"):
            return

        # Apply transformations
        transform = QTransform()
        if self._flip_h:
            transform.scale(-1, 1)
        if self._flip_v:
            transform.scale(1, -1)
        if self._rotation:
            transform.rotate(self._rotation)
        if self._flip_h or self._flip_v or self._rotation:
            image = image.transformed(transform)

        pixmap = QPixmap.fromImage(image)
        scaled = pixmap.scaled(
            self._image_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)

        self._frame_count += 1
        self._fps_frames += 1

        now = time.monotonic()
        elapsed = now - self._last_fps_time
        if elapsed >= 1.0:
            self._fps = self._fps_frames / elapsed
            self._fps_frames = 0
            self._last_fps_time = now

        size_kb = len(jpeg_data) / 1024
        self._info_label.setText(
            f"FPS: {self._fps:.1f} | Size: {size_kb:.1f} KB | Frames: {self._frame_count}"
        )

    def reset(self) -> None:
        self._frame_count = 0
        self._fps_frames = 0
        self._fps = 0.0
        self._last_fps_time = time.monotonic()
        self._image_label.clear()
        self._image_label.setText("No camera feed")
        self._info_label.setText("FPS: -- | Size: -- | Frames: 0")
