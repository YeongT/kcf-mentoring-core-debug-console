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

PREFIX_IMU = 0x23  # Device -> Server: IMU batch preview
PREFIX_SD_CHUNK = 0x24  # Device -> Server: SD file download chunk

PREFIX_NAMES = {
    PREFIX_INIT: "INIT",
    PREFIX_INIT_ACK: "INIT_ACK",
    PREFIX_CMD: "CMD",
    PREFIX_RES: "RES",
    PREFIX_STATUS: "STATUS",
    PREFIX_CAMERA: "CAMERA",
    PREFIX_LIDAR: "LIDAR",
    PREFIX_IMU: "IMU",
    PREFIX_SD_CHUNK: "SD_CHUNK",
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
CMD_GET_PROTOCOL_INFO = 0x0D
CMD_TIME_SYNC = 0x0E

# Protocol capability flags returned by CMD_GET_PROTOCOL_INFO.
CAP_STATUS_PUSH = 1 << 0
CAP_CAMERA_STREAM = 1 << 1
CAP_LIDAR_PREVIEW = 1 << 2
CAP_IMU_PREVIEW = 1 << 3
CAP_SD_BROWSER = 1 << 4
CAP_SD_DOWNLOAD = 1 << 5
CAP_TIME_SYNC = 1 << 6
CAP_IMU_STREAM_CTRL = 1 << 7

CAPABILITY_NAMES = {
    CAP_STATUS_PUSH: "status",
    CAP_CAMERA_STREAM: "camera",
    CAP_LIDAR_PREVIEW: "lidar-preview",
    CAP_IMU_PREVIEW: "imu-preview",
    CAP_SD_BROWSER: "sd-browser",
    CAP_SD_DOWNLOAD: "sd-download",
    CAP_TIME_SYNC: "time-sync",
    CAP_IMU_STREAM_CTRL: "imu-stream-ctrl",
}

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

# --- Command IDs --- SD Card (0x40~0x4F)
CMD_SD_LIST = 0x40
CMD_SD_DOWNLOAD = 0x41

# --- Command IDs --- IMU (0x50~0x5F)
CMD_IMU_SET_PREVIEW = 0x50

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
    CMD_GET_PROTOCOL_INFO: "GET_PROTOCOL_INFO",
    CMD_TIME_SYNC: "TIME_SYNC",
    CMD_LIDAR_GET_INFO: "LIDAR_GET_INFO",
    CMD_LIDAR_GET_HEALTH: "LIDAR_GET_HEALTH",
    CMD_LIDAR_RESET: "LIDAR_RESET",
    CMD_LIDAR_SET_SCAN_MODE: "LIDAR_SET_SCAN_MODE",
    CMD_CAMERA_GET_INFO: "CAMERA_GET_INFO",
    CMD_CAMERA_SET_PARAM: "CAMERA_SET_PARAM",
    CMD_SD_LIST: "SD_LIST",
    CMD_SD_DOWNLOAD: "SD_DOWNLOAD",
    CMD_IMU_SET_PREVIEW: "IMU_SET_PREVIEW",
}

