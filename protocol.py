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

# --- Command IDs --- Basic (0x01~0x08)
CMD_GET_STATUS = 0x01
CMD_START_SCAN = 0x02
CMD_STOP_SCAN = 0x03
CMD_SET_MOTOR_RPM = 0x04
CMD_START_STREAM = 0x05
CMD_STOP_STREAM = 0x06
CMD_CAPTURE_FRAME = 0x07
CMD_SET_CAMERA_CONFIG = 0x08

# --- Command IDs --- Device Info & Control (0x09~0x0F)
CMD_GET_DEVICE_INFO = 0x09
CMD_REBOOT = 0x0A
CMD_SET_LED = 0x0B
CMD_SET_LCD_TEXT = 0x0C

# --- Command IDs --- RPLiDAR (0x20~0x2F)
CMD_LIDAR_GET_INFO = 0x20
CMD_LIDAR_GET_HEALTH = 0x21
CMD_LIDAR_RESET = 0x22
CMD_LIDAR_SET_SCAN_MODE = 0x23

# Scan modes for CMD_LIDAR_SET_SCAN_MODE
SCAN_MODE_STANDARD = 0
SCAN_MODE_EXPRESS = 1

SCAN_MODE_NAMES = {
    SCAN_MODE_STANDARD: "Standard",
    SCAN_MODE_EXPRESS: "Express",
}

# --- Command IDs --- Camera Advanced (0x30~0x3F)
CMD_CAMERA_GET_INFO = 0x30
CMD_CAMERA_SET_PARAM = 0x31

# Camera param IDs for CMD_CAMERA_SET_PARAM
CAMERA_PARAM_BRIGHTNESS = 0x01  # -2 to 2
CAMERA_PARAM_CONTRAST = 0x02  # -2 to 2
CAMERA_PARAM_SATURATION = 0x03  # -2 to 2
CAMERA_PARAM_EFFECT = 0x04  # 0=None,1=Neg,2=Gray,3=Red,4=Green,5=Blue,6=Sepia
CAMERA_PARAM_WHITEBAL = 0x05  # 0/1
CAMERA_PARAM_EXPOSURE = 0x06  # 0/1 (auto)
CAMERA_PARAM_AEC_VALUE = 0x07  # 0-1200
CAMERA_PARAM_HMIRROR = 0x08  # 0/1
CAMERA_PARAM_VFLIP = 0x09  # 0/1

CAMERA_PARAM_NAMES = {
    CAMERA_PARAM_BRIGHTNESS: "Brightness",
    CAMERA_PARAM_CONTRAST: "Contrast",
    CAMERA_PARAM_SATURATION: "Saturation",
    CAMERA_PARAM_EFFECT: "Effect",
    CAMERA_PARAM_WHITEBAL: "White Balance",
    CAMERA_PARAM_EXPOSURE: "Auto Exposure",
    CAMERA_PARAM_AEC_VALUE: "AEC Value",
    CAMERA_PARAM_HMIRROR: "H-Mirror",
    CAMERA_PARAM_VFLIP: "V-Flip",
}

CAMERA_EFFECTS = {
    0: "None",
    1: "Negative",
    2: "Grayscale",
    3: "Red Tint",
    4: "Green Tint",
    5: "Blue Tint",
    6: "Sepia",
}

CMD_NAMES = {
    CMD_GET_STATUS: "GET_STATUS",
    CMD_START_SCAN: "START_SCAN",
    CMD_STOP_SCAN: "STOP_SCAN",
    CMD_SET_MOTOR_RPM: "SET_MOTOR_RPM",
    CMD_START_STREAM: "START_STREAM",
    CMD_STOP_STREAM: "STOP_STREAM",
    CMD_CAPTURE_FRAME: "CAPTURE_FRAME",
    CMD_SET_CAMERA_CONFIG: "SET_CAMERA_CONFIG",
    CMD_GET_DEVICE_INFO: "GET_DEVICE_INFO",
    CMD_REBOOT: "REBOOT",
    CMD_SET_LED: "SET_LED",
    CMD_SET_LCD_TEXT: "SET_LCD_TEXT",
    CMD_LIDAR_GET_INFO: "LIDAR_GET_INFO",
    CMD_LIDAR_GET_HEALTH: "LIDAR_GET_HEALTH",
    CMD_LIDAR_RESET: "LIDAR_RESET",
    CMD_LIDAR_SET_SCAN_MODE: "LIDAR_SET_SCAN_MODE",
    CMD_CAMERA_GET_INFO: "CAMERA_GET_INFO",
    CMD_CAMERA_SET_PARAM: "CAMERA_SET_PARAM",
}

