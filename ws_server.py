"""WebSocket server that accepts ESP32 device connections and bridges to Qt GUI."""

import asyncio
import socket
import threading
import time
from typing import Optional

from websockets.asyncio.server import serve, ServerConnection
from websockets.exceptions import ConnectionClosed

from PyQt6.QtCore import QObject, pyqtSignal

from protocol import (
    MAX_DEVICE_NAME_BYTES,
    MAX_PACKET_SIZE,
    PREFIX_INIT,
    PREFIX_RES,
    PREFIX_STATUS,
    PREFIX_CAMERA,
    PREFIX_LIDAR,
    PREFIX_IMU,
    PREFIX_SD_CHUNK,
    PROTOCOL_VERSION,
    DeviceStatus,
    InitAckSettings,
    parse_init,
    parse_response,
    parse_status,
    parse_lidar_frame,
    parse_imu_frame,
    parse_sd_chunk,
    build_command,
)

DEVICE_MESSAGE_TIMEOUT_S = 20.0
PING_INTERVAL_S = 30.0
PING_TIMEOUT_S = 30.0


class DeviceConnection(QObject):
    """Manages a single device WebSocket connection with Qt signals."""

    # Signals emitted on the main (GUI) thread
    device_connected = pyqtSignal(str, bytes)  # device_name, initial status bytes
    device_disconnected = pyqtSignal()
    response_received = pyqtSignal(bytes)  # raw RES message
    status_received = pyqtSignal(bytes)  # raw STATUS message (prefix + 22B DeviceStatus)
    camera_frame_received = pyqtSignal(bytes)  # raw CAMERA message
    lidar_frame_received = pyqtSignal(bytes)  # raw LIDAR message
    imu_frame_received = pyqtSignal(bytes)  # raw IMU message
    sd_chunk_received = pyqtSignal(bytes)  # raw SD file chunk
    raw_message_received = pyqtSignal(str, bytes)  # direction("RX"/"TX"), raw data
    log_message = pyqtSignal(str)  # text log

    def __init__(self):
        super().__init__()
        self._ws: Optional[ServerConnection] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._device_name: str = ""
        self._seq: int = 0
        self._conn_id: int = 0  # incremented on each new connection
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

    def send_command(self, cmd_id: int, payload: bytes = b"") -> int | None:
        """Send a command to the device (thread-safe)."""
        ws = self._ws
        loop = self._loop
        if not ws or not loop:
            return None
        seq = self.next_seq()
        try:
            packet = build_command(cmd_id, seq, payload)
        except (TypeError, ValueError) as e:
            self.log_message.emit(f"Command build failed: {e}")
            return None
        self.raw_message_received.emit("TX", packet)
        self._schedule_send(ws, loop, packet)
        return seq

    def send_raw(self, data: bytes) -> None:
        """Send raw bytes to the device (thread-safe)."""
        ws = self._ws
        loop = self._loop
        if not ws or not loop:
            return
        if not isinstance(data, (bytes, bytearray, memoryview)):
            self.log_message.emit("Raw send failed: data must be bytes-like")
            return
        data = bytes(data)
        if len(data) > MAX_PACKET_SIZE:
            self.log_message.emit(f"Raw send failed: packet exceeds {MAX_PACKET_SIZE} bytes")
            return
        self.raw_message_received.emit("TX", data)
        self._schedule_send(ws, loop, data)

    def _schedule_send(
        self,
        ws: ServerConnection,
        loop: asyncio.AbstractEventLoop,
        data: bytes,
    ) -> None:
        try:
            future = asyncio.run_coroutine_threadsafe(self._send(ws, data), loop)
        except RuntimeError:
            return
        future.add_done_callback(self._send_done)

    def _send_done(self, future) -> None:
        try:
            future.result()
        except Exception as e:
            self.log_message.emit(f"Send failed: {e}")

    async def _send(self, ws: ServerConnection, data: bytes) -> None:
        if self._ws is ws:
            await ws.send(data)

    def disconnect(self) -> None:
        """Close the WebSocket connection from the server side."""
        if self._ws and self._loop:
            try:
                asyncio.run_coroutine_threadsafe(self._close(), self._loop)
            except RuntimeError:
                pass  # event loop closed

    async def _close(self) -> None:
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass

    def _set_connection(self, ws: ServerConnection, loop: asyncio.AbstractEventLoop) -> int:
        # Close previous connection if still active
        old_ws = self._ws
        if old_ws and old_ws != ws:
            asyncio.ensure_future(self._force_close(old_ws), loop=loop)
        self._ws = ws
        self._loop = loop
        self._conn_id += 1
        return self._conn_id

    def _clear_connection(self, conn_id: int) -> bool:
        """Clear connection only if conn_id matches current. Returns True if cleared."""
        if conn_id == self._conn_id:
            self._ws = None
            self._loop = None
            self._device_name = ""
            return True
        return False  # stale disconnect, ignore

    @staticmethod
    async def _force_close(ws: ServerConnection) -> None:
        try:
            await ws.close()
        except Exception:
            pass


