"""Non-GUI smoke checks for protocol, settings, UDP discovery, and WebSocket server."""

import asyncio
import json
import socket
import tempfile
import time
from pathlib import Path

from PyQt6.QtCore import QCoreApplication
from websockets.asyncio.client import connect

import settings
from protocol import (
    CMD_GET_STATUS,
    MAX_PACKET_SIZE,
    PREFIX_CMD,
    PREFIX_INIT,
    PREFIX_INIT_ACK,
    PREFIX_RES,
    PREFIX_SD_CHUNK,
    PREFIX_STATUS,
    PROTOCOL_VERSION,
    DeviceStatus,
    build_command,
    parse_command,
    parse_sd_chunk,
)
from udp_discovery import UdpDiscoveryListener
from ws_server import DeviceConnection, WebSocketServer


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _status_bytes() -> bytes:
    return DeviceStatus.STRUCT.pack(0, 300, 1024, 2048, 7, 1000, 95, 0, 0x0F)


def _init_packet(name: str = "CORE_SMOKE") -> bytes:
    name_bytes = name.encode("utf-8")
    return bytes([PREFIX_INIT, PROTOCOL_VERSION, len(name_bytes)]) + name_bytes + _status_bytes()


def test_settings_migrates_legacy_port() -> None:
    original_path = settings._SETTINGS_PATH
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "settings.json"
        path.write_text(json.dumps({"status_poll_interval": 1000, "server_port": 3000}), encoding="utf-8")
        settings._SETTINGS_PATH = str(path)
        try:
            loaded = settings.load()
            assert loaded["server_port"] == 3421
            rewritten = json.loads(path.read_text(encoding="utf-8"))
            assert rewritten["server_port"] == 3421
        finally:
            settings._SETTINGS_PATH = original_path


def test_protocol_and_discovery_validation() -> None:
    packet = build_command(CMD_GET_STATUS, 255)
    parsed = parse_command(packet)
    assert parsed is not None
    assert parsed.cmd_id == CMD_GET_STATUS
    try:
        build_command(CMD_GET_STATUS, 0, b"x" * MAX_PACKET_SIZE)
    except ValueError:
        pass
    else:
        raise AssertionError("oversized command was accepted")

    assert UdpDiscoveryListener._parse_packet("CORE|192.168.1.50") is not None
    assert UdpDiscoveryListener._parse_packet("CORE|999.1.1.1") is None
    assert UdpDiscoveryListener._parse_packet("bad\x01name|192.168.1.50") is None
    assert UdpDiscoveryListener._parse_packet("CONNECT|127.0.0.1:3421") is None
    chunk = parse_sd_chunk(bytes([PREFIX_SD_CHUNK, 3, 0x01, 0, 0, 0, 0, 2, 0, 0, 0, 1, 2]))
    assert chunk is not None
    assert chunk.transfer_id == 3
    assert parse_sd_chunk(bytes([PREFIX_SD_CHUNK, 3, 0x00, 0, 0, 0, 0, 2, 0, 0, 0])) is None


async def test_live_websocket_handshake_and_commands() -> None:
    QCoreApplication.instance() or QCoreApplication([])
    connection = DeviceConnection()
    server = WebSocketServer(connection, host="127.0.0.1", port=_free_port())
    server.start()
    url = f"ws://127.0.0.1:{server.port}"

    try:
        deadline = time.time() + 5
        ws_context = None
        while time.time() < deadline:
            try:
                ws_context = connect(url, max_size=MAX_PACKET_SIZE)
                ws = await ws_context.__aenter__()
                break
            except OSError:
                await asyncio.sleep(0.05)
        else:
            raise AssertionError("server did not accept WebSocket connections")

        try:
            await ws.send(_init_packet())
            ack = await asyncio.wait_for(ws.recv(), timeout=2)
            assert isinstance(ack, bytes)
            assert ack[0] == PREFIX_INIT_ACK

            await ws.send(bytes([PREFIX_RES, CMD_GET_STATUS]))
            await ws.send(b"")
            connection.send_command(CMD_GET_STATUS)
            cmd = await asyncio.wait_for(ws.recv(), timeout=2)
            assert isinstance(cmd, bytes)
            assert cmd[0] == PREFIX_CMD
            parsed = parse_command(cmd)
            assert parsed is not None
            assert parsed.cmd_id == CMD_GET_STATUS

            await ws.send(bytes([PREFIX_STATUS]) + _status_bytes())
        finally:
            if ws_context is not None:
                await ws_context.__aexit__(None, None, None)
    finally:
        server.stop()


def main() -> None:
    test_settings_migrates_legacy_port()
    test_protocol_and_discovery_validation()
    asyncio.run(test_live_websocket_handshake_and_commands())
    print("smoke_protocol_server: OK")


if __name__ == "__main__":
    main()
