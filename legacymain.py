from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import types

# Win10 fallback: avoid hardware-accelerated OpenGL issues on older drivers.
os.environ.setdefault("QT_OPENGL", "software")



def _install_pyuac_fallback() -> None:
    """Provide a minimal pyuac-compatible shim for legacy mode.

    This intentionally overrides any installed pyuac package so legacy mode
    never depends on pywin32 modules like win32con.
    """

    shim = types.ModuleType("pyuac")

    def isUserAdmin() -> bool:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def runAsAdmin(cmdLine=None, wait: bool = False) -> None:
        if cmdLine is None:
            cmdLine = [sys.executable, *sys.argv]
        if not cmdLine:
            raise RuntimeError("No command line provided for elevation")

        exe = str(cmdLine[0])
        params = " ".join(subprocess.list2cmdline([str(part)]) for part in cmdLine[1:])
        show_cmd = 1
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, show_cmd)
        if int(result) <= 32:
            raise RuntimeError(f"ShellExecuteW failed with code {int(result)}")

        if wait:
            # pyuac supports wait=True, but this legacy shim does not track the process handle.
            return

    shim.isUserAdmin = isUserAdmin
    shim.runAsAdmin = runAsAdmin
    sys.modules["pyuac"] = shim


_install_pyuac_fallback()

import main as limbo_main
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication


if __name__ == "__main__":
    debug_mode = "--debug" in sys.argv
    if debug_mode:
        limbo_main._enable_debug_console_windows()
    else:
        limbo_main._suppress_console_output()

    app = QApplication(sys.argv)
    controller = limbo_main.MainController(debug_mode=debug_mode)

    def _force_shutdown() -> None:
        controller.allow_close = True
        controller.disable_opening_settings = True
        controller.setting_window_opened = True
        controller.audio.stop()
        controller._hide_focus_overlay()
        if controller.focus_overlay is not None:
            controller.focus_overlay.close()
        for window in list(controller.window_list):
            window.close()
        app.quit()

    def _handle_sigint(_signum, _frame) -> None:
        QTimer.singleShot(0, _force_shutdown)

    signal.signal(signal.SIGINT, _handle_sigint)
    sigint_pump = QTimer()
    sigint_pump.timeout.connect(lambda: None)
    sigint_pump.start(120)
    app._sigint_pump = sigint_pump

    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        _force_shutdown()
        sys.exit(130)
