"""IMU debugging panel with rich telemetry, controls, and orientation view."""

from __future__ import annotations

import math
import time
from collections import deque

from PyQt6.QtCore import QPointF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPainterPath
from PyQt6.QtWidgets import QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from protocol import ImuFrame


MOUNT_ROLL_SIGN = 1.0
MOUNT_PITCH_SIGN = 1.0
MOUNT_YAW_SIGN = 1.0
MOUNT_DESCRIPTION = "Firmware body-frame IMU mount"


def _metric_label(title: str) -> tuple[QLabel, QLabel]:
    title_label = QLabel(title)
    title_label.setStyleSheet("color: #78909C; font-size: 11px;")
    value_label = QLabel("--")
    value_label.setFont(QFont("Consolas", 10))
    value_label.setStyleSheet("color: #CFD8DC;")
    return title_label, value_label


class StatusCard(QGroupBox):
    def __init__(self, title: str):
        super().__init__(title)
        self._value = QLabel("--")
        self._value.setFont(QFont("Consolas", 10))
        self._value.setStyleSheet("color: #E3F2FD; font-weight: bold;")

        layout = QVBoxLayout()
        layout.setContentsMargins(10, 12, 10, 10)
        layout.addWidget(self._value)
        self.setLayout(layout)
        self.setStyleSheet(
            "QGroupBox { border: 1px solid #243241; border-radius: 6px; color: #90A4AE; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }"
        )

    def set_value(self, text: str, color: str = "#E3F2FD") -> None:
        self._value.setText(text)
        self._value.setStyleSheet(f"color: {color}; font-weight: bold;")


class SignalChart(QWidget):
    def __init__(self, title: str, scale: float, unit: str):
        super().__init__()
        self._title = title
        self._scale = scale
        self._unit = unit
        self._series = {"x": deque(maxlen=220), "y": deque(maxlen=220), "z": deque(maxlen=220)}
        self._colors = {"x": QColor("#4FC3F7"), "y": QColor("#81C784"), "z": QColor("#FFB74D")}
        self.setMinimumHeight(100)
        self.setStyleSheet("background-color: #0A0E14; border: 1px solid #202A35; border-radius: 6px;")

    def push(self, x: float, y: float, z: float) -> None:
        self._series["x"].append(x)
        self._series["y"].append(y)
        self._series["z"].append(z)
        self.update()

    def reset(self) -> None:
        for values in self._series.values():
            values.clear()
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(12, 12, -12, -18)
        painter.fillRect(rect, QColor("#0A0E14"))

        painter.setPen(QPen(QColor("#22303C"), 1))
        for idx in range(5):
            y = rect.top() + rect.height() * idx / 4
            painter.drawLine(rect.left(), int(y), rect.right(), int(y))

        center_y = rect.center().y()
        painter.setPen(QPen(QColor("#3C4D5E"), 1))
        painter.drawLine(rect.left(), int(center_y), rect.right(), int(center_y))

        painter.setFont(QFont("Consolas", 8))
        painter.setPen(QColor("#7F8C99"))
        painter.drawText(rect.left(), rect.top() - 2, f"{self._title} ({self._unit})")
        painter.drawText(rect.right() - 42, rect.top() + 10, f"+{self._scale:g}")
        painter.drawText(rect.right() - 34, rect.bottom(), f"-{self._scale:g}")

        width = max(1, rect.width())
        for axis in ("x", "y", "z"):
            values = list(self._series[axis])
            if len(values) < 2:
                continue
            painter.setPen(QPen(self._colors[axis], 1.6))
            points = []
            for idx, value in enumerate(values):
                x = rect.left() + idx * width / max(1, len(values) - 1)
                norm = max(-1.0, min(1.0, value / self._scale))
                y = rect.center().y() - norm * (rect.height() / 2)
                points.append(QPointF(x, y))
            for start, end in zip(points, points[1:]):
                painter.drawLine(start, end)

        legend_x = rect.left()
        for axis in ("x", "y", "z"):
            painter.setPen(self._colors[axis])
            painter.drawText(legend_x, rect.bottom() + 14, axis.upper())
            legend_x += 22
        painter.end()


class AttitudeWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._roll_deg = 0.0
        self._pitch_deg = 0.0
        self._yaw_deg = 0.0
        self.setMinimumSize(220, 220)
        self.setStyleSheet("background-color: #0A0E14; border: 1px solid #202A35; border-radius: 6px;")

    def update_orientation(self, roll_deg: float, pitch_deg: float, yaw_deg: float) -> None:
        self._roll_deg = roll_deg
        self._pitch_deg = pitch_deg
        self._yaw_deg = yaw_deg
        self.update()

    def reset(self) -> None:
        self._roll_deg = 0.0
        self._pitch_deg = 0.0
        self._yaw_deg = 0.0
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(16, 16, -16, -16)
        center = rect.center()
        radius = int(min(rect.width(), rect.height()) / 2)

        painter.fillRect(rect, QColor("#0A0E14"))
        painter.setPen(QPen(QColor("#22303C"), 1))
        painter.drawEllipse(center, radius, radius)

        painter.save()
        painter.translate(center)
        painter.rotate(-self._roll_deg)
        horizon_offset = int(max(-radius * 0.35, min(radius * 0.35, self._pitch_deg * 1.2)))
        painter.setBrush(QColor("#24476B"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(-radius, -radius * 2 + horizon_offset, radius * 2, radius * 2)
        painter.setBrush(QColor("#5F4B32"))
        painter.drawRect(-radius, horizon_offset, radius * 2, radius * 2)
        painter.setPen(QPen(QColor("#E3F2FD"), 2))
        painter.drawLine(QPointF(-radius, float(horizon_offset)), QPointF(float(radius), float(horizon_offset)))
        painter.restore()

        painter.setPen(QPen(QColor("#CFD8DC"), 2))
        painter.drawLine(QPointF(center.x() - 24, center.y()), QPointF(center.x() + 24, center.y()))
        painter.drawLine(QPointF(center.x(), center.y() - 12), QPointF(center.x(), center.y() + 12))
        painter.setFont(QFont("Consolas", 8))
        painter.setPen(QColor("#90A4AE"))
        painter.drawText(rect.left(), rect.bottom() + 2, f"Yaw {self._yaw_deg:.1f} deg")
        painter.end()


class TrajectoryCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self._trail = deque(maxlen=320)
        self._yaw_deg = 0.0
        self.setMinimumHeight(150)
        self.setStyleSheet("background-color: #0A0E14; border: 1px solid #202A35; border-radius: 6px;")

    def update_state(self, trail: deque[tuple[float, float]], yaw_deg: float) -> None:
        self._trail = deque(trail, maxlen=320)
        self._yaw_deg = yaw_deg
        self.update()

    def clear_trail(self) -> None:
        self._trail.clear()
        self.update()

    def reset(self) -> None:
        self._trail.clear()
        self._yaw_deg = 0.0
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(12, 12, -12, -12)
        painter.fillRect(rect, QColor("#0A0E14"))

        painter.setPen(QPen(QColor("#22303C"), 1))
        painter.drawRect(rect)
        painter.drawLine(rect.center().x(), rect.top(), rect.center().x(), rect.bottom())
        painter.drawLine(rect.left(), rect.center().y(), rect.right(), rect.center().y())

        painter.setPen(QColor("#7F8C99"))
        painter.setFont(QFont("Consolas", 8))
        painter.drawText(rect.left(), rect.top() - 2, "Relative XY trail / heading")
        painter.drawText(rect.right() - 10, rect.center().y() - 4, "X")
        painter.drawText(rect.center().x() + 4, rect.top() + 10, "Y")

        current = QPointF(float(rect.center().x()), float(rect.center().y()))
        if self._trail:
            max_abs = max(max(abs(x), abs(y)) for x, y in self._trail)
            scale = (min(rect.width(), rect.height()) * 0.42) / max(0.15, max_abs)
            points = []
            for x_m, y_m in self._trail:
                sx = rect.center().x() + x_m * scale
                sy = rect.center().y() - y_m * scale
                points.append(QPointF(sx, sy))
            for idx, (start, end) in enumerate(zip(points, points[1:]), start=1):
                alpha = int(40 + 215 * idx / max(1, len(points) - 1))
                painter.setPen(QPen(QColor(79, 195, 247, alpha), 1.5))
                painter.drawLine(start, end)
            current = points[-1]

        painter.setPen(QPen(QColor("#FF7043"), 2))
        painter.setBrush(QColor("#FF7043"))
        painter.drawEllipse(current, 4.0, 4.0)

        heading_len = min(rect.width(), rect.height()) * 0.18
        yaw_rad = math.radians(self._yaw_deg)
        end = QPointF(current.x() + math.sin(yaw_rad) * heading_len, current.y() - math.cos(yaw_rad) * heading_len)
        painter.drawLine(current, end)
        painter.drawEllipse(end, 3.0, 3.0)
        painter.end()


class ImuPanel(QGroupBox):
    metrics_updated = pyqtSignal(dict)
    state_changed = pyqtSignal(bool, str)

    def __init__(self):
        super().__init__("IMU Debug")
        self._accel_chart = SignalChart("Acceleration", 2.5, "g")
        self._gyro_chart = SignalChart("Angular Velocity", 360.0, "dps")
        self._trail_canvas = TrajectoryCanvas()
        self._attitude = AttitudeWidget()

        self._last_timestamp_us: int | None = None
        self._last_wall_time: float | None = None
        self._roll = 0.0
        self._pitch = 0.0
        self._yaw = 0.0
        self._level_roll = 0.0
        self._level_pitch = 0.0
        self._level_yaw = 0.0
        self._velocity = [0.0, 0.0, 0.0]
        self._position = [0.0, 0.0, 0.0]
        self._trail = deque(maxlen=320)
        self._sample_count = 0
        self._sample_rate_hz = 0.0
        self._latest_accel = (0.0, 0.0, 0.0)
        self._latest_gyro = (0.0, 0.0, 0.0)
        self._online = False
        self._sensor_available = False
        self._auto_calibrating = False
        self._calibration_needed = 160
        self._calibration_seen = 0
        self._calibration_accel_sum = [0.0, 0.0, 0.0]
        self._calibration_gyro_sum = [0.0, 0.0, 0.0]
        self._gyro_bias = (0.0, 0.0, 0.0)
        self._world_accel_bias = (0.0, 0.0, 0.0)

        self._age_timer = QTimer(self)
        self._age_timer.setInterval(250)
        self._age_timer.timeout.connect(self._refresh_age)
        self._age_timer.start()

        self._init_ui()
        self._emit_state()

    def begin_monitor_session(self) -> None:
        self.reset()
        self._sensor_available = True
        self._auto_calibrating = True
        self._calibration_seen = 0
        self._calibration_accel_sum = [0.0, 0.0, 0.0]
        self._calibration_gyro_sum = [0.0, 0.0, 0.0]
        self._gyro_bias = (0.0, 0.0, 0.0)
        self._world_accel_bias = (0.0, 0.0, 0.0)
        self._level_roll = 0.0
        self._level_pitch = 0.0
        self._level_yaw = 0.0
        self._card_state.set_value("CAL", "#4FC3F7")
        self._card_mode.set_value("Auto baseline", "#4FC3F7")
        self._emit_state()

    def is_monitoring(self) -> bool:
        return self._online or self._auto_calibrating

    def set_available(self, available: bool) -> None:
        self._sensor_available = available
        if not available:
            self._online = False
            self._auto_calibrating = False
            self._card_state.set_value("OFF", "#F44336")
            self._emit_state()
        elif not self._online and not self._auto_calibrating:
            self._card_state.set_value("WAIT", "#FF9800")

    def _init_ui(self) -> None:
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(8, 10, 8, 8)

        cards = QGridLayout()
        cards.setHorizontalSpacing(8)
        cards.setVerticalSpacing(8)
        self._card_state = StatusCard("State")
        self._card_age = StatusCard("Age")
        self._card_rate = StatusCard("Rate")
        self._card_mode = StatusCard("Solver")
        cards.addWidget(self._card_state, 0, 0)
        cards.addWidget(self._card_age, 0, 1)
        cards.addWidget(self._card_rate, 0, 2)
        cards.addWidget(self._card_mode, 0, 3)
        layout.addLayout(cards)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        top_row.addWidget(self._attitude, 3)

        values_box = QGroupBox("Live Values")
        values_layout = QGridLayout()
        values_layout.setContentsMargins(10, 14, 10, 10)
        values_layout.setHorizontalSpacing(12)
        values_layout.setVerticalSpacing(6)
        self._labels: dict[str, QLabel] = {}
        items = [
            ("Samples", "samples"),
            ("Accel", "accel"),
            ("Gyro", "gyro"),
            ("Roll", "roll"),
            ("Pitch", "pitch"),
            ("Yaw", "yaw"),
            ("Rel XY", "position"),
            ("Axes", "axes"),
        ]
        for idx, (title, key) in enumerate(items):
            title_label, value_label = _metric_label(title)
            row = idx // 2
            col = (idx % 2) * 2
            values_layout.addWidget(title_label, row, col)
            values_layout.addWidget(value_label, row, col + 1)
            self._labels[key] = value_label
        values_box.setLayout(values_layout)
        
        v_right = QVBoxLayout()
        v_right.addWidget(values_box)
        
        top_row.addLayout(v_right, 4)
        layout.addLayout(top_row)

        layout.addWidget(self._accel_chart)
        layout.addWidget(self._gyro_chart)
        layout.addWidget(self._trail_canvas, 1)
        self.setLayout(layout)

    def set_online(self, online: bool) -> None:
        self._online = online
        if online:
            if self._auto_calibrating:
                self._card_state.set_value("CAL", "#4FC3F7")
            else:
                self._card_state.set_value("LIVE", "#4CAF50")
        else:
            text = "WAIT" if self._sensor_available else "OFF"
            color = "#FF9800" if self._sensor_available else "#F44336"
            self._card_state.set_value(text, color)
            self._card_age.set_value("--", "#90A4AE")
            self._card_rate.set_value("--", "#90A4AE")
        self._emit_state()

    def update_frame(self, frame: ImuFrame) -> None:
        if not frame.samples:
            return

        self.set_online(True)
        frame_dt_total = 0.0
        frame_dt_count = 0

        for sample in frame.samples:
            self._sample_count += 1
            if self._last_timestamp_us is None:
                dt = 0.005  # Assume 200Hz if no history
            else:
                # Calculate actual dt from hardware timestamps (us -> s)
                dt_us = sample.timestamp_us - self._last_timestamp_us
                if dt_us <= 0 or dt_us > 100000:  # Gap > 100ms or negative
                    dt = 0.005
                else:
                    dt = dt_us / 1_000_000.0
            
            self._last_timestamp_us = sample.timestamp_us
            self._last_wall_time = time.monotonic()
            
            if dt > 0:
                frame_dt_total += dt
                frame_dt_count += 1

            ax, ay, az = sample.accel_x_g, sample.accel_y_g, sample.accel_z_g
            raw_gx, raw_gy, raw_gz = sample.gyro_x_dps, sample.gyro_y_dps, sample.gyro_z_dps

            if self._auto_calibrating:
                self._accumulate_calibration(ax, ay, az, raw_gx, raw_gy, raw_gz)
                continue

            gx = raw_gx - self._gyro_bias[0]
            gy = raw_gy - self._gyro_bias[1]
            gz = raw_gz - self._gyro_bias[2]
            if abs(gx) < 0.08:
                gx = 0.0
            if abs(gy) < 0.08:
                gy = 0.0
            if abs(gz) < 0.08:
                gz = 0.0
            self._latest_accel = (ax, ay, az)
            self._latest_gyro = (gx, gy, gz)

            self._accel_chart.push(ax, ay, az)
            self._gyro_chart.push(gx, gy, gz)

            # --- Attitude Estimation (Complementary Filter) ---
            # Accelerometer angles (Pitch/Roll)
            roll_acc = math.atan2(ay, az if abs(az) > 1e-6 else 1e-6)
            pitch_acc = math.atan2(-ax, math.sqrt(ay * ay + az * az))
            
            # Filter constant: larger = trust gyro more (smooth but drifts), smaller = trust accel more (noisy but stable)
            alpha = 0.96 
            if dt > 0:
                self._roll = alpha * (self._roll + math.radians(gx) * dt) + (1 - alpha) * roll_acc
                self._pitch = alpha * (self._pitch + math.radians(gy) * dt) + (1 - alpha) * pitch_acc
                self._yaw += math.radians(gz) * dt

                # --- Relative Motion Cue ---
                cr, sr = math.cos(self._roll), math.sin(self._roll)
                cp, sp = math.cos(self._pitch), math.sin(self._pitch)
                cy, sy = math.cos(self._yaw), math.sin(self._yaw)
                
                # Rotation matrix (World to Body) - simplified ZYX
                rot = (
                    (cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr),
                    (sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr),
                    (-sp, cp * sr, cp * cr),
                )

                # Transform body accel to world accel (remove gravity)
                world_ax = rot[0][0] * ax + rot[0][1] * ay + rot[0][2] * az
                world_ay = rot[1][0] * ax + rot[1][1] * ay + rot[1][2] * az
                world_az = rot[2][0] * ax + rot[2][1] * ay + rot[2][2] * az - 1.0
                world_ax -= self._world_accel_bias[0]
                world_ay -= self._world_accel_bias[1]
                world_az -= self._world_accel_bias[2]

                # This is intentionally not metric odometry. It is a short-term
                # motion cue for "which way did it move relative to start?"
                acc_threshold = 0.035
                if abs(world_ax) < acc_threshold:
                    world_ax = 0.0
                if abs(world_ay) < acc_threshold:
                    world_ay = 0.0

                gyro_mag = math.sqrt(gx * gx + gy * gy + gz * gz)
                stationary = world_ax == 0.0 and world_ay == 0.0 and gyro_mag < 1.5
                velocity_decay = math.pow(0.72 if stationary else 0.90, dt * 100)
                position_decay = math.pow(0.997 if stationary else 0.999, dt * 100)
                motion_gain = 1.4
                for idx, world_acc in enumerate((world_ax, world_ay)):
                    self._velocity[idx] = (self._velocity[idx] + world_acc * motion_gain * dt) * velocity_decay
                    self._position[idx] = (self._position[idx] + self._velocity[idx] * dt) * position_decay
                    self._position[idx] = max(-5.0, min(5.0, self._position[idx]))
                self._velocity[2] = 0.0
                self._position[2] = 0.0

                self._trail.append((self._position[0], self._position[1]))

        if frame_dt_count > 0:
            self._sample_rate_hz = 1.0 / (frame_dt_total / frame_dt_count)

        if self._auto_calibrating:
            self._card_rate.set_value(f"{self._sample_rate_hz:.1f} Hz", "#81C784")
            self._card_age.set_value("0 ms", "#4CAF50")
            self._labels["samples"].setText(str(self._sample_count))
            self._labels["axes"].setText("Building baseline")
            self.metrics_updated.emit(self.get_snapshot())
            return

        roll_deg, pitch_deg, yaw_deg = self.get_orientation_deg()
        self._attitude.update_orientation(roll_deg, pitch_deg, yaw_deg)
        self._card_rate.set_value(f"{self._sample_rate_hz:.1f} Hz", "#81C784")
        self._card_mode.set_value("Complementary + mount", "#4FC3F7")
        self._refresh_age()

        accel_mag = math.sqrt(sum(v * v for v in self._latest_accel))
        gyro_mag = math.sqrt(sum(v * v for v in self._latest_gyro))
        self._labels["samples"].setText(str(self._sample_count))
        self._labels["accel"].setText(f"{accel_mag:.2f} g")
        self._labels["gyro"].setText(f"{gyro_mag:.1f} dps")
        self._labels["roll"].setText(f"{roll_deg:.1f} deg")
        self._labels["pitch"].setText(f"{pitch_deg:.1f} deg")
        self._labels["yaw"].setText(f"{yaw_deg:.1f} deg")
        self._labels["position"].setText(f"{self._position[0]:+.2f}, {self._position[1]:+.2f} rel")
        self._labels["axes"].setText(
            f"{MOUNT_DESCRIPTION} | "
            f"A {self._latest_accel[0]:+.2f} {self._latest_accel[1]:+.2f} {self._latest_accel[2]:+.2f} | "
            f"G {self._latest_gyro[0]:+.1f} {self._latest_gyro[1]:+.1f} {self._latest_gyro[2]:+.1f}"
        )
        self._trail_canvas.update_state(self._trail, yaw_deg)
        self.metrics_updated.emit(self.get_snapshot())

    def _accumulate_calibration(self, ax: float, ay: float, az: float, gx: float, gy: float, gz: float) -> None:
        self._calibration_accel_sum[0] += ax
        self._calibration_accel_sum[1] += ay
        self._calibration_accel_sum[2] += az
        self._calibration_gyro_sum[0] += gx
        self._calibration_gyro_sum[1] += gy
        self._calibration_gyro_sum[2] += gz
        self._calibration_seen += 1

        if self._calibration_seen < self._calibration_needed:
            return

        inv = 1.0 / self._calibration_seen
        avg_ax, avg_ay, avg_az = (v * inv for v in self._calibration_accel_sum)
        self._gyro_bias = tuple(v * inv for v in self._calibration_gyro_sum)

        self._roll = math.atan2(avg_ay, avg_az if abs(avg_az) > 1e-6 else 1e-6)
        self._pitch = math.atan2(-avg_ax, math.sqrt(avg_ay * avg_ay + avg_az * avg_az))
        self._yaw = 0.0
        self._level_roll = self._roll
        self._level_pitch = self._pitch
        self._level_yaw = self._yaw
        self._velocity = [0.0, 0.0, 0.0]
        self._position = [0.0, 0.0, 0.0]
        self._trail.clear()
        self._trail.append((0.0, 0.0))
        self._last_timestamp_us = None

        cr, sr = math.cos(self._roll), math.sin(self._roll)
        cp, sp = math.cos(self._pitch), math.sin(self._pitch)
        rot = (
            (cp, sp * sr, sp * cr),
            (0.0, cr, -sr),
            (-sp, cp * sr, cp * cr),
        )
        self._world_accel_bias = (
            rot[0][0] * avg_ax + rot[0][1] * avg_ay + rot[0][2] * avg_az,
            rot[1][0] * avg_ax + rot[1][1] * avg_ay + rot[1][2] * avg_az,
            rot[2][0] * avg_ax + rot[2][1] * avg_ay + rot[2][2] * avg_az - 1.0,
        )

        self._auto_calibrating = False
        self.set_online(True)
        self._card_mode.set_value("Baseline locked", "#4FC3F7")
        self._attitude.update_orientation(*self.get_orientation_deg())
        self._trail_canvas.update_state(self._trail, 0.0)

    def _refresh_age(self) -> None:
        if self._last_wall_time is None:
            self._card_age.set_value("--", "#90A4AE")
            return
        age_ms = int((time.monotonic() - self._last_wall_time) * 1000)
        color = "#4CAF50" if age_ms < 200 else "#FF9800" if age_ms < 1000 else "#F44336"
        self._card_age.set_value(f"{age_ms} ms", color)
        if self._online and age_ms > 1500:
            self._online = False
            self._card_state.set_value("WAIT", "#FF9800")
            self._emit_state()

    def _emit_state(self) -> None:
        if self._auto_calibrating:
            message = "IMU baseline calibration"
        elif self._online:
            message = "IMU streaming active"
        else:
            message = "Waiting for preview packets..."
        self.state_changed.emit(self._online, message)

    def zero_yaw(self) -> None:
        self._level_yaw = self._yaw
        self._velocity[2] = 0.0
        self._attitude.update_orientation(*self.get_orientation_deg())
        self._trail_canvas.update_state(self._trail, 0.0)
        self.metrics_updated.emit(self.get_snapshot())

    def clear_trail(self) -> None:
        self._trail.clear()
        self._position = [0.0, 0.0, 0.0]
        self._velocity = [0.0, 0.0, 0.0]
        self._trail_canvas.clear_trail()
        self._labels["position"].setText("+0.00, +0.00 rel")
        self.metrics_updated.emit(self.get_snapshot())

    def reset_filter(self) -> None:
        self._level_roll = self._roll
        self._level_pitch = self._pitch
        self._level_yaw = self._yaw
        self._velocity = [0.0, 0.0, 0.0]
        self._position = [0.0, 0.0, 0.0]
        self._trail.clear()
        self._attitude.update_orientation(0.0, 0.0, 0.0)
        self._trail_canvas.reset()
        self._labels["position"].setText("+0.00, +0.00 rel")
        self.metrics_updated.emit(self.get_snapshot())

    def get_orientation_deg(self) -> tuple[float, float, float]:
        return (
            self._angle_delta_deg(self._roll, self._level_roll) * MOUNT_ROLL_SIGN,
            self._angle_delta_deg(self._pitch, self._level_pitch) * MOUNT_PITCH_SIGN,
            self._angle_delta_deg(self._yaw, self._level_yaw) * MOUNT_YAW_SIGN,
        )

    @staticmethod
    def _angle_delta_deg(value_rad: float, baseline_rad: float) -> float:
        deg = math.degrees(value_rad - baseline_rad)
        while deg > 180.0:
            deg -= 360.0
        while deg < -180.0:
            deg += 360.0
        return deg

    def get_snapshot(self) -> dict:
        roll_deg, pitch_deg, yaw_deg = self.get_orientation_deg()
        age_ms = None if self._last_wall_time is None else int((time.monotonic() - self._last_wall_time) * 1000)
        return {
            "online": self._online,
            "samples": self._sample_count,
            "sample_rate_hz": self._sample_rate_hz,
            "age_ms": age_ms,
            "timestamp_us": self._last_timestamp_us,
            "roll_deg": roll_deg,
            "pitch_deg": pitch_deg,
            "yaw_deg": yaw_deg,
            "accel": self._latest_accel,
            "gyro": self._latest_gyro,
            "position": tuple(self._position),
        }

    def reset(self) -> None:
        self._last_timestamp_us = None
        self._last_wall_time = None
        self._roll = 0.0
        self._pitch = 0.0
        self._yaw = 0.0
        self._level_roll = 0.0
        self._level_pitch = 0.0
        self._level_yaw = 0.0
        self._velocity = [0.0, 0.0, 0.0]
        self._position = [0.0, 0.0, 0.0]
        self._trail.clear()
        self._sample_count = 0
        self._sample_rate_hz = 0.0
        self._latest_accel = (0.0, 0.0, 0.0)
        self._latest_gyro = (0.0, 0.0, 0.0)
        self._online = False
        self._auto_calibrating = False
        self._calibration_seen = 0
        self._calibration_accel_sum = [0.0, 0.0, 0.0]
        self._calibration_gyro_sum = [0.0, 0.0, 0.0]
        self._gyro_bias = (0.0, 0.0, 0.0)
        self._world_accel_bias = (0.0, 0.0, 0.0)
        for label in self._labels.values():
            label.setText("--")
        text = "WAIT" if self._sensor_available else "OFF"
        color = "#FF9800" if self._sensor_available else "#F44336"
        self._card_state.set_value(text, color)
        self._card_age.set_value("--", "#90A4AE")
        self._card_rate.set_value("--", "#90A4AE")
        self._card_mode.set_value("Idle", "#90A4AE")
        self._attitude.reset()
        self._accel_chart.reset()
        self._gyro_chart.reset()
        self._trail_canvas.reset()
        self.metrics_updated.emit(self.get_snapshot())
        self._emit_state()
