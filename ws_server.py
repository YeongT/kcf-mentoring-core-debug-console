"""WebSocket server that accepts ESP32 device connections and bridges to Qt GUI."""

import asyncio
import threading
from typing import Optional

from websockets.asyncio.server import serve, ServerConnection

from PyQt6.QtCore import QObject, pyqtSignal

from protocol import (
    PREFIX_INIT,
    PREFIX_RES,
    PREFIX_STATUS,
    PREFIX_CAMERA,
    PREFIX_LIDAR,
    InitAckSettings,
    parse_init,
    build_command,
)


class DeviceConnection(QObject):
    """Manages a single device WebSocket connection with Qt signals."""

    # Signals emitted on the main (GUI) thread
    device_connected = pyqtSignal(str, bytes)  # device_name, initial status bytes
    device_disconnected = pyqtSignal()
    response_received = pyqtSignal(bytes)  # raw RES message
    status_received = pyqtSignal(bytes)  # raw STATUS message (18B)
    camera_frame_received = pyqtSignal(bytes)  # raw CAMERA message
    lidar_frame_received = pyqtSignal(bytes)  # raw LIDAR message
    raw_message_received = pyqtSignal(str, bytes)  # direction("RX"/"TX"), raw data
    log_message = pyqtSignal(str)  # text log

    def __init__(self):
        super().__init__()
        self._ws: Optional[ServerConnection] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._device_name: str = ""
        self._seq: int = 0
        self._init_ack_settings = InitAckSettings()

    @property
    def connected(self) -> bool:
        return self._ws is not None

    @property
    def device_name(self) -> str:
        return self._device_name

    @property
    def init_ack_settings(self) -> InitAckSettings:
        return self._init_ack_settings

    @init_ack_settings.setter
    def init_ack_settings(self, value: InitAckSettings) -> None:
        self._init_ack_settings = value

    def next_seq(self) -> int:
        seq = self._seq
        self._seq = (self._seq + 1) & 0xFF
        return seq

    def send_command(self, cmd_id: int, payload: bytes = b"") -> None:
        """Send a command to the device (thread-safe)."""
        if not self._ws or not self._loop:
            return
        seq = self.next_seq()
        packet = build_command(cmd_id, seq, payload)
        self.raw_message_received.emit("TX", packet)
        asyncio.run_coroutine_threadsafe(self._send(packet), self._loop)

    def send_raw(self, data: bytes) -> None:
        """Send raw bytes to the device (thread-safe)."""
        if not self._ws or not self._loop:
            return
        self.raw_message_received.emit("TX", data)
        asyncio.run_coroutine_threadsafe(self._send(data), self._loop)

    async def _send(self, data: bytes) -> None:
        if self._ws:
            try:
                await self._ws.send(data)
            except Exception:
                pass

    def disconnect(self) -> None:
        """Close the WebSocket connection from the server side."""
        if self._ws and self._loop:
            asyncio.run_coroutine_threadsafe(self._close(), self._loop)

    async def _close(self) -> None:
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass

    def _set_connection(self, ws: ServerConnection, loop: asyncio.AbstractEventLoop) -> None:
        self._ws = ws
        self._loop = loop

    def _clear_connection(self) -> None:
        self._ws = None


class WebSocketServer(QObject):
    """Asyncio WebSocket server running in a background thread."""

    server_started = pyqtSignal()
    server_failed = pyqtSignal(str)  # error message

    def __init__(self, connection: DeviceConnection, host: str = "0.0.0.0", port: int = 3000):
        super().__init__()
        self._connection = connection
        self._host = host
        self._port = port
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    @property
    def port(self) -> int:
        return self._port

    @port.setter
    def port(self, value: int) -> None:
        self._port = value

    def start(self) -> None:
        if self._running:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None
        self._loop = None

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._setup())
        except OSError as e:
            self._connection.log_message.emit(f"Server start failed: {e}")
            self._running = False
            self.server_failed.emit(str(e))
            return
        self._running = True
        self.server_started.emit()
        self._loop.run_forever()

    async def _setup(self) -> None:
        self._server = await serve(
            self._handle_connection,
            self._host,
            self._port,
            max_size=2**20,  # 1MB max message
        )
        self._connection.log_message.emit(f"WebSocket server listening on {self._host}:{self._port}")

    async def _handle_connection(self, ws: ServerConnection) -> None:
        conn = self._connection
        loop = asyncio.get_running_loop()

        conn.log_message.emit(f"New connection from {ws.remote_address}")

        # First message should be binary INIT
        try:
            first_msg = await asyncio.wait_for(ws.recv(), timeout=10)
        except (asyncio.TimeoutError, Exception) as e:
            conn.log_message.emit(f"Handshake failed: {e}")
            return

        if not isinstance(first_msg, bytes) or len(first_msg) < 1:
            conn.log_message.emit("Handshake failed: expected binary INIT")
            return

        # Parse INIT
        if first_msg[0] == PREFIX_INIT:
            init_msg = parse_init(first_msg)
            if not init_msg:
                conn.log_message.emit("Handshake failed: malformed INIT")
                return
            device_name = init_msg.device_name
            conn.raw_message_received.emit("RX", first_msg)
            conn.log_message.emit(
                f"INIT from '{device_name}' (proto v{init_msg.protocol_version})"
            )
        else:
            # Fallback: legacy TEXT handshake
            if isinstance(first_msg, str):
                device_name = first_msg
            else:
                device_name = first_msg.decode("utf-8", errors="replace")
            conn.log_message.emit(f"Legacy handshake from '{device_name}'")
            init_msg = None

        conn._set_connection(ws, loop)
        conn._device_name = device_name

        # Send INIT_ACK with pre-configured settings
        if init_msg:
            ack_data = conn.init_ack_settings.to_bytes()
            conn.raw_message_received.emit("TX", ack_data)
            try:
                await ws.send(ack_data)
            except Exception as e:
                conn.log_message.emit(f"Failed to send INIT_ACK: {e}")
                conn._clear_connection()
                return

            settings = conn.init_ack_settings
            parts = [f"status_push={settings.status_push_ms}ms"]
            if settings.flags & 0x01:
                parts.append(f"stream={settings.stream_interval_ms}ms")
            if settings.motor_rpm > 0:
                parts.append(f"rpm={settings.motor_rpm}")
            conn.log_message.emit(f"INIT_ACK sent ({', '.join(parts)})")

            # Build initial status bytes for the signal (prefix + 17B)
            initial_status = bytes([PREFIX_STATUS]) + first_msg[3 + first_msg[2]:][:17]
        else:
            initial_status = b""

        conn.device_connected.emit(device_name, initial_status)
        conn.log_message.emit(f"Device connected: {device_name}")

        try:
            async for message in ws:
                try:
                    if isinstance(message, bytes) and len(message) > 0:
                        conn.raw_message_received.emit("RX", message)
                        prefix = message[0]
                        if prefix == PREFIX_RES:
                            conn.response_received.emit(message)
                        elif prefix == PREFIX_STATUS:
                            conn.status_received.emit(message)
                        elif prefix == PREFIX_CAMERA:
                            conn.camera_frame_received.emit(message)
                        elif prefix == PREFIX_LIDAR:
                            conn.lidar_frame_received.emit(message)
                    elif isinstance(message, str):
                        conn.log_message.emit(f"TEXT: {message}")
                except Exception as e:
                    conn.log_message.emit(f"Handler error: {e}")
        except Exception as e:
            conn.log_message.emit(f"Connection error: {e}")
        finally:
            conn._clear_connection()
            conn.device_disconnected.emit()
            conn.log_message.emit(f"Device disconnected: {device_name}")
