import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QGuiApplication, QWindow

from lhub.single_instance import SingleInstanceGuard, restore_window
from lhub.tray import LHubTray

_app = QGuiApplication.instance() or QGuiApplication(sys.argv)


class _FakeWindow:
    def __init__(self, visible=True, states=Qt.WindowState.WindowNoState, visibility=None):
        self._visible = visible
        self._states = states
        self._visibility = visibility
        self.calls = []

    def isVisible(self):
        return self._visible

    def windowStates(self):
        return self._states

    def visibility(self):
        if self._visibility is not None:
            return self._visibility
        if not self._visible:
            return QWindow.Visibility.Hidden
        if self._states & Qt.WindowState.WindowMinimized:
            return QWindow.Visibility.Minimized
        return QWindow.Visibility.Windowed

    def hide(self):
        self._visible = False
        self.calls.append("hide")

    def setWindowStates(self, states):
        self._states = states
        self._visibility = None
        self.calls.append(("setWindowStates", states))

    def show(self):
        self._visible = True
        self.calls.append("show")

    def showNormal(self):
        self._visible = True
        self._states &= ~Qt.WindowState.WindowMinimized
        self._visibility = None
        self.calls.append("showNormal")

    def showMaximized(self):
        self._visible = True
        self._states = (self._states & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowMaximized
        self._visibility = None
        self.calls.append("showMaximized")

    def showFullScreen(self):
        self._visible = True
        self._states = (self._states & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowFullScreen
        self._visibility = None
        self.calls.append("showFullScreen")

    def raise_(self):
        self.calls.append("raise_")

    def requestActivate(self):
        self.calls.append("requestActivate")


class TestSingleInstance(unittest.TestCase):
    def test_secondary_notifies_primary_with_activation_token(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as tmpdir:
            primary = SingleInstanceGuard(app_id="test.lhub.single", runtime_dir=tmpdir)
            self.addCleanup(primary.close)

            self.assertTrue(primary.try_become_primary())

            received_tokens = []
            primary.activationRequested.connect(received_tokens.append)

            secondary = SingleInstanceGuard(app_id="test.lhub.single", runtime_dir=tmpdir)
            self.addCleanup(secondary.close)
            self.assertFalse(secondary.try_become_primary())

            notify_result = []

            def _notify():
                notify_result.append(secondary.notify_primary(activation_token="tok-123"))

            t = threading.Thread(target=_notify)
            t.start()

            deadline = time.monotonic() + 2.0
            while not received_tokens and time.monotonic() < deadline:
                QCoreApplication.processEvents()
                time.sleep(0.01)

            t.join(timeout=2.0)

            self.assertEqual(notify_result, [True])
            self.assertEqual(received_tokens, ["tok-123"])

    def test_close_releases_lock_for_next_primary(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as tmpdir:
            first = SingleInstanceGuard(app_id="test.lhub.release", runtime_dir=tmpdir)
            self.assertTrue(first.try_become_primary())
            first.close()

            second = SingleInstanceGuard(app_id="test.lhub.release", runtime_dir=tmpdir)
            self.addCleanup(second.close)
            self.assertTrue(second.try_become_primary())

    def test_recovers_stale_lock_and_socket_after_crash(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as tmpdir:
            code = (
                "import sys, time\n"
                "from PySide6.QtCore import QCoreApplication\n"
                "from lhub.single_instance import SingleInstanceGuard\n"
                "app = QCoreApplication([])\n"
                f"g = SingleInstanceGuard(app_id='test.lhub.crash', runtime_dir={tmpdir!r})\n"
                "assert g.try_become_primary()\n"
                "print('READY', flush=True)\n"
                "time.sleep(60)\n"
            )
            with subprocess.Popen(
                [sys.executable, "-c", code],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ) as proc:
                try:
                    self.assertEqual(proc.stdout.readline().strip(), "READY")
                    # While alive, cannot take over
                    contender = SingleInstanceGuard(app_id="test.lhub.crash", runtime_dir=tmpdir)
                    self.assertFalse(contender.try_become_primary())
                    contender.close()
                finally:
                    proc.kill()
                    proc.wait(timeout=5)

            # After SIGKILL, stale lock + socket must be recovered immediately
            recovered = SingleInstanceGuard(app_id="test.lhub.crash", runtime_dir=tmpdir)
            self.addCleanup(recovered.close)
            self.assertTrue(recovered.try_become_primary())


class TestRestoreWindow(unittest.TestCase):
    def test_restore_hidden_window(self):
        win = _FakeWindow(visible=False, states=Qt.WindowState.WindowNoState)
        restore_window(win)
        self.assertEqual(win.calls, ["show", "raise_", "requestActivate"])
        self.assertTrue(win.isVisible())

    def test_restore_minimized_window_on_x11(self):
        win = _FakeWindow(visible=True, states=Qt.WindowState.WindowMinimized)
        with patch.object(_app, "platformName", return_value="xcb"):
            restore_window(win)
        self.assertEqual(
            win.calls,
            [
                ("setWindowStates", Qt.WindowState.WindowNoState),
                "showNormal",
                "raise_",
                "requestActivate",
            ],
        )

    def test_restore_minimized_window_on_wayland_remaps_and_sets_token(self):
        win = _FakeWindow(visible=True, states=Qt.WindowState.WindowMinimized)
        prev_token = os.environ.pop("XDG_ACTIVATION_TOKEN", None)
        try:
            with patch.object(_app, "platformName", return_value="wayland"):
                restore_window(win, activation_token="wayland-tok-42")
            self.assertEqual(os.environ.get("XDG_ACTIVATION_TOKEN"), "wayland-tok-42")
            self.assertEqual(
                win.calls,
                [
                    "hide",
                    ("setWindowStates", Qt.WindowState.WindowNoState),
                    "showNormal",
                    "raise_",
                    "requestActivate",
                ],
            )
        finally:
            if prev_token is None:
                os.environ.pop("XDG_ACTIVATION_TOKEN", None)
            else:
                os.environ["XDG_ACTIVATION_TOKEN"] = prev_token

    def test_restore_minimized_maximized_window_preserves_maximized(self):
        win = _FakeWindow(
            visible=True,
            states=Qt.WindowState.WindowMinimized | Qt.WindowState.WindowMaximized,
        )
        with patch.object(_app, "platformName", return_value="xcb"):
            restore_window(win)
        self.assertEqual(
            win.calls,
            [
                ("setWindowStates", Qt.WindowState.WindowMaximized),
                "showMaximized",
                "raise_",
                "requestActivate",
            ],
        )

    def test_restore_already_visible_window_does_not_hide(self):
        win = _FakeWindow(visible=True, states=Qt.WindowState.WindowNoState)
        with patch.object(_app, "platformName", return_value="wayland"):
            restore_window(win)
        self.assertEqual(win.calls, ["raise_", "requestActivate"])

    def test_tray_show_window_uses_restore_window(self):
        tray = LHubTray.__new__(LHubTray)
        tray.window = _FakeWindow(visible=True, states=Qt.WindowState.WindowMinimized)
        with patch("lhub.tray.restore_window") as mock_restore:
            tray._show_window()
            mock_restore.assert_called_once_with(tray.window)


if __name__ == "__main__":
    unittest.main()
