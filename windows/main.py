"""Run from repository root: python -m windows.main."""
import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from windows.core.diagnostics import Diagnostics
from windows.core.display_controller import DisplayController
from windows.core.power import WindowsPower
from windows.core.settings import Settings
from windows.ui.main_window import MainWindow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", action="store_true", help="장치 제어 없이 UI를 생성하고 종료")
    parser.add_argument("--screenshot", help="UI PNG 저장 경로 (smoke-test 전용)")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    # Explicit Korean font also makes offscreen render checks reproducible.
    font = Path("C:/Windows/Fonts/malgun.ttf")
    if font.exists():
        QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont("Malgun Gothic", 10))
    app.setApplicationName("Smart Monitor Controller")
    app.setQuitOnLastWindowClosed(False)
    log = Diagnostics()
    lock = QLockFile(str(log.root / "app.lock"))
    if not lock.tryLock(100):
        print("Smart Monitor Controller가 이미 실행 중입니다.", file=sys.stderr)
        return 2
    try:
        settings = Settings.load(log.root / "settings.json")
    except Exception as error:
        log.event("settings_error", error=str(error))
        settings = Settings()
    controller = DisplayController(WindowsPower(), log)
    window = MainWindow(log, settings, controller, auto_scan=not args.smoke_test)
    window.show()
    log.event("app_started", mode="smoke" if args.smoke_test else "live")
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
