import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QDir, QLockFile, QObject, QStandardPaths, Qt, Signal
from PySide6.QtGui import QGuiApplication, QWindow
from PySide6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger(__name__)

DEFAULT_APP_ID = "io.github.lhub.LHub"
MAX_MESSAGE_BYTES = 4096


def _default_runtime_dir() -> Path:
    runtime_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.RuntimeLocation)
    if runtime_dir:
        return Path(runtime_dir)
    return Path(QDir.tempPath()) / f"lhub-{os.getuid()}"


def restore_window(window, activation_token: Optional[str] = None) -> None:
    """Restore a hidden, minimized, or background window and bring it to the front."""
    if window is None:
        return

    if activation_token:
        os.environ["XDG_ACTIVATION_TOKEN"] = activation_token

    states = window.windowStates()
    is_minimized = bool(states & Qt.WindowState.WindowMinimized)
    if not is_minimized and hasattr(window, "visibility"):
        is_minimized = window.visibility() == QWindow.Visibility.Minimized

    if is_minimized:
        new_states = states & ~Qt.WindowState.WindowMinimized
        app = QGuiApplication.instance()
        if isinstance(app, QGuiApplication) and app.platformName().startswith("wayland"):
            # Wayland's xdg-shell has no unset_minimized request; re-mapping the
            # surface ensures the compositor unminimizes even without a token.
            window.hide()
        window.setWindowStates(new_states)
        if bool(new_states & Qt.WindowState.WindowFullScreen):
            window.showFullScreen()
        elif bool(new_states & Qt.WindowState.WindowMaximized):
            window.showMaximized()
        else:
            window.showNormal()
    elif not window.isVisible():
        window.show()

    window.raise_()
    window.requestActivate()


class SingleInstanceGuard(QObject):
    """Ensures only one L-Hub instance runs per user session and forwards activations."""

    activationRequested = Signal(str)

    def __init__(
        self,
        app_id: str = DEFAULT_APP_ID,
        runtime_dir: Optional[str | Path] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        base_dir = Path(runtime_dir) if runtime_dir is not None else _default_runtime_dir()
        self._base_dir = base_dir
        self._lock_path = str(base_dir / f"{app_id}.lock")
        self._socket_path = str(base_dir / f"{app_id}.sock")
        self._lock = QLockFile(self._lock_path)
        self._lock.setStaleLockTime(0)
        self._server: Optional[QLocalServer] = None
        self._buffers: dict[QLocalSocket, bytearray] = {}

    @property
    def lock_path(self) -> str:
        return self._lock_path

    @property
    def socket_path(self) -> str:
        return self._socket_path

    def try_become_primary(self) -> bool:
        self._base_dir.mkdir(parents=True, exist_ok=True)
        if not self._lock.tryLock(0):
            return False

        QLocalServer.removeServer(self._socket_path)
        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not server.listen(self._socket_path):
            logger.warning(
                "Could not listen on instance socket %s: %s",
                self._socket_path,
                server.errorString(),
            )
            server.deleteLater()
            return True

        server.newConnection.connect(self._on_new_connection)
        self._server = server
        return True

    def notify_primary(
        self,
        activation_token: Optional[str] = None,
        timeout_ms: int = 1000,
    ) -> bool:
        token = os.environ.get("XDG_ACTIVATION_TOKEN", "") if activation_token is None else activation_token
        payload = (json.dumps({"action": "activate", "token": token}) + "\n").encode("utf-8")
        deadline = time.monotonic() + (timeout_ms / 1000.0)

        while True:
            sock = QLocalSocket()
            sock.connectToServer(self._socket_path)
            if sock.waitForConnected(200):
                sock.write(payload)
                sock.flush()
                sock.waitForBytesWritten(500)
                sock.waitForReadyRead(300)
                sock.disconnectFromServer()
                sock.close()
                return True

            sock.abort()
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)

    def _on_new_connection(self) -> None:
        if self._server is None:
            return
        while self._server.hasPendingConnections():
            client = self._server.nextPendingConnection()
            if client is None:
                continue
            self._buffers[client] = bytearray()
            client.readyRead.connect(lambda c=client: self._on_client_ready_read(c))
            client.disconnected.connect(lambda c=client: self._on_client_disconnected(c))
            if client.bytesAvailable() > 0:
                self._on_client_ready_read(client)

    def _on_client_ready_read(self, client: QLocalSocket) -> None:
        buf = self._buffers.get(client)
        if buf is None:
            return
        buf.extend(bytes(client.readAll()))
        if b"\n" in buf or len(buf) >= MAX_MESSAGE_BYTES:
            self._finalize_client(client)

    def _on_client_disconnected(self, client: QLocalSocket) -> None:
        if client in self._buffers:
            self._finalize_client(client)
        client.deleteLater()

    def _finalize_client(self, client: QLocalSocket) -> None:
        raw = bytes(self._buffers.pop(client, bytearray()))
        token = ""
        line = raw.split(b"\n", 1)[0].strip()
        if line:
            try:
                data = json.loads(line.decode("utf-8"))
                if isinstance(data, dict) and isinstance(data.get("token"), str):
                    token = data["token"]
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                logger.debug("Ignoring invalid activation message: %s", exc)

        self.activationRequested.emit(token)

        if client.state() == QLocalSocket.LocalSocketState.ConnectedState:
            client.write(b"ok\n")
            client.flush()
            client.disconnectFromServer()

    def close(self) -> None:
        for client in list(self._buffers.keys()):
            client.abort()
            client.deleteLater()
        self._buffers.clear()

        if self._server is not None:
            self._server.close()
            self._server.deleteLater()
            self._server = None

        if self._lock.isLocked():
            QLocalServer.removeServer(self._socket_path)
            self._lock.unlock()
