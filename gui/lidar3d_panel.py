"""2.5D room-map panel with perspective and top-down accumulated views."""

from __future__ import annotations

import math
import time
from collections import deque

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QFrame, QGroupBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from protocol import ImuFrame, LidarFrame


def _panel_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setFont(QFont("Consolas", 9))
    label.setStyleSheet("color: #90A4AE; letter-spacing: 1px;")
    return label


class PerspectiveRoomCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self._history = deque(maxlen=90)  # (stamp, world_points, pose_xy, yaw_deg)
        self.setMinimumHeight(340)
        self.setStyleSheet("background-color: #08111C; border: 1px solid #203042; border-radius: 8px;")

    def update_frame(self, world_points: list[tuple[float, float]], pose_xy: tuple[float, float], yaw_deg: float) -> None:
        self._history.append((time.monotonic(), world_points, pose_xy, yaw_deg))
        self.update()

    def clear_map(self) -> None:
        self._history.clear()
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(14, 18, -14, -14)
        painter.fillRect(rect, QColor("#08111C"))

        painter.setPen(QPen(QColor("#26384A"), 1))
        painter.drawRoundedRect(rect, 8, 8)
        painter.setPen(QColor("#8AA0B6"))
        painter.setFont(QFont("Consolas", 8))
        painter.drawText(rect.left(), rect.top() - 4, "PERSPECTIVE ROOM RECONSTRUCTION")

        center_x = rect.center().x()
        horizon_y = rect.top() + rect.height() * 0.28
        ground_y = rect.bottom() - 26
        painter.setPen(QPen(QColor("#142433"), 1))
        for idx in range(6):
            y = horizon_y + (ground_y - horizon_y) * idx / 5
            painter.drawLine(rect.left(), int(y), rect.right(), int(y))
        for idx in range(-4, 5):
            x = center_x + rect.width() * idx / 10
            painter.drawLine(int(x), int(horizon_y), int(x), rect.bottom())
        painter.setPen(QPen(QColor("#2E4256"), 1))
        painter.drawLine(rect.left(), int(ground_y), rect.right(), int(ground_y))
        painter.drawLine(int(center_x), rect.top(), int(center_x), rect.bottom())

        if not self._history:
            painter.setPen(QColor("#5E7388"))
            painter.setFont(QFont("Consolas", 12))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Waiting for LiDAR + IMU fusion data")
            painter.end()
            return

        now = time.monotonic()
        for stamp, points, pose_xy, yaw_deg in self._history:
            age = now - stamp
            if age > 8.0:
                continue
            fade = max(0.1, 1.0 - age / 8.0)
            scale = 0.80 + age * 0.25
            for x_m, y_m in points:
                depth = max(0.6, y_m + 3.5)
                sx = center_x + (x_m - pose_xy[0]) / scale * (rect.width() * 0.18)
                sy = ground_y - depth / scale * (rect.height() * 0.12) - age * 12.0
                painter.setPen(QPen(QColor(53, 163, 255, int(220 * fade)), 1.5))
                painter.drawPoint(QPointF(sx, sy))

            device_x = center_x
            device_y = ground_y - age * 12.0
            painter.setPen(QPen(QColor("#FF7A45"), 2))
            painter.setBrush(QColor("#FF7A45"))
            painter.drawEllipse(QPointF(device_x, device_y), 3.5, 3.5)
            heading_len = rect.width() * 0.06
            yaw_rad = math.radians(yaw_deg)
            end = QPointF(device_x + math.cos(yaw_rad) * heading_len, device_y - math.sin(yaw_rad) * heading_len * 0.55)
            painter.drawLine(QPointF(device_x, device_y), end)

        painter.end()


class TopDownMapCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self._points = deque(maxlen=12000)
        self._poses = deque(maxlen=500)
        self._yaw_deg = 0.0
        self.setMinimumHeight(190)
        self.setStyleSheet("background-color: #08111C; border: 1px solid #203042; border-radius: 8px;")

    def update_frame(self, world_points: list[tuple[float, float]], pose_xy: tuple[float, float], yaw_deg: float) -> None:
        for point in world_points:
            self._points.append(point)
        self._poses.append(pose_xy)
        self._yaw_deg = yaw_deg
        self.update()

    def clear_map(self) -> None:
        self._points.clear()
        self._poses.clear()
        self._yaw_deg = 0.0
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(14, 18, -14, -14)
        painter.fillRect(rect, QColor("#08111C"))
        painter.setPen(QPen(QColor("#26384A"), 1))
        painter.drawRoundedRect(rect, 8, 8)
        painter.setPen(QColor("#8AA0B6"))
        painter.setFont(QFont("Consolas", 8))
        painter.drawText(rect.left(), rect.top() - 4, "TOP VIEW ACCUMULATION")

        if not self._points and not self._poses:
            painter.setPen(QColor("#5E7388"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "No accumulated room map yet")
            painter.end()
            return

        all_x = [p[0] for p in self._points] + [p[0] for p in self._poses]
        all_y = [p[1] for p in self._points] + [p[1] for p in self._poses]
        min_x, max_x = min(all_x, default=-2.0), max(all_x, default=2.0)
        min_y, max_y = min(all_y, default=-2.0), max(all_y, default=2.0)
        span = max(max_x - min_x, max_y - min_y, 2.0)
        scale = min(rect.width(), rect.height()) / (span * 1.25)
        cx = rect.center().x() - (min_x + max_x) * 0.5 * scale
        cy = rect.center().y() + (min_y + max_y) * 0.5 * scale

        painter.setPen(QPen(QColor("#142433"), 1))
        for idx in range(-5, 6):
            painter.drawLine(rect.left(), int(cy + idx * scale), rect.right(), int(cy + idx * scale))
            painter.drawLine(int(cx + idx * scale), rect.top(), int(cx + idx * scale), rect.bottom())

        for x_m, y_m in self._points:
            sx = cx + x_m * scale
            sy = cy - y_m * scale
            painter.setPen(QPen(QColor(70, 174, 255, 70), 1.2))
            painter.drawPoint(QPointF(sx, sy))

        if len(self._poses) > 1:
            pose_points = [QPointF(cx + x * scale, cy - y * scale) for x, y in self._poses]
            for idx, (start, end) in enumerate(zip(pose_points, pose_points[1:]), start=1):
                alpha = int(40 + 180 * idx / max(1, len(pose_points) - 1))
                painter.setPen(QPen(QColor(255, 170, 77, alpha), 1.7))
                painter.drawLine(start, end)

        if self._poses:
            x_m, y_m = self._poses[-1]
            device = QPointF(cx + x_m * scale, cy - y_m * scale)
            painter.setPen(QPen(QColor("#FF7A45"), 2))
            painter.setBrush(QColor("#FF7A45"))
            painter.drawEllipse(device, 4, 4)
            yaw_rad = math.radians(self._yaw_deg)
            end = QPointF(device.x() + math.cos(yaw_rad) * 20, device.y() - math.sin(yaw_rad) * 20)
            painter.drawLine(device, end)
        painter.end()


class HudStrip(QFrame):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("background-color: #0D1622; border: 1px solid #203042; border-radius: 8px;")
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)
        self._labels: dict[str, QLabel] = {}
        for key, title in (
            ("frames", "Frames"),
            ("yaw", "Yaw"),
            ("pose", "Pose"),
            ("window", "Window"),
        ):
            title_label = QLabel(title)
            title_label.setStyleSheet("color: #7D93A8;")
            value_label = QLabel("--")
            value_label.setFont(QFont("Consolas", 9))
            value_label.setStyleSheet("color: #E3F2FD; font-weight: bold;")
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(title_label)
            col.addWidget(value_label)
            wrapper = QWidget()
            wrapper.setLayout(col)
            layout.addWidget(wrapper)
            self._labels[key] = value_label
        layout.addStretch()
        self.setLayout(layout)

    def update_values(self, frames: int, yaw_deg: float, pose_xy: tuple[float, float], horizon_s: float) -> None:
        self._labels["frames"].setText(str(frames))
        self._labels["yaw"].setText(f"{yaw_deg:.1f} deg")
        self._labels["pose"].setText(f"{pose_xy[0]:+.2f}, {pose_xy[1]:+.2f} m")
        self._labels["window"].setText(f"{horizon_s:.1f} s")


class Lidar3DPanel(QGroupBox):
    def __init__(self):
        super().__init__("LiDAR 3D / 2.5D Room Map")
        self._perspective = PerspectiveRoomCanvas()
        self._topdown = TopDownMapCanvas()
        self._hud = HudStrip()
        self._caption = QLabel("LiDAR points are rotated by IMU yaw and accumulated into a room-like debugging view.")
        self._caption.setStyleSheet("color: #8AA0B6;")
        self._caption.setWordWrap(True)

        self._frame_count = 0
        self._yaw_deg = 0.0
        self._pose_xy = (0.0, 0.0)
        self._horizon_s = 8.0

        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.addWidget(self._perspective, 5)
        layout.addWidget(self._topdown, 3)
        layout.addWidget(self._hud, 0)
        layout.addWidget(self._caption, 0)
        self.setLayout(layout)
        self._sync_hud()

    def update_imu_frame(self, frame: ImuFrame) -> None:
        if not frame.samples:
            return
        sample = frame.samples[-1]
        self._yaw_deg += sample.gyro_z_dps * 0.005
        self._sync_hud()

    def set_orientation(self, yaw_deg: float) -> None:
        self._yaw_deg = yaw_deg
        self._sync_hud()

    def set_pose(self, x_m: float, y_m: float) -> None:
        self._pose_xy = (x_m, y_m)
        self._sync_hud()

    def update_lidar_frame(self, frame: LidarFrame) -> None:
        self._frame_count += 1
        world_points = []
        yaw_rad = math.radians(self._yaw_deg)
        cy = math.cos(yaw_rad)
        sy = math.sin(yaw_rad)
        for point in frame.points:
            if point.distance_mm <= 0:
                continue
            local_angle = math.radians(point.angle_deg)
            local_x = math.cos(local_angle) * (point.distance_mm / 1000.0)
            local_y = math.sin(local_angle) * (point.distance_mm / 1000.0)
            world_x = self._pose_xy[0] + local_x * cy - local_y * sy
            world_y = self._pose_xy[1] + local_x * sy + local_y * cy
            world_points.append((world_x, world_y))

        self._perspective.update_frame(world_points, self._pose_xy, self._yaw_deg)
        self._topdown.update_frame(world_points, self._pose_xy, self._yaw_deg)
        self._sync_hud()

    def _sync_hud(self) -> None:
        self._hud.update_values(self._frame_count, self._yaw_deg, self._pose_xy, self._horizon_s)

    def reset(self) -> None:
        self._frame_count = 0
        self._yaw_deg = 0.0
        self._pose_xy = (0.0, 0.0)
        self._perspective.clear_map()
        self._topdown.clear_map()
        self._sync_hud()

    def clear_map(self) -> None:
        self.reset()

    def get_snapshot(self) -> dict:
        return {
            "frames": self._frame_count,
            "yaw_deg": self._yaw_deg,
            "pose_xy": self._pose_xy,
            "horizon_s": self._horizon_s,
        }