# --- Camera Resolution/Quality enums (matches firmware CameraController) ---
# Resolution values are ESP-IDF framesize_t enum values
CAMERA_RESOLUTIONS = {
    "VGA (640x480)": 8,      # FRAMESIZE_VGA
    "SVGA (800x600)": 9,     # FRAMESIZE_SVGA
    "XGA (1024x768)": 10,    # FRAMESIZE_XGA
    "SXGA (1280x1024)": 12,  # FRAMESIZE_SXGA
    "HD (1280x720)": 11,     # FRAMESIZE_HD
    "UXGA (1600x1200)": 13,  # FRAMESIZE_UXGA
    "FHD (1920x1080)": 14,   # FRAMESIZE_FHD
    "QXGA (2048x1536)": 17,  # FRAMESIZE_QXGA
    "QHD (2560x1440)": 18,   # FRAMESIZE_QHD
    "WQXGA (2560x1600)": 19, # FRAMESIZE_WQXGA
    "QSXGA (2592x1944)": 20, # FRAMESIZE_QSXGA
}

CAMERA_QUALITIES = {
    "ORIGINAL (1)": 1,
    "ULTRA (4)": 4,
    "HIGH (7)": 7,
    "MEDIUM (10)": 10,
    "BASIC (18)": 18,
    "LOW (24)": 24,
    "PREVIEW (30)": 30,
}

# Default values matching firmware defaults
DEFAULT_CAMERA_RESOLUTION = "HD (1280x720)"
DEFAULT_CAMERA_QUALITY = "HIGH (7)"

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


@dataclass
class DeviceInfo:
    """Parsed GET_DEVICE_INFO response payload."""

    chip_model: int = 0
    chip_cores: int = 0
    chip_revision: int = 0
    free_heap: int = 0
    min_free_heap: int = 0
    psram_total: int = 0
    psram_free: int = 0
    wifi_rssi: int = -127
    device_name: str = ""

    @classmethod
    def from_bytes(cls, data: bytes) -> Optional["DeviceInfo"]:
        if len(data) < 21:
            return None
        chip_model = data[0]
        chip_cores = data[1]
        chip_revision = struct.unpack_from("<H", data, 2)[0]
        free_heap = struct.unpack_from("<I", data, 4)[0]
        min_free_heap = struct.unpack_from("<I", data, 8)[0]
        psram_total = struct.unpack_from("<I", data, 12)[0]
        psram_free = struct.unpack_from("<I", data, 16)[0]
        wifi_rssi = struct.unpack_from("<b", data, 20)[0]  # signed int8
        device_name = ""
        if len(data) > 21:
            name_bytes = data[21:]
            device_name = name_bytes.split(b"\x00")[0].decode("utf-8", errors="replace")
        return cls(
            chip_model=chip_model,
            chip_cores=chip_cores,
            chip_revision=chip_revision,
            free_heap=free_heap,
            min_free_heap=min_free_heap,
            psram_total=psram_total,
            psram_free=psram_free,
            wifi_rssi=wifi_rssi,
            device_name=device_name,
        )


@dataclass
class LidarInfo:
    """Parsed LIDAR_GET_INFO response (20 bytes, matches rplidar::DeviceInfo)."""

    model: int = 0
    firmware_minor: int = 0
    firmware_major: int = 0
    hardware: int = 0
    serial: str = ""

    @classmethod
    def from_bytes(cls, data: bytes) -> Optional["LidarInfo"]:
        if len(data) < 20:
            return None
        model = data[0]
        fw_minor = data[1]
        fw_major = data[2]
        hw = data[3]
        serial = data[4:20].hex().upper()
        return cls(
            model=model,
            firmware_minor=fw_minor,
            firmware_major=fw_major,
            hardware=hw,
            serial=serial,
        )

    @property
    def major_model(self) -> int:
        return (self.model >> 3) & 0x1F

    @property
    def firmware_str(self) -> str:
        return f"{self.firmware_major}.{self.firmware_minor}"


