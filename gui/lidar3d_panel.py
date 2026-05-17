"""Fixed 2.5D LiDAR + IMU room-map panel."""

from __future__ import annotations

import math
import time
from collections import deque

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QFrame, QGroupBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from protocol import ImuFrame, LidarFrame


class ScanMatcher2D:
    def __init__(self):
        self._resolution_m = 0.08
        self._cells: set[tuple[int, int]] = set()
        self._match_cells: set[tuple[int, int]] = set()
        self._cell_limit = 60000

    def reset(self) -> None:
        self._cells.clear()
        self._match_cells.clear()

    @property
    def ready(self) -> bool:
        return len(self._cells) >= 120

    @property
    def cell_count(self) -> int:
        return len(self._cells)

    def match(
        self,
        local_points: list[tuple[float, float]],
        predicted_pose: tuple[float, float, float],
    ) -> tuple[tuple[float, float, float], float, bool]:
        if not self.ready or len(local_points) < 20:
            return predicted_pose, 0.0, False

        sample = self._sample_points(local_points, 96)
        pred_x, pred_y, pred_yaw = predicted_pose
        best_pose = predicted_pose
        best_hits = -1
        best_score = -1.0

        yaw_offsets = (-10.0, -6.0, -3.0, 0.0, 3.0, 6.0, 10.0)
        xy_offsets = (-0.18, -0.09, 0.0, 0.09, 0.18)
        for yaw_offset in yaw_offsets:
            yaw_deg = pred_yaw + yaw_offset
            yaw = math.radians(yaw_deg)
            cy, sy = math.cos(yaw), math.sin(yaw)
            rotated = [(x * cy - y * sy, x * sy + y * cy) for x, y in sample]
            for dx in xy_offsets:
                tx = pred_x + dx
                for dy in xy_offsets:
                    ty = pred_y + dy
                    exact_hits = 0
                    near_hits = 0
                    for rx, ry in rotated:
                        cell = self._cell_key(rx + tx, ry + ty)
                        if cell in self._cells:
                            exact_hits += 1
                        elif cell in self._match_cells:
                            near_hits += 1
                    penalty = 0.03 * abs(yaw_offset) + 1.2 * math.hypot(dx, dy)
                    score = exact_hits * 2.0 + near_hits * 0.25 - penalty
                    if score > best_score:
                        best_score = score
                        best_hits = exact_hits
                        best_pose = (tx, ty, yaw_deg)

        quality = max(0.0, min(1.0, best_hits / max(1, len(sample))))
        accepted = best_hits >= max(10, int(len(sample) * 0.14))
        return best_pose if accepted else predicted_pose, quality, accepted

    def add_points(self, world_points: list[tuple[float, float]]) -> None:
        if len(self._cells) > self._cell_limit:
            self.reset()
        for x_m, y_m in self._sample_points(world_points, 360):
            cell = self._cell_key(x_m, y_m)
            if cell in self._cells:
                continue
            self._cells.add(cell)
            cx, cy = cell
            for nx in (cx - 1, cx, cx + 1):
                for ny in (cy - 1, cy, cy + 1):
                    self._match_cells.add((nx, ny))

    def _cell_key(self, x_m: float, y_m: float) -> tuple[int, int]:
        return (int(round(x_m / self._resolution_m)), int(round(y_m / self._resolution_m)))

    @staticmethod
    def _sample_points(points: list[tuple[float, float]], limit: int) -> list[tuple[float, float]]:
        if len(points) <= limit:
            return points
        step = max(1, len(points) // limit)
        return points[::step][:limit]


class FixedWallCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self._points = deque(maxlen=24000)  # (forward_m, lateral_m, height_m, distance_m, stamp)
        self._wall_half_width_m = 4.0
        self._z_min_m = -1.5
        self._z_max_m = 2.5
        self._height_deadband_m = 0.08
        self._fade_reference_s = 45.0
        self.setMinimumHeight(340)
        self.setStyleSheet("background-color: #08111C; border: 1px solid #203042; border-radius: 8px;")

    def update_frame(self, world_points: list[tuple[float, float, float, float]]) -> None:
        stamp = time.monotonic()
        for point in world_points:
            self._points.append((*point, stamp))
        self.update()

    def clear_map(self) -> None:
        self._points.clear()
        self.update()

    def set_horizon(self, seconds: float) -> None:
        self._fade_reference_s = max(5.0, min(120.0, seconds))
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
        painter.drawText(rect.left(), rect.top() - 4, "FIXED 2.5D WALL MAP")

        x_center = rect.center().x()
        z_span = self._z_max_m - self._z_min_m
        half_width_px = rect.width() * 0.47

        painter.setPen(QPen(QColor("#142433"), 1))
        for meter in range(int(-self._wall_half_width_m), int(self._wall_half_width_m) + 1):
            sx = x_center + meter / self._wall_half_width_m * half_width_px
            painter.drawLine(int(sx), rect.top(), int(sx), rect.bottom())
        for z_m in (-1.0, 0.0, 1.0, 2.0):
            sy = rect.bottom() - (z_m - self._z_min_m) / z_span * rect.height()
            painter.drawLine(rect.left(), int(sy), rect.right(), int(sy))

        floor_y = rect.bottom() - (0.0 - self._z_min_m) / z_span * rect.height()
        painter.setPen(QPen(QColor("#2E4256"), 1.5))
        painter.drawLine(rect.left(), int(floor_y), rect.right(), int(floor_y))
        painter.drawLine(int(x_center), rect.top(), int(x_center), rect.bottom())

        painter.setPen(QColor("#668094"))
        painter.setFont(QFont("Consolas", 8))
        painter.drawText(rect.left() + 8, int(floor_y) - 5, "z=0")
        painter.drawText(rect.left() + 8, rect.top() + 16, "lateral x height, fixed world frame")

        if not self._points:
            painter.setPen(QColor("#5E7388"))
            painter.setFont(QFont("Consolas", 12))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Waiting for fused LiDAR + IMU points")
            painter.end()
            return

        now = time.monotonic()
        projected: dict[tuple[int, int], tuple[float, float, float, float, float]] = {}
        for forward_m, lateral_m, height_m, distance_m, stamp in self._points:
            if abs(lateral_m) > self._wall_half_width_m or height_m < self._z_min_m or height_m > self._z_max_m:
                continue
            if abs(height_m) < self._height_deadband_m:
                continue
            sx = x_center + lateral_m / self._wall_half_width_m * half_width_px
            sy = rect.bottom() - (height_m - self._z_min_m) / z_span * rect.height()
            key = (int(round(sx)), int(round(sy)))
            depth_m = abs(forward_m)
            previous = projected.get(key)
            if previous is None or depth_m < abs(previous[0]):
                projected[key] = (forward_m, sx, sy, distance_m, stamp)

        if not projected:
            painter.setPen(QColor("#5E7388"))
            painter.setFont(QFont("Consolas", 10))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Tilt or sweep the scanner to accumulate wall height")
            painter.end()
            return

        for forward_m, sx, sy, distance_m, stamp in projected.values():
            age = max(0.0, now - stamp)
            recent = max(0.0, 1.0 - age / self._fade_reference_s)
            depth = min(1.0, max(0.0, abs(forward_m) / max(distance_m, 0.001)))
            alpha = int(65 + 155 * recent)
            red = int(55 + 80 * (1.0 - depth))
            green = int(150 + 75 * recent)
            blue = int(220 + 25 * depth)
            painter.setPen(QPen(QColor(red, green, blue, alpha), 1.4))
            painter.drawLine(QPointF(sx, sy - 1.5), QPointF(sx, sy + 1.5))

        painter.end()


class TopDownMapCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self._points = deque(maxlen=24000)  # (x_m, y_m, stamp)
        self._poses = deque(maxlen=800)
        self._yaw_deg = 0.0
        self._radius_m = 5.0
        self.setMinimumHeight(180)
        self.setStyleSheet("background-color: #08111C; border: 1px solid #203042; border-radius: 8px;")

    def update_frame(self, world_points: list[tuple[float, float]], pose_xy: tuple[float, float], yaw_deg: float) -> None:
        stamp = time.monotonic()
        for x_m, y_m in world_points:
            self._points.append((x_m, y_m, stamp))
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
        painter.drawText(rect.left(), rect.top() - 4, "FIXED FLOOR PLAN")

        scale = min(rect.width(), rect.height()) / (self._radius_m * 2.25)
        cx = rect.center().x()
        cy = rect.center().y()

        painter.setPen(QPen(QColor("#142433"), 1))
        for meter in range(-int(self._radius_m), int(self._radius_m) + 1):
            painter.drawLine(rect.left(), int(cy - meter * scale), rect.right(), int(cy - meter * scale))
            painter.drawLine(int(cx + meter * scale), rect.top(), int(cx + meter * scale), rect.bottom())

        painter.setPen(QPen(QColor("#2E4256"), 1.3))
        painter.drawLine(rect.left(), int(cy), rect.right(), int(cy))
        painter.drawLine(int(cx), rect.top(), int(cx), rect.bottom())

        if not self._points and not self._poses:
            painter.setPen(QColor("#5E7388"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "No accumulated floor points yet")
            painter.end()
            return

        now = time.monotonic()
        for x_m, y_m, stamp in self._points:
            if abs(x_m) > self._radius_m or abs(y_m) > self._radius_m:
                continue
            age = max(0.0, now - stamp)
            alpha = int(70 + 130 * max(0.0, 1.0 - age / 45.0))
            sx = cx + y_m * scale
            sy = cy - x_m * scale
            painter.setPen(QPen(QColor(70, 174, 255, alpha), 1.2))
            painter.drawPoint(QPointF(sx, sy))

        if len(self._poses) > 1:
            pose_points = [QPointF(cx + y * scale, cy - x * scale) for x, y in self._poses]
            for idx, (start, end) in enumerate(zip(pose_points, pose_points[1:]), start=1):
                alpha = int(40 + 180 * idx / max(1, len(pose_points) - 1))
                painter.setPen(QPen(QColor(255, 170, 77, alpha), 1.7))
                painter.drawLine(start, end)

        if self._poses:
            x_m, y_m = self._poses[-1]
            device = QPointF(cx + y_m * scale, cy - x_m * scale)
            painter.setPen(QPen(QColor("#FF7A45"), 2))
            painter.setBrush(QColor("#FF7A45"))
            painter.drawEllipse(device, 4.0, 4.0)
            yaw_rad = math.radians(self._yaw_deg)
            heading = QPointF(device.x() + math.sin(yaw_rad) * 22, device.y() - math.cos(yaw_rad) * 22)
            painter.drawLine(device, heading)
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
            ("points", "Points"),
            ("pose", "Pose"),
            ("attitude", "Attitude"),
            ("match", "Match"),
            ("span", "Span"),
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

    def update_values(
        self,
        frames: int,
        points: int,
        attitude: tuple[float, float, float],
        pose_xy: tuple[float, float],
        match_quality: float,
        match_active: bool,
        span_m: float,
    ) -> None:
        roll_deg, pitch_deg, yaw_deg = attitude
        self._labels["frames"].setText(str(frames))
        self._labels["points"].setText(str(points))
        self._labels["pose"].setText(f"{pose_xy[0]:+.2f}, {pose_xy[1]:+.2f} m")
        self._labels["attitude"].setText(f"R {roll_deg:+.1f} / P {pitch_deg:+.1f} / Y {yaw_deg:+.1f} deg")
        state = "LOCK" if match_active else "PRED"
        self._labels["match"].setText(f"{state} {match_quality * 100:.0f}%")
        self._labels["span"].setText(f"{span_m:.1f} m fixed")


class Lidar3DPanel(QGroupBox):
    def __init__(self):
        super().__init__("LiDAR 3D / 2.5D Room Map")
        self._wall = FixedWallCanvas()
        self._topdown = TopDownMapCanvas()
        self._hud = HudStrip()
        self._caption = QLabel(
            "The map view is fixed. IMU roll/pitch levels the scan, IMU yaw predicts short motion, and LiDAR "
            "scan matching corrects yaw/xy before points are accumulated. The wall view filters near-level "
            "z=0 slices so horizontal scans do not smear into a fake wall."
        )
        self._caption.setStyleSheet("color: #8AA0B6;")
        self._caption.setWordWrap(True)

        self._frame_count = 0
        self._point_count = 0
        self._roll_deg = 0.0
        self._pitch_deg = 0.0
        self._yaw_deg = 0.0
        self._slam_yaw_deg = 0.0
        self._last_match_imu_yaw_deg: float | None = None
        self._match_quality = 0.0
        self._match_active = False
        self._pose_xy = (0.0, 0.0)
        self._attitude_history = deque(maxlen=1200)  # (timestamp_us, roll_deg, pitch_deg, yaw_deg)
        self._matcher = ScanMatcher2D()
        self._span_m = 8.0
        self._fade_reference_s = 45.0

        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.addWidget(self._wall, 5)
        layout.addWidget(self._topdown, 4)
        layout.addWidget(self._hud, 0)
        layout.addWidget(self._caption, 0)
        self.setLayout(layout)
        self._sync_hud()

    def update_imu_frame(self, frame: ImuFrame) -> None:
        if not frame.samples:
            return
        sample = frame.samples[-1]
        self._yaw_deg += sample.gyro_z_dps * 0.005
        self.set_attitude(self._roll_deg, self._pitch_deg, self._yaw_deg, sample.timestamp_us)

    def set_attitude(
        self,
        roll_deg: float,
        pitch_deg: float,
        yaw_deg: float,
        timestamp_us: int | None = None,
    ) -> None:
        self._roll_deg = roll_deg
        self._pitch_deg = pitch_deg
        self._yaw_deg = yaw_deg
        if timestamp_us is not None:
            self._attitude_history.append((timestamp_us, roll_deg, pitch_deg, yaw_deg))
        self._sync_hud()

    def set_orientation(self, yaw_deg: float) -> None:
        self.set_attitude(self._roll_deg, self._pitch_deg, yaw_deg)

    def set_pose(self, _x_m: float, _y_m: float) -> None:
        # Raw accelerometer double-integration is still too drift-prone for metric odometry.
        self._pose_xy = (0.0, 0.0)
        self._sync_hud()

    def update_lidar_frame(self, frame: LidarFrame) -> None:
        self._frame_count += 1
        floor_points: list[tuple[float, float]] = []
        wall_points: list[tuple[float, float, float, float]] = []
        roll_deg, pitch_deg, yaw_deg = self._attitude_for_timestamp(frame.timestamp_us)
        predicted_yaw = self._predict_slam_yaw(yaw_deg)
        level_points: list[tuple[float, float, float, float]] = []

        for point in frame.points:
            if point.distance_mm <= 0:
                continue
            distance_m = point.distance_mm / 1000.0
            if distance_m < 0.15 or distance_m > 8.0:
                continue
            local_angle = math.radians(point.angle_deg)
            local_x = math.cos(local_angle) * distance_m
            local_y = math.sin(local_angle) * distance_m
            level_points.append((*self._rotate_roll_pitch(local_x, local_y, 0.0, roll_deg, pitch_deg), distance_m))

        match_points = [(x_m, y_m) for x_m, y_m, _z_m, distance_m in level_points if 0.25 <= distance_m <= 6.0]
        predicted_pose = (self._pose_xy[0], self._pose_xy[1], predicted_yaw)
        matched_pose, self._match_quality, self._match_active = self._matcher.match(match_points, predicted_pose)
        self._pose_xy = (matched_pose[0], matched_pose[1])
        self._slam_yaw_deg = matched_pose[2]
        self._last_match_imu_yaw_deg = yaw_deg

        for level_x, level_y, level_z, distance_m in level_points:
            world_x, world_y = self._rotate_yaw_translate(level_x, level_y, self._slam_yaw_deg, self._pose_xy)
            world_z = level_z
            floor_points.append((world_x, world_y))
            wall_points.append((world_x, world_y, world_z, distance_m))

        self._matcher.add_points(floor_points)
        self._point_count += len(wall_points)
        self._wall.update_frame(wall_points)
        self._topdown.update_frame(floor_points, self._pose_xy, self._slam_yaw_deg)
        self._sync_hud()

    def _predict_slam_yaw(self, imu_yaw_deg: float) -> float:
        if self._last_match_imu_yaw_deg is None:
            return imu_yaw_deg
        return self._slam_yaw_deg + self._angle_delta_deg(imu_yaw_deg, self._last_match_imu_yaw_deg)

    def _attitude_for_timestamp(self, timestamp_us: int) -> tuple[float, float, float]:
        if timestamp_us <= 0 or not self._attitude_history:
            return self._roll_deg, self._pitch_deg, self._yaw_deg

        previous = None
        for item in self._attitude_history:
            if item[0] >= timestamp_us:
                if previous is None:
                    return item[1], item[2], item[3]
                span = max(1, item[0] - previous[0])
                ratio = max(0.0, min(1.0, (timestamp_us - previous[0]) / span))
                return (
                    previous[1] + (item[1] - previous[1]) * ratio,
                    previous[2] + (item[2] - previous[2]) * ratio,
                    self._interp_angle_deg(previous[3], item[3], ratio),
                )
            previous = item

        if previous is not None:
            return previous[1], previous[2], previous[3]
        return self._roll_deg, self._pitch_deg, self._yaw_deg

    @staticmethod
    def _interp_angle_deg(start_deg: float, end_deg: float, ratio: float) -> float:
        return start_deg + Lidar3DPanel._angle_delta_deg(end_deg, start_deg) * ratio

    @staticmethod
    def _angle_delta_deg(value_deg: float, baseline_deg: float) -> float:
        delta = value_deg - baseline_deg
        while delta > 180.0:
            delta -= 360.0
        while delta < -180.0:
            delta += 360.0
        return delta

    def _rotate_roll_pitch(
        self,
        x_m: float,
        y_m: float,
        z_m: float,
        roll_deg: float,
        pitch_deg: float,
    ) -> tuple[float, float, float]:
        roll = math.radians(roll_deg)
        pitch = math.radians(pitch_deg)
        cr, sr = math.cos(roll), math.sin(roll)
        cp, sp = math.cos(pitch), math.sin(pitch)

        x1 = x_m
        y1 = y_m * cr - z_m * sr
        z1 = y_m * sr + z_m * cr

        x2 = x1 * cp + z1 * sp
        y2 = y1
        z2 = -x1 * sp + z1 * cp
        return x2, y2, z2

    @staticmethod
    def _rotate_yaw_translate(
        x_m: float,
        y_m: float,
        yaw_deg: float,
        pose_xy: tuple[float, float],
    ) -> tuple[float, float]:
        yaw = math.radians(yaw_deg)
        cy, sy = math.cos(yaw), math.sin(yaw)
        return (x_m * cy - y_m * sy + pose_xy[0], x_m * sy + y_m * cy + pose_xy[1])

    def _rotate_body_to_world(
        self,
        x_m: float,
        y_m: float,
        z_m: float,
        roll_deg: float,
        pitch_deg: float,
        yaw_deg: float,
    ) -> tuple[float, float, float]:
        level_x, level_y, level_z = self._rotate_roll_pitch(x_m, y_m, z_m, roll_deg, pitch_deg)
        world_x, world_y = self._rotate_yaw_translate(level_x, level_y, yaw_deg, (0.0, 0.0))
        return world_x, world_y, level_z

    def _sync_hud(self) -> None:
        self._hud.update_values(
            self._frame_count,
            self._point_count,
            (self._roll_deg, self._pitch_deg, self._slam_yaw_deg),
            self._pose_xy,
            self._match_quality,
            self._match_active,
            self._span_m,
        )

    def reset(self) -> None:
        self._frame_count = 0
        self._point_count = 0
        self._roll_deg = 0.0
        self._pitch_deg = 0.0
        self._yaw_deg = 0.0
        self._slam_yaw_deg = 0.0
        self._last_match_imu_yaw_deg = None
        self._match_quality = 0.0
        self._match_active = False
        self._pose_xy = (0.0, 0.0)
        self._attitude_history.clear()
        self._matcher.reset()
        self._wall.clear_map()
        self._topdown.clear_map()
        self._sync_hud()

    def clear_map(self) -> None:
        self.reset()

    def set_horizon(self, seconds: float) -> None:
        self._fade_reference_s = max(5.0, min(120.0, seconds))
        self._wall.set_horizon(self._fade_reference_s)
        self._sync_hud()

    def get_snapshot(self) -> dict:
        return {
            "frames": self._frame_count,
            "point_count": self._point_count,
            "roll_deg": self._roll_deg,
            "pitch_deg": self._pitch_deg,
            "yaw_deg": self._slam_yaw_deg,
            "imu_yaw_deg": self._yaw_deg,
            "pose_xy": self._pose_xy,
            "match_quality": self._match_quality,
            "match_active": self._match_active,
            "map_cells": self._matcher.cell_count,
            "horizon_s": self._fade_reference_s,
            "span_m": self._span_m,
        }
