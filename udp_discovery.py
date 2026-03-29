"""UDP Discovery listener for ESP32 devices.

Listens on port 4200 for broadcast packets from ESP32 devices.
Packet format: "DEVICE_NAME|IP_ADDRESS"
Example: "CORE_DEVICE_f7x4k2|192.168.137.100"
"""

import socket
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable

DISCOVERY_PORT = 4200
DEVICE_TIMEOUT_S = 5.0
BUFFER_SIZE = 256


@dataclass
class DiscoveredDevice:
    """A device found via UDP broadcast."""
    name: str
    ip_address: str
    last_seen: datetime = field(default_factory=datetime.now)


class UdpDiscoveryListener:
    """Listens for ESP32 UDP broadcast discovery packets on port 4200.

    Usage:
        listener = UdpDiscoveryListener()
        listener.on_devices_changed = callback  # called with List[DiscoveredDevice]
        listener.start()
        ...
        listener.stop()
    """

    def __init__(self, port: int = DISCOVERY_PORT):
        self._port = port
        self._socket: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._cleanup_thread: Optional[threading.Thread] = None
        self._running = False
        self._devices: Dict[str, DiscoveredDevice] = {}
        self._lock = threading.Lock()

        # Callback: called with current device list when it changes
        self.on_devices_changed: Optional[Callable[[List[DiscoveredDevice]], None]] = None

    @property
    def devices(self) -> List[DiscoveredDevice]:
        """Current list of discovered devices."""
        with self._lock:
            return list(self._devices.values())

    def start(self) -> bool:
        """Start listening for UDP broadcasts."""
        if self._running:
            return True

        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._socket.settimeout(1.0)  # allow periodic check for stop
            self._socket.bind(("0.0.0.0", self._port))
        except OSError as e:
            print(f"[Discovery] Failed to bind UDP port {self._port}: {e}")
            return False

        self._running = True

        self._thread = threading.Thread(
            target=self._listen_loop, daemon=True, name="udp-discovery"
        )
        self._thread.start()

        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, daemon=True, name="udp-cleanup"
        )
        self._cleanup_thread.start()

        print(f"[Discovery] Listening on UDP port {self._port}")
        return True

    def stop(self) -> None:
        """Stop listening and clean up."""
        self._running = False

        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None

        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=2.0)
            self._cleanup_thread = None

        with self._lock:
            self._devices.clear()

        print("[Discovery] Stopped")

    def _listen_loop(self) -> None:
        """Main receive loop (runs in background thread)."""
        while self._running and self._socket:
            try:
                data, addr = self._socket.recvfrom(BUFFER_SIZE)
            except socket.timeout:
                continue
            except OSError:
                break

            message = data.decode("utf-8", errors="ignore").strip()
            device = self._parse_packet(message)
            if device is None:
                continue

            changed = False
            with self._lock:
                existing = self._devices.get(device.name)
                if existing is None or existing.ip_address != device.ip_address:
                    changed = True
                self._devices[device.name] = device

            if changed:
                print(f"[Discovery] Found: {device.name} @ {device.ip_address}")

            self._notify()

    def _cleanup_loop(self) -> None:
        """Periodically remove stale devices."""
        while self._running:
            time.sleep(2.0)

            now = datetime.now()
            timeout = timedelta(seconds=DEVICE_TIMEOUT_S)
            removed = []

            with self._lock:
                for name, dev in list(self._devices.items()):
                    if now - dev.last_seen > timeout:
                        del self._devices[name]
                        removed.append(name)

            for name in removed:
                print(f"[Discovery] Device timed out: {name}")

            if removed:
                self._notify()

    @staticmethod
    def _parse_packet(message: str) -> Optional[DiscoveredDevice]:
        """Parse 'DEVICE_NAME|IP_ADDRESS' packet."""
        parts = message.split("|")
        if len(parts) != 2:
            return None

        name = parts[0].strip()
        ip = parts[1].strip()
        if not name or not ip:
            return None

        return DiscoveredDevice(name=name, ip_address=ip)

    def send_connect(self, device_ip: str, server_ip: str, server_port: int) -> bool:
        """Send CONNECT|server_ip:server_port to a device via UDP unicast."""
        message = f"CONNECT|{server_ip}:{server_port}"
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(message.encode("utf-8"), (device_ip, self._port))
            sock.close()
            print(f"[Discovery] Sent CONNECT to {device_ip}: {message}")
            return True
        except OSError as e:
            print(f"[Discovery] Failed to send CONNECT to {device_ip}: {e}")
            return False

    def _notify(self) -> None:
        """Notify callback with current device list."""
        if self.on_devices_changed:
            self.on_devices_changed(self.devices)
