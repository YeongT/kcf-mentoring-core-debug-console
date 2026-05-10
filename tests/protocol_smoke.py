"""Smoke checks for the Core Device protocol v2 contract."""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol import (
    CMD_START_STREAM,
    INIT_FLAG_START_STREAM,
    PREFIX_INIT,
    PREFIX_INIT_ACK,
    PREFIX_RES,
    PREFIX_SD_CHUNK,
    PREFIX_STATUS,
    PROTOCOL_VERSION,
    RESULT_OK,
    SCAN_SCANNING,
    DeviceStatus,
    InitAckSettings,
    build_command,
    parse_init,
    parse_response,
    parse_sd_chunk,
    parse_status,
)
from udp_discovery import UdpDiscoveryListener


def _status_payload(sensor_flags: int = 0x0D) -> bytes:
    return DeviceStatus.STRUCT.pack(
        SCAN_SCANNING,
        612,
        1234,
        4096,
        77,
        9001,
        0xFF,
        1,
        sensor_flags,
    )


def run() -> None:
    payload = _status_payload()
    assert len(payload) == DeviceStatus.STRUCT_SIZE == 22

    status = parse_status(bytes([PREFIX_STATUS]) + payload)
    assert status is not None
    assert status.camera_streaming == 1
    assert status.sensor_flags == 0x0D
    assert status.sd_ok

    ack = InitAckSettings(
        status_push_ms=5000,
        stream_interval_ms=80,
        motor_rpm=700,
        flags=INIT_FLAG_START_STREAM,
        camera_resolution=13,
        camera_quality=10,
    ).to_bytes()
    assert len(ack) == 13
    assert ack[0] == PREFIX_INIT_ACK

    name = b"CORE_DEVICE"
    init = bytes([PREFIX_INIT, PROTOCOL_VERSION, len(name)]) + name + payload
    parsed_init = parse_init(init)
    assert parsed_init is not None
    assert parsed_init.device_name == "CORE_DEVICE"
    assert parsed_init.status.lidar_rpm == 612

    cmd = build_command(CMD_START_STREAM, 7, struct.pack("<H", 200))
    assert cmd == bytes([0x10, CMD_START_STREAM, 7, 0xC8, 0x00])

    response = parse_response(bytes([PREFIX_RES, CMD_START_STREAM, 7, RESULT_OK]))
    assert response is not None
    assert response.ok

    chunk = parse_sd_chunk(bytes([PREFIX_SD_CHUNK, 7, 0x01, 0, 0, 0, 0, 2, 0, 0, 0, 1, 2]))
    assert chunk is not None
    assert chunk.transfer_id == 7
    assert chunk.offset == 0
    assert chunk.total_size == 2
    assert chunk.data == b"\x01\x02"
    assert chunk.is_eof
    assert parse_sd_chunk(bytes([PREFIX_SD_CHUNK, 8, 0x01, 0, 0, 0, 0, 3, 0, 0, 0, 1, 2])) is None

    assert UdpDiscoveryListener._parse_packet(b"CORE_DEVICE|192.168.137.100", "192.168.137.100")
    assert UdpDiscoveryListener._parse_packet(b"CONNECT|192.168.137.1:3421", "192.168.137.100") is None


if __name__ == "__main__":
    run()
    print("protocol smoke passed")
