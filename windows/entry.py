"""Executable entry point; helpers do not start the Qt GUI."""
import importlib
import sys


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--helper":
        module = sys.argv[2]
        if module not in ("windows.core.watchdog", "windows.core.lease_guard"):
            raise SystemExit("Unsupported helper")
        sys.argv = [sys.argv[0], *sys.argv[3:]]
        return importlib.import_module(module).main()
    from windows.main import main as gui_main
    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
