"""Core Device Test Client - PyQt6 GUI with WebSocket server."""

import sys
import os

# Add this directory to path for local imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication

from ws_server import DeviceConnection, WebSocketServer
from udp_discovery import UdpDiscoveryListener
from gui.main_window import MainWindow
import settings


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Core Device Test Client")

    saved = settings.load()

    # Create shared connection object (bridges WS server ↔ GUI)
    connection = DeviceConnection()

    # Server auto-starts — devices connect via UDP CONNECT command
    server = WebSocketServer(connection, host="0.0.0.0", port=saved.get("server_port", 3000))
    server.start()

    # UDP Discovery listener — starts immediately to find devices
    discovery = UdpDiscoveryListener()
    discovery.start()

    # Create and show main window
    window = MainWindow(connection, server, discovery)
    window.show()

    exit_code = app.exec()
    discovery.stop()
    server.stop()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