LIDAR_HEALTH_OK = 0
LIDAR_HEALTH_WARNING = 1
LIDAR_HEALTH_ERROR = 2

LIDAR_HEALTH_NAMES = {
    LIDAR_HEALTH_OK: "Good",
    LIDAR_HEALTH_WARNING: "Warning",
    LIDAR_HEALTH_ERROR: "Error (Protection Stop)",
}


@dataclass
class LidarHealth:
    """Parsed LIDAR_GET_HEALTH response (3 bytes, matches rplidar::DeviceHealth)."""

    status: int = 0
    error_code: int = 0

    @classmethod
    def from_bytes(cls, data: bytes) -> Optional["LidarHealth"]:
        if len(data) < 3:
            return None
        status = data[0]
        error_code = struct.unpack_from("<H", data, 1)[0]
        return cls(status=status, error_code=error_code)

    @property
    def status_name(self) -> str:
        return LIDAR_HEALTH_NAMES.get(self.status, f"Unknown(0x{self.status:02X})")

    @property
    def is_ok(self) -> bool:
        return self.status == LIDAR_HEALTH_OK


@dataclass
class CameraInfo:
    """Parsed CAMERA_GET_INFO response."""

    resolution: int = 0
    quality: int = 0
    streaming: bool = False
    model: str = ""

    @classmethod
    def from_bytes(cls, data: bytes) -> Optional["CameraInfo"]:
        if len(data) < 3:
            return None
        resolution = data[0]
        quality = data[1]
        streaming = data[2] != 0
        model = ""
        if len(data) > 3:
            model = data[3:].split(b"\x00")[0].decode("utf-8", errors="replace")
        return cls(
            resolution=resolution,
            quality=quality,
            streaming=streaming,
            model=model,
        )


# --- Packet builders ---


def build_command(cmd_id: int, seq: int, payload: bytes = b"") -> bytes:
    """Build a command packet: [0x10] [cmd_id] [seq] [payload...]"""
    return bytes([PREFIX_CMD, cmd_id, seq]) + payload


def build_set_motor_rpm(seq: int, rpm: int) -> bytes:
    return build_command(CMD_SET_MOTOR_RPM, seq, struct.pack("<H", rpm))


def build_start_stream(seq: int, interval_ms: int = 0) -> bytes:
    return build_command(CMD_START_STREAM, seq, struct.pack("<H", interval_ms))


def build_camera_set_param(seq: int, param_id: int, value: int) -> bytes:
    """Build CAMERA_SET_PARAM: [param_id:1B][value:2B LE int16]"""
    return build_command(CMD_CAMERA_SET_PARAM, seq, struct.pack("<Bh", param_id, value))


def build_set_led(seq: int, index: int, r: int, g: int, b: int) -> bytes:
    return build_command(CMD_SET_LED, seq, bytes([index, r, g, b]))


def build_set_lcd_text(seq: int, line: int, text: str) -> bytes:
    return build_command(CMD_SET_LCD_TEXT, seq, bytes([line]) + text.encode("utf-8"))


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
    """Settings sent to device via INIT_ACK (12 bytes payload)."""

    status_push_ms: int = 5000
    stream_interval_ms: int = 50
    motor_rpm: int = 0
    flags: int = 0
    camera_resolution: int = 0  # 0 = don't change
    camera_quality: int = 0  # 0 = don't change

    def to_bytes(self) -> bytes:
        return bytes([PREFIX_INIT_ACK]) + struct.pack(
            "<HHHBBBxxx",
            self.status_push_ms,
            self.stream_interval_ms,
            self.motor_rpm,
            self.flags,
            self.camera_resolution,
            self.camera_quality,
        )


def parse_init(data: bytes) -> Optional[InitMessage]:
    return InitMessage.from_bytes(data)


def format_hex(data: bytes, max_bytes: int = 32) -> str:
    """Format bytes as hex string, truncated if needed."""
    hex_str = data[:max_bytes].hex(" ")
    if len(data) > max_bytes:
        hex_str += f" ... ({len(data)} bytes total)"
    return hex_str
