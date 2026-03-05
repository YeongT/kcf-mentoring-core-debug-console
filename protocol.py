"""Binary protocol definitions and parsing for Core Device WebSocket communication."""

import struct
from dataclasses import dataclass
from typing import List, Optional, Tuple

# --- Message Prefixes (grouped by function) ---
# 0x00~0x0F: Handshake
PREFIX_INIT = 0x01  # Device → Server: init handshake
PREFIX_INIT_ACK = 0x02  # Server → Device: init ack + settings
# 0x10~0x1F: Command / Response
PREFIX_CMD = 0x10  # Server → Device: command request
PREFIX_RES = 0x11  # Device → Server: command response
# 0x20~0x2F: Push (Device → Server)
PREFIX_STATUS = 0x20  # Device → Server: periodic status push
PREFIX_CAMERA = 0x21  # Device → Server: JPEG camera frame
PREFIX_LIDAR = 0x22  # Device → Server: LiDAR preview

PREFIX_NAMES = {
    PREFIX_INIT: "INIT",
    PREFIX_INIT_ACK: "INIT_ACK",
    PREFIX_CMD: "CMD",
    PREFIX_RES: "RES",
    PREFIX_STATUS: "STATUS",
    PREFIX_CAMERA: "CAMERA",
    PREFIX_LIDAR: "LIDAR",
}

# --- Command IDs ---
CMD_GET_STATUS = 0x01
CMD_START_SCAN = 0x02
CMD_STOP_SCAN = 0x03
CMD_SET_MOTOR_RPM = 0x04
CMD_START_STREAM = 0x05
CMD_STOP_STREAM = 0x06
CMD_CAPTURE_FRAME = 0x07

CMD_NAMES = {
    CMD_GET_STATUS: "GET_STATUS",
    CMD_START_SCAN: "START_SCAN",
    CMD_STOP_SCAN: "STOP_SCAN",
    CMD_SET_MOTOR_RPM: "SET_MOTOR_RPM",
    CMD_START_STREAM: "START_STREAM",
    CMD_STOP_STREAM: "STOP_STREAM",
    CMD_CAPTURE_FRAME: "CAPTURE_FRAME",
}

# --- Result Codes ---
RESULT_OK = 0x00
RESULT_ERROR = 0x01

# --- Scan States ---
SCAN_IDLE = 0x00
SCAN_SCANNING = 0x01
SCAN_STOPPING = 0x02

SCAN_STATE_NAMES = {
    SCAN_IDLE: "IDLE",
    SCAN_SCANNING: "SCANNING",
    SCAN_STOPPING: "STOPPING",
}


@dataclass
class DeviceStatus:
    """17-byte packed DeviceStatus struct (little-endian)."""

    scan_state: int = 0
    lidar_rpm: int = 0
    sd_free_mb: int = 0
    frame_count: int = 0
    scan_duration_ms: int = 0
    battery_pct: int = 0xFF
    camera_streaming: int = 0

    STRUCT_FORMAT = "<BHIIIBBx"  # x is padding to handle 17 bytes manually
    STRUCT_SIZE = 17

    @classmethod
    def from_bytes(cls, data: bytes) -> "DeviceStatus":
        if len(data) < cls.STRUCT_SIZE:
            raise ValueError(f"DeviceStatus needs {cls.STRUCT_SIZE} bytes, got {len(data)}")
        scan_state = data[0]
        lidar_rpm = struct.unpack_from("<H", data, 1)[0]
        sd_free_mb = struct.unpack_from("<I", data, 3)[0]
        frame_count = struct.unpack_from("<I", data, 7)[0]
        scan_duration_ms = struct.unpack_from("<I", data, 11)[0]
        battery_pct = data[15]
        camera_streaming = data[16]
        return cls(
            scan_state=scan_state,
            lidar_rpm=lidar_rpm,
            sd_free_mb=sd_free_mb,
            frame_count=frame_count,
            scan_duration_ms=scan_duration_ms,
            battery_pct=battery_pct,
            camera_streaming=camera_streaming,
        )

    @property
    def scan_state_name(self) -> str:
        return SCAN_STATE_NAMES.get(self.scan_state, f"UNKNOWN(0x{self.scan_state:02X})")

    @property
    def battery_str(self) -> str:
        return "N/A" if self.battery_pct == 0xFF else f"{self.battery_pct}%"

    @property
    def streaming_str(self) -> str:
        return "ON" if self.camera_streaming else "OFF"

    @property
    def duration_str(self) -> str:
        ms = self.scan_duration_ms
        if ms == 0:
            return "0s"
        seconds = ms // 1000
        minutes = seconds // 60
        if minutes > 0:
            return f"{minutes}m {seconds % 60}s"
        return f"{seconds}s"


