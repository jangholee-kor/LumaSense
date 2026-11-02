"""Run from repository root: python -m windows.main."""
import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from windows.core.diagnostics import Diagnostics
from windows.core.diagnostics import data_dir
from windows.core.display_controller import DisplayController
from windows.core.power import WindowsPower
from windows.core.settings import Settings
from windows.core.simulation import SimulatedPower
from windows.core.watchdog import arm_watchdog
from windows.ui.main_window import MainWindow
from windows import __version__
import traceback


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", action="store_true", help="장치 제어 없이 UI를 생성하고 종료")
    parser.add_argument("--screenshot", help="UI PNG 저장 경로 (smoke-test 전용)")
    parser.add_argument("--simulate", action="store_true", help="가상 센서와 제어 백엔드로 실행")
    parser.add_argument("--minimized", action="store_true", help="트레이로 시작")
    args = parser.parse_args()
    if args.screenshot and not args.smoke_test:
        parser.error("--screenshot은 --smoke-test와 함께 사용하세요.")
    app = QApplication(sys.argv[:1])
    # Explicit Korean font also makes offscreen render checks reproducible.
    font = Path("C:/Windows/Fonts/malgun.ttf")
    if font.exists():
        QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont("Malgun Gothic", 10))
    app.setApplicationName("Smart Monitor Controller")
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)
    root = data_dir()
    mode_dir = "simulation" if args.simulate else ("smoke" if args.smoke_test else None)
    if mode_dir and root.name != mode_dir:
        root = root / mode_dir
    log = Diagnostics(root)
    lock = QLockFile(str(log.root / "app.lock"))
    if not lock.tryLock(100):
        print("Smart Monitor Controller가 이미 실행 중입니다.", file=sys.stderr)
        return 2
    try:
        settings = Settings.load(log.root / "settings.json")
    except Exception as error:
        log.event("settings_error", error=str(error))
        settings = Settings()
    if args.smoke_test:
        settings.auto_presence = settings.auto_brightness = settings.connect_on_start = False
    safe_mode = args.simulate or args.smoke_test
    controller = DisplayController(SimulatedPower() if safe_mode else WindowsPower(), log,
                                   **({"arm": lambda *values: arm_watchdog(*values, simulate=True)} if safe_mode else {}))
    window = MainWindow(log, settings, controller, auto_scan=not args.smoke_test, simulation=safe_mode)
    def exception_hook(kind, value, tb):
        log.event("unhandled_exception", error=str(value), traceback="".join(traceback.format_exception(kind, value, tb)))
        window.runtime.external_block = True
        window.auto_fault = True
        window.fail(f"예외로 자동 제어를 중단했습니다: {value}")
    sys.excepthook = exception_hook
    app.aboutToQuit.connect(window.stop_services)
    window.show()
    if not args.smoke_test and (args.minimized or settings.start_minimized):
        window.hide_to_tray()
    log.event("app_started", version=__version__, mode="smoke" if args.smoke_test else ("simulation" if args.simulate else "live"))
    if args.smoke_test:
        def finish():
            if args.screenshot:
                window.grab().save(args.screenshot)
            window.quitting = True
            app.quit()
        QTimer.singleShot(700, finish)
    result = app.exec()
    log.event("app_stopped", code=result)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
