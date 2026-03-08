"""LiDAR 2D visualization panel using QPainter."""

import math

from PyQt6.QtWidgets import QGroupBox, QVBoxLayout, QWidget, QLabel
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QPainter, QPen, QColor, QBrush, QFont

from protocol import LidarFrame


class LidarCanvas(QWidget):
    """Custom widget for drawing LiDAR point cloud in polar view."""

    def __init__(self):
        super().__init__()
        self._points: list[tuple[float, float]] = []  # (x, y) in mm
        self._max_distance = 3000  # mm, auto-scaled
        self.setMinimumSize(300, 300)
        self.setStyleSheet("background-color: #0a0a0a;")

    def update_frame(self, frame: LidarFrame) -> None:
        points = []
        max_dist = 0
        for pt in frame.points:
            if pt.distance_mm == 0:
                continue
            angle_rad = math.radians(pt.angle_deg)
            x = pt.distance_mm * math.cos(angle_rad)
            y = pt.distance_mm * math.sin(angle_rad)
            points.append((x, y))
            if pt.distance_mm > max_dist:
                max_dist = pt.distance_mm

        self._points = points
        if max_dist > 0:
            self._max_distance = max_dist * 1.15  # 15% margin
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        cx = w / 2
        cy = h / 2
        radius = min(cx, cy) - 10
        scale = radius / self._max_distance if self._max_distance > 0 else 1

        # Draw grid circles
        grid_pen = QPen(QColor(40, 40, 40))
        painter.setPen(grid_pen)
        ring_count = 4
        for i in range(1, ring_count + 1):
            r = radius * i / ring_count
            painter.drawEllipse(QPointF(cx, cy), r, r)

        # Draw crosshair
        painter.drawLine(int(cx - radius), int(cy), int(cx + radius), int(cy))
        painter.drawLine(int(cx), int(cy - radius), int(cx), int(cy + radius))

        # Draw distance labels
        label_pen = QPen(QColor(80, 80, 80))
        painter.setPen(label_pen)
        painter.setFont(QFont("Consolas", 8))
        for i in range(1, ring_count + 1):
            dist = int(self._max_distance * i / ring_count)
            r = radius * i / ring_count
            label = f"{dist / 1000:.1f}m" if dist >= 1000 else f"{dist}mm"
            painter.drawText(int(cx + 4), int(cy - r + 12), label)

        # Draw points
        point_pen = QPen(QColor(0, 255, 100))
        point_brush = QBrush(QColor(0, 255, 100))
        painter.setPen(point_pen)
        painter.setBrush(point_brush)

        for x_mm, y_mm in self._points:
            sx = cx + x_mm * scale
            sy = cy - y_mm * scale  # Y inverted for screen coords
            painter.drawEllipse(QPointF(sx, sy), 2, 2)

        # Draw center (device position)
        painter.setPen(QPen(QColor(255, 100, 100)))
        painter.setBrush(QBrush(QColor(255, 100, 100)))
        painter.drawEllipse(QPointF(cx, cy), 4, 4)

        painter.end()


class LidarPanel(QGroupBox):
    def __init__(self):
        super().__init__("LiDAR Preview")
        self._frame_count = 0
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout()

        self._canvas = LidarCanvas()
        layout.addWidget(self._canvas, 1)

        self._info_label = QLabel("Points: -- | Frames: 0")
        self._info_label.setFont(QFont("Consolas", 9))
        self._info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._info_label)

        self.setLayout(layout)

    def update_frame(self, frame: LidarFrame) -> None:
        self._canvas.update_frame(frame)
        self._frame_count += 1
        valid_pts = sum(1 for p in frame.points if p.distance_mm > 0)
        self._info_label.setText(f"Points: {valid_pts} | Frames: {self._frame_count}")

    def reset(self) -> None:
        self._canvas._points = []
        self._canvas.update()
        self._frame_count = 0
        self._info_label.setText("Points: -- | Frames: 0")