@dataclass
class LidarPoint:
    angle_deg: float
    distance_mm: int


@dataclass
class LidarFrame:
    timestamp_us: int
    points: List[LidarPoint]


@dataclass
class CommandResponse:
    cmd_id: int
    seq: int
    result: int
    payload: bytes

    @property
    def ok(self) -> bool:
        return self.result == RESULT_OK

    @property
    def cmd_name(self) -> str:
        return CMD_NAMES.get(self.cmd_id, f"0x{self.cmd_id:02X}")


# --- Packet builders ---


def build_command(cmd_id: int, seq: int, payload: bytes = b"") -> bytes:
    """Build a command packet: [0x10] [cmd_id] [seq] [payload...]"""
    return bytes([PREFIX_CMD, cmd_id, seq]) + payload


def build_set_motor_rpm(seq: int, rpm: int) -> bytes:
    return build_command(CMD_SET_MOTOR_RPM, seq, struct.pack("<H", rpm))


def build_start_stream(seq: int, interval_ms: int = 0) -> bytes:
    return build_command(CMD_START_STREAM, seq, struct.pack("<H", interval_ms))


# --- Packet parsers ---


def parse_response(data: bytes) -> Optional[CommandResponse]:
    """Parse a RES message: [0x11] [cmd_id] [seq] [result] [payload...]"""
    if len(data) < 4 or data[0] != PREFIX_RES:
        return None
    return CommandResponse(
        cmd_id=data[1],
        seq=data[2],
        result=data[3],
        payload=data[4:],
    )


def parse_status(data: bytes) -> Optional[DeviceStatus]:
    """Parse a STATUS message: [0x20] [DeviceStatus: 17B]"""
    if len(data) < 18 or data[0] != PREFIX_STATUS:
        return None
    return DeviceStatus.from_bytes(data[1:18])


def parse_camera_frame(data: bytes) -> Optional[bytes]:
    """Parse a CAMERA message: [0x21] [JPEG data...]"""
    if len(data) < 2 or data[0] != PREFIX_CAMERA:
        return None
    return data[1:]


def parse_lidar_frame(data: bytes) -> Optional[LidarFrame]:
    """Parse a LIDAR message: [0x22] [ts:8B] [count:2B] [points: count*4B]"""
    if len(data) < 11 or data[0] != PREFIX_LIDAR:
        return None
    timestamp_us = struct.unpack_from("<Q", data, 1)[0]
    point_count = struct.unpack_from("<H", data, 9)[0]
    points = []
    offset = 11
    for _ in range(point_count):
        if offset + 4 > len(data):
            break
        angle_q6, distance_mm = struct.unpack_from("<HH", data, offset)
        points.append(LidarPoint(angle_deg=angle_q6 / 64.0, distance_mm=distance_mm))
        offset += 4
    return LidarFrame(timestamp_us=timestamp_us, points=points)


# --- Handshake ---

INIT_FLAG_START_STREAM = 0x01

PROTOCOL_VERSION = 1


@dataclass
class InitMessage:
    """INIT handshake from device."""

    protocol_version: int
    device_name: str
    status: DeviceStatus

    @classmethod
    def from_bytes(cls, data: bytes) -> Optional["InitMessage"]:
        if len(data) < 3 or data[0] != PREFIX_INIT:
            return None
        version = data[1]
        name_len = data[2]
        if len(data) < 3 + name_len + DeviceStatus.STRUCT_SIZE:
            return None
        name = data[3 : 3 + name_len].decode("utf-8", errors="replace")
        status = DeviceStatus.from_bytes(data[3 + name_len : 3 + name_len + DeviceStatus.STRUCT_SIZE])
        return cls(protocol_version=version, device_name=name, status=status)


@dataclass
class InitAckSettings:
    """Settings sent to device via INIT_ACK."""

    status_push_ms: int = 2000
    stream_interval_ms: int = 50
    motor_rpm: int = 0
    flags: int = 0

    def to_bytes(self) -> bytes:
        return bytes([PREFIX_INIT_ACK]) + struct.pack(
            "<HHHBx",
            self.status_push_ms,
            self.stream_interval_ms,
            self.motor_rpm,
            self.flags,
        )


def parse_init(data: bytes) -> Optional[InitMessage]:
    return InitMessage.from_bytes(data)


def format_hex(data: bytes, max_bytes: int = 32) -> str:
    """Format bytes as hex string, truncated if needed."""
    hex_str = data[:max_bytes].hex(" ")
    if len(data) > max_bytes:
        hex_str += f" ... ({len(data)} bytes total)"
    return hex_str