class WebSocketServer(QObject):
    """Asyncio WebSocket server running in a background thread."""

    server_started = pyqtSignal()
    server_stopped = pyqtSignal()  # emitted when server stops (crash or manual)
    server_failed = pyqtSignal(str)  # error message

    def __init__(self, connection: DeviceConnection, host: str = "0.0.0.0", port: int = 3421):
        super().__init__()
        self._connection = connection
        self._host = host
        self._port = port
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._server = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @port.setter
    def port(self, value: int) -> None:
        self._port = value

    def start(self) -> None:
        if self._running or self._thread:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._running and not self._thread:
            return
        self._running = False
        loop = self._loop
        thread = self._thread
        if loop and loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(self._shutdown(), loop)
                future.result(timeout=3)
            except Exception as e:
                self._connection.log_message.emit(f"Server shutdown warning: {e}")
                loop.call_soon_threadsafe(loop.stop)
        if thread and thread is not threading.current_thread():
            thread.join(timeout=3)
        self._thread = None
        self._loop = None
        self._server = None
        self.server_stopped.emit()

    async def _shutdown(self) -> None:
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        if self._connection._ws:
            try:
                await self._connection._ws.close()
            except Exception:
                pass
        self._connection._clear_connection(self._connection._conn_id)

        loop = asyncio.get_running_loop()
        current = asyncio.current_task(loop)
        pending = [task for task in asyncio.all_tasks(loop) if task is not current and not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        loop.call_soon(loop.stop)

    def restart(self) -> None:
        """Stop and restart the server after socket release."""
        self.stop()
        import time
        time.sleep(0.3)
        self.start()

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._setup())
        except Exception as e:
            self._connection.log_message.emit(f"Server start failed: {e}")
            self._running = False
            self.server_failed.emit(str(e))
            loop.close()
            return
        self.server_started.emit()
        try:
            loop.run_forever()
        except Exception as e:
            self._connection.log_message.emit(f"Server crashed: {e}")
        finally:
            loop.close()
            if self._running:
                # Loop exited unexpectedly
                self._running = False
                self._connection._clear_connection(self._connection._conn_id)
                self._connection.log_message.emit("Server stopped unexpectedly")
                self.server_stopped.emit()

    async def _setup(self) -> None:
        # Create socket with SO_REUSEADDR to allow quick restart
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self._host, self._port))
            sock.listen()
            sock.setblocking(False)

            self._server = await serve(
                self._handle_connection,
                sock=sock,
                max_size=2**20,  # 1MB max message
                ping_interval=PING_INTERVAL_S,
                ping_timeout=PING_TIMEOUT_S,
                close_timeout=3,
            )
        except Exception:
            sock.close()
            raise
        self._connection.log_message.emit(f"WebSocket server listening on {self._host}:{self._port}")

    def _validate_device_message(self, message: bytes) -> bool:
        conn = self._connection
        if not isinstance(message, (bytes, bytearray, memoryview)):
            conn.log_message.emit("Dropped non-binary device message")
            return False
        message = bytes(message)
        if len(message) == 0:
            conn.log_message.emit("Dropped empty binary message")
            return False
        if len(message) > MAX_PACKET_SIZE:
            conn.log_message.emit(f"Dropped oversized binary message ({len(message)} bytes)")
            return False
        prefix = message[0]
        if prefix == PREFIX_RES:
            if parse_response(message):
                return True
            conn.log_message.emit(f"Dropped malformed RES ({len(message)} bytes)")
        elif prefix == PREFIX_STATUS:
            if parse_status(message):
                return True
            conn.log_message.emit(f"Dropped malformed STATUS ({len(message)} bytes)")
        elif prefix == PREFIX_CAMERA:
            if len(message) >= 2:
                return True
            conn.log_message.emit("Dropped empty CAMERA frame")
        elif prefix == PREFIX_LIDAR:
            if parse_lidar_frame(message):
                return True
            conn.log_message.emit(f"Dropped malformed LIDAR frame ({len(message)} bytes)")
        elif prefix == PREFIX_IMU:
            if parse_imu_frame(message):
                return True
            conn.log_message.emit(f"Dropped malformed IMU frame ({len(message)} bytes)")
        elif prefix == PREFIX_SD_CHUNK:
            if parse_sd_chunk(message):
                return True
            conn.log_message.emit(f"Dropped malformed SD_CHUNK ({len(message)} bytes)")
        else:
            conn.log_message.emit(f"Dropped unknown binary prefix 0x{prefix:02X} ({len(message)} bytes)")
        return False

    @staticmethod
    def _valid_device_name(name: str) -> bool:
        if not name:
            return False
        if len(name.encode("utf-8")) > MAX_DEVICE_NAME_BYTES:
            return False
        return not any(ord(ch) < 32 for ch in name)

    async def _close_bad_handshake(self, ws: ServerConnection, reason: str) -> None:
        try:
            await ws.close(code=1002, reason=reason[:120])
        except Exception:
            pass

    async def _handle_connection(self, ws: ServerConnection) -> None:
        conn = self._connection
        loop = asyncio.get_running_loop()

        conn.log_message.emit(f"New connection from {ws.remote_address}")

        # First message should be binary INIT
        try:
            first_msg = await asyncio.wait_for(ws.recv(), timeout=10)
        except asyncio.TimeoutError:
            conn.log_message.emit("Handshake failed: timed out waiting for INIT")
            await self._close_bad_handshake(ws, "INIT timeout")
            return
        except Exception as e:
            conn.log_message.emit(f"Handshake failed: {e}")
            return

        if isinstance(first_msg, bytes) and len(first_msg) < 1:
            conn.log_message.emit("Handshake failed: empty binary message")
            await self._close_bad_handshake(ws, "empty INIT")
            return

        # Parse INIT
        if isinstance(first_msg, bytes) and first_msg[0] == PREFIX_INIT:
            conn.raw_message_received.emit("RX", first_msg)
            init_msg = parse_init(first_msg)
            if not init_msg:
                conn.log_message.emit("Handshake failed: malformed INIT")
                await self._close_bad_handshake(ws, "malformed INIT")
                return
            if init_msg.protocol_version != PROTOCOL_VERSION:
                conn.log_message.emit(
                    f"Handshake failed: protocol v{init_msg.protocol_version} != v{PROTOCOL_VERSION}"
                )
                await self._close_bad_handshake(ws, "unsupported protocol")
                return
            device_name = init_msg.device_name
            if not self._valid_device_name(device_name):
                conn.log_message.emit("Handshake failed: invalid device name")
                await self._close_bad_handshake(ws, "invalid device name")
                return
            conn.log_message.emit(
                f"INIT from '{device_name}' (proto v{init_msg.protocol_version})"
            )
        elif isinstance(first_msg, str):
            # Fallback: legacy TEXT handshake
            device_name = first_msg.strip()
            if not self._valid_device_name(device_name):
                conn.log_message.emit("Handshake failed: invalid legacy device name")
                await self._close_bad_handshake(ws, "invalid device name")
                return
            conn.log_message.emit(f"Legacy handshake from '{device_name}'")
            init_msg = None
        else:
            conn.log_message.emit("Handshake failed: expected binary INIT")
            await self._close_bad_handshake(ws, "expected binary INIT")
            return

        conn_id = conn._set_connection(ws, loop)
        conn._device_name = device_name

        # Send INIT_ACK with pre-configured settings
        if init_msg:
            ack_data = conn.init_ack_settings.to_bytes()
            conn.raw_message_received.emit("TX", ack_data)
            try:
                await ws.send(ack_data)
            except Exception as e:
                conn.log_message.emit(f"Failed to send INIT_ACK: {e}")
                conn._clear_connection(conn_id)
                return

            settings = conn.init_ack_settings
            parts = [f"status_push={settings.status_push_ms}ms"]
            if settings.flags & 0x01:
                parts.append(f"stream={settings.stream_interval_ms}ms")
            if settings.motor_rpm > 0:
                parts.append(f"rpm={settings.motor_rpm}")
            conn.log_message.emit(f"INIT_ACK sent ({', '.join(parts)})")

            # Build initial status bytes for the signal (prefix + DeviceStatus)
            initial_status = bytes([PREFIX_STATUS]) + first_msg[
                3 + first_msg[2] : 3 + first_msg[2] + DeviceStatus.STRUCT_SIZE
            ]
        else:
            initial_status = b""

        conn.device_connected.emit(device_name, initial_status)
        conn.log_message.emit(f"Device connected: {device_name}")
        last_traffic_timeout_log = 0.0

        try:
            while True:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=DEVICE_MESSAGE_TIMEOUT_S)
                    last_traffic_timeout_log = 0.0
                    if isinstance(message, bytes):
                        if not self._validate_device_message(message):
                            continue
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
                        elif prefix == PREFIX_IMU:
                            conn.imu_frame_received.emit(message)
                        elif prefix == PREFIX_SD_CHUNK:
                            conn.sd_chunk_received.emit(message)
                    elif isinstance(message, str):
                        conn.log_message.emit(f"TEXT: {message}")
                except asyncio.TimeoutError:
                    now = time.monotonic()
                    if now - last_traffic_timeout_log >= DEVICE_MESSAGE_TIMEOUT_S:
                        conn.log_message.emit(
                            f"No protocol traffic for {int(DEVICE_MESSAGE_TIMEOUT_S)}s; keeping WebSocket open"
                        )
                        last_traffic_timeout_log = now
                    continue
                except (asyncio.CancelledError, GeneratorExit):
                    break
                except ConnectionClosed:
                    break
                except Exception as e:
                    conn.log_message.emit(f"Message processing error: {e}")
                    break
        except (asyncio.CancelledError, GeneratorExit):
            pass
        except Exception as e:
            conn.log_message.emit(f"WebSocket connection error: {e}")
        finally:
            if conn._clear_connection(conn_id):
                conn.device_disconnected.emit()
                conn.log_message.emit(f"Device disconnected: {device_name}")
            else:
                conn.log_message.emit(f"Stale connection cleaned up: {device_name}")