# --- Camera Resolution/Quality enums (matches firmware CameraController) ---
# Resolution values are ESP-IDF framesize_t enum values
CAMERA_RESOLUTIONS = {
    "VGA (640x480)": 10,      # FRAMESIZE_VGA
    "SVGA (800x600)": 11,     # FRAMESIZE_SVGA
    "XGA (1024x768)": 12,     # FRAMESIZE_XGA
    "HD (1280x720)": 13,      # FRAMESIZE_HD
    "SXGA (1280x1024)": 14,   # FRAMESIZE_SXGA
    "UXGA (1600x1200)": 15,   # FRAMESIZE_UXGA
    "FHD (1920x1080)": 16,    # FRAMESIZE_FHD
    "QXGA (2048x1536)": 19,   # FRAMESIZE_QXGA
    "QHD (2560x1440)": 20,    # FRAMESIZE_QHD
    "WQXGA (2560x1600)": 21,  # FRAMESIZE_WQXGA
    "QSXGA (2592x1944)": 24,  # FRAMESIZE_5MP (2592x1944)
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
RESULT_INVALID_PAYLOAD = 0x02
RESULT_UNAVAILABLE = 0x03
RESULT_BUSY = 0x04
RESULT_NOT_FOUND = 0x05
RESULT_UNSUPPORTED = 0x06

RESULT_NAMES = {
    RESULT_OK: "OK",
    RESULT_ERROR: "ERROR",
    RESULT_INVALID_PAYLOAD: "INVALID_PAYLOAD",
    RESULT_UNAVAILABLE: "UNAVAILABLE",
    RESULT_BUSY: "BUSY",
    RESULT_NOT_FOUND: "NOT_FOUND",
    RESULT_UNSUPPORTED: "UNSUPPORTED",
}

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
    """22-byte packed DeviceStatus struct (little-endian)."""

    scan_state: int = 0
    lidar_rpm: int = 0
    sd_free_mb: int = 0
    sd_total_mb: int = 0
    frame_count: int = 0
    scan_duration_ms: int = 0
    battery_pct: int = 0xFF
    camera_streaming: int = 0
    sensor_flags: int = 0  # bit0=LiDAR, bit1=IMU, bit2=Camera, bit3=SD

    STRUCT_SIZE = 22

    @classmethod
    def from_bytes(cls, data: bytes) -> "DeviceStatus":
        if len(data) < 21:
            raise ValueError(f"DeviceStatus needs at least 21 bytes, got {len(data)}")
        scan_state = data[0]
        lidar_rpm = struct.unpack_from("<H", data, 1)[0]
        sd_free_mb = struct.unpack_from("<I", data, 3)[0]
        sd_total_mb = struct.unpack_from("<I", data, 7)[0]
        frame_count = struct.unpack_from("<I", data, 11)[0]
        scan_duration_ms = struct.unpack_from("<I", data, 15)[0]
        battery_pct = data[19]
        camera_streaming = data[20]
        sensor_flags = data[21] if len(data) >= 22 else 0
        return cls(
            scan_state=scan_state,
            lidar_rpm=lidar_rpm,
            sd_free_mb=sd_free_mb,
            sd_total_mb=sd_total_mb,
            frame_count=frame_count,
            scan_duration_ms=scan_duration_ms,
            battery_pct=battery_pct,
            camera_streaming=camera_streaming,
            sensor_flags=sensor_flags,
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

    @property
    def lidar_ok(self) -> bool:
        return bool(self.sensor_flags & 0x01)

    @property
    def imu_ok(self) -> bool:
        return bool(self.sensor_flags & 0x02)

    @property
    def camera_ok(self) -> bool:
        return bool(self.sensor_flags & 0x04)

    @property
    def sd_ok(self) -> bool:
        return bool(self.sensor_flags & 0x08)

    @property
    def sd_str(self) -> str:
        if self.sd_total_mb == 0:
            return "0 GB"
        used_gb = (self.sd_total_mb - self.sd_free_mb) / 1024
        total_gb = self.sd_total_mb / 1024
        pct = (self.sd_total_mb - self.sd_free_mb) / self.sd_total_mb * 100
        return f"{used_gb:.1f} / {total_gb:.1f} GB ({pct:.1f}%)"


@dataclass
class LidarPoint:
    angle_deg: float
    distance_mm: int


@dataclass
class LidarFrame:
    timestamp_us: int
    points: List[LidarPoint]


@dataclass
class ImuSample:
    timestamp_us: int
    accel_x_raw: int
    accel_y_raw: int
    accel_z_raw: int
    gyro_x_raw: int
    gyro_y_raw: int
    gyro_z_raw: int

    @property
    def accel_x_g(self) -> float:
        return self.accel_x_raw / 8192.0

    @property
    def accel_y_g(self) -> float:
        return self.accel_y_raw / 8192.0

    @property
    def accel_z_g(self) -> float:
        return self.accel_z_raw / 8192.0

    @property
    def gyro_x_dps(self) -> float:
        return self.gyro_x_raw / 65.5

    @property
    def gyro_y_dps(self) -> float:
        return self.gyro_y_raw / 65.5

    @property
    def gyro_z_dps(self) -> float:
        return self.gyro_z_raw / 65.5


@dataclass
class ImuFrame:
    batch_start_us: int
    samples: List[ImuSample]


@dataclass
class SdEntry:
    path: str
    is_dir: bool
    size_bytes: int

    @property
    def name(self) -> str:
        parts = [part for part in self.path.split("/") if part]
        return parts[-1] if parts else "/"


@dataclass
class SdChunk:
    flags: int
    offset: int
    total_size: int
    data: bytes

    @property
    def is_eof(self) -> bool:
        return bool(self.flags & 0x01)


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

    @property
    def result_name(self) -> str:
        return RESULT_NAMES.get(self.result, f"0x{self.result:02X}")


@dataclass
class ProtocolInfo:
    """Parsed GET_PROTOCOL_INFO response payload from protocol v2 firmware."""

    version: int = 0
    capabilities: int = 0
    imu_preview_enabled: bool = False
    imu_interval_ms: int = 0
    status_push_ms: int = 0
    max_payload_hint: int = 0

    @classmethod
    def from_bytes(cls, data: bytes) -> Optional["ProtocolInfo"]:
        if len(data) < 12:
            return None
        return cls(
            version=data[0],
            capabilities=struct.unpack_from("<I", data, 1)[0],
            imu_preview_enabled=data[5] != 0,
            imu_interval_ms=struct.unpack_from("<H", data, 6)[0],
            status_push_ms=struct.unpack_from("<H", data, 8)[0],
            max_payload_hint=struct.unpack_from("<H", data, 10)[0],
        )

    @property
    def capability_list(self) -> List[str]:
        return [name for bit, name in CAPABILITY_NAMES.items() if self.capabilities & bit]

    @property
    def capability_str(self) -> str:
        return ", ".join(self.capability_list) or "none"


@dataclass
class TimeSyncInfo:
    """Parsed TIME_SYNC response payload."""

    device_time_us: int = 0
    device_tick_ms: int = 0

    @classmethod
    def from_bytes(cls, data: bytes) -> Optional["TimeSyncInfo"]:
        if len(data) < 12:
            return None
        return cls(
            device_time_us=struct.unpack_from("<Q", data, 0)[0],
            device_tick_ms=struct.unpack_from("<I", data, 8)[0],
        )


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


def build_imu_set_preview(seq: int, enabled: bool, interval_ms: int | None = None) -> bytes:
    payload = bytes([1 if enabled else 0])
    if interval_ms is not None:
        payload += struct.pack("<H", max(0, min(0xFFFF, int(interval_ms))))
    return build_command(CMD_IMU_SET_PREVIEW, seq, payload)


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
    """Parse a STATUS message: [0x20] [DeviceStatus: 22B]"""
    if len(data) < 23 or data[0] != PREFIX_STATUS:
        return None
    return DeviceStatus.from_bytes(data[1:23])


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


def parse_imu_frame(data: bytes) -> Optional[ImuFrame]:
    """Parse an IMU message: [0x23] [batch_start_us:8B] [count:1B] [samples: count*20B]."""
    if len(data) < 10 or data[0] != PREFIX_IMU:
        return None
    batch_start_us = struct.unpack_from("<Q", data, 1)[0]
    sample_count = data[9]
    offset = 10
    samples: list[ImuSample] = []
    for _ in range(sample_count):
        if offset + 20 > len(data):
            break
        ts_offset_us, ax, ay, az, gx, gy, gz, _reserved = struct.unpack_from("<IhhhhhhI", data, offset)
        samples.append(
            ImuSample(
                timestamp_us=batch_start_us + ts_offset_us,
                accel_x_raw=ax,
                accel_y_raw=ay,
                accel_z_raw=az,
                gyro_x_raw=gx,
                gyro_y_raw=gy,
                gyro_z_raw=gz,
            )
        )
        offset += 20
    return ImuFrame(batch_start_us=batch_start_us, samples=samples)


def parse_sd_chunk(data: bytes) -> Optional[SdChunk]:
    """Parse an SD download chunk: [0x24] [flags:1B] [offset:4B] [total_size:4B] [bytes...]."""
    if len(data) < 10 or data[0] != PREFIX_SD_CHUNK:
        return None
    flags = data[1]
    offset = struct.unpack_from("<I", data, 2)[0]
    total_size = struct.unpack_from("<I", data, 6)[0]
    return SdChunk(flags=flags, offset=offset, total_size=total_size, data=data[10:])


def parse_sd_entries(data: bytes) -> list[SdEntry]:
    """Parse SD_LIST payload: [count:2B] repeated [flags:1B][size:8B][path_len:2B][path:utf8]."""
    if len(data) < 2:
        return []
    entry_count = struct.unpack_from("<H", data, 0)[0]
    offset = 2
    entries: list[SdEntry] = []
    for _ in range(entry_count):
        if offset + 11 > len(data):
            break
        flags = data[offset]
        size_bytes = struct.unpack_from("<Q", data, offset + 1)[0]
        path_len = struct.unpack_from("<H", data, offset + 9)[0]
        offset += 11
        if offset + path_len > len(data):
            break
        path = data[offset : offset + path_len].decode("utf-8", errors="replace")
        offset += path_len
        entries.append(SdEntry(path=path, is_dir=bool(flags & 0x01), size_bytes=size_bytes))
    return entries


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
