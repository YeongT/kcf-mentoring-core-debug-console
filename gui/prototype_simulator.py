"""Synthetic IMU + LiDAR prototype simulator for 2.5D room mapping."""

from __future__ import annotations

import math
import time

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from protocol import ImuFrame, ImuSample, LidarFrame, LidarPoint


class PrototypeSimulator(QObject):
    frame_ready = pyqtSignal(object, object, object)  # status, imu_frame, lidar_frame
    started = pyqtSignal()
    stopped = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)
        self._start_time = 0.0
        self._last_time = 0.0
        self._last_yaw = 0.0
        self._frame_count = 0
        self._room_segments = [
            ((0.0, 0.0), (6.0, 0.0)),
            ((6.0, 0.0), (6.0, 4.5)),
            ((6.0, 4.5), (4.4, 4.5)),
            ((4.4, 4.5), (4.4, 3.0)),
            ((4.4, 3.0), (2.6, 3.0)),
            ((2.6, 3.0), (2.6, 4.5)),
            ((2.6, 4.5), (0.0, 4.5)),
            ((0.0, 4.5), (0.0, 0.0)),
        ]

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    def start(self) -> None:
        if self.running:
            return
        self._start_time = time.monotonic()
        self._last_time = self._start_time
        self._last_yaw = 0.0
        self._frame_count = 0
        self._timer.start()
        self.started.emit()

    def stop(self) -> None:
        if not self.running:
            return
        self._timer.stop()
        self.stopped.emit()

    def _tick(self) -> None:
        now = time.monotonic()
        t = now - self._start_time
        dt = max(0.02, now - self._last_time)
        self._last_time = now

        x = 3.0 + math.cos(t * 0.23) * 1.35 + math.sin(t * 0.57) * 0.18
        y = 2.15 + math.sin(t * 0.29) * 1.0
        yaw = 35.0 * math.sin(t * 0.34) + 22.0 * math.sin(t * 0.11)
        yaw_rate = (yaw - self._last_yaw) / dt
        self._last_yaw = yaw

        imu_frame = self._build_imu_frame(now, yaw_rate)
        lidar_frame = self._build_lidar_frame(now, x, y, yaw)
        status = {
            "scan_state": 1,
            "lidar_rpm": 660,
            "frame_count": self._frame_count,
            "scan_duration_ms": int(t * 1000),
            "camera_streaming": 0,
            "sensor_flags": 0x03,
        }
        self._frame_count += 1
        self.frame_ready.emit(status, imu_frame, lidar_frame)

    def _build_imu_frame(self, now: float, yaw_rate_dps: float) -> ImuFrame:
        batch_start_us = int(now * 1_000_000)
        samples = []
        for idx in range(5):
            phase = now * 3.5 + idx * 0.18
            ax_g = 0.03 * math.sin(phase) + 0.015 * math.sin(phase * 0.37)
            ay_g = 0.04 * math.cos(phase * 0.7)
            az_g = 1.0 + 0.02 * math.sin(phase * 0.3)
            gx = 3.0 * math.sin(phase * 0.8)
            gy = 2.2 * math.cos(phase * 0.6)
            gz = yaw_rate_dps + 1.5 * math.sin(phase)
            samples.append(
                ImuSample(
                    timestamp_us=batch_start_us + idx * 10_000,
                    accel_x_raw=int(ax_g * 8192),
                    accel_y_raw=int(ay_g * 8192),
                    accel_z_raw=int(az_g * 8192),
                    gyro_x_raw=int(gx * 65.5),
                    gyro_y_raw=int(gy * 65.5),
                    gyro_z_raw=int(gz * 65.5),
                )
            )
        return ImuFrame(batch_start_us=batch_start_us, samples=samples)

    def _build_lidar_frame(self, now: float, x: float, y: float, yaw_deg: float) -> LidarFrame:
        points = []
        for angle_deg in range(0, 360, 3):
            world_angle = math.radians(angle_deg + yaw_deg)
            distance_m = self._cast_ray(x, y, math.cos(world_angle), math.sin(world_angle))
            if distance_m is None:
                continue
            jitter = 1.0 + 0.004 * math.sin(now * 7.0 + angle_deg * 0.2)
            distance_mm = max(0, int(distance_m * 1000 * jitter))
            points.append(LidarPoint(angle_deg=float(angle_deg), distance_mm=distance_mm))
        return LidarFrame(timestamp_us=int(now * 1_000_000), points=points)

    def _cast_ray(self, x: float, y: float, dx: float, dy: float) -> float | None:
        closest = None
        for (x1, y1), (x2, y2) in self._room_segments:
            sx = x2 - x1
            sy = y2 - y1
            denom = dx * sy - dy * sx
            if abs(denom) < 1e-6:
                continue
            qpx = x1 - x
            qpy = y1 - y
            t = (qpx * sy - qpy * sx) / denom
            u = (qpx * dy - qpy * dx) / denom
            if t >= 0.0 and 0.0 <= u <= 1.0:
                if closest is None or t < closest:
                    closest = t
        return closest
