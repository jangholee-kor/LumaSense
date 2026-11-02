"""Display requests only: no system suspend, locking, or DDC power command."""
import ctypes
from ctypes import wintypes
import sys

WAKE_METHODS = ("monitor_power", "execution_state", "mouse_move")


class MouseInput(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KeyboardInput(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class HardwareInput(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class InputUnion(ctypes.Union):
    _fields_ = [("mi", MouseInput), ("ki", KeyboardInput), ("hi", HardwareInput)]


class Input(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", wintypes.DWORD), ("data", InputUnion)]


class WindowsPower:
    def __init__(self):
        if sys.platform != "win32":
            raise OSError("Windows 전용 기능")
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t,
                                                  ctypes.c_ssize_t, wintypes.UINT, wintypes.UINT,
                                                  ctypes.POINTER(ctypes.c_size_t)]
        self.user.SendMessageTimeoutW.restype = ctypes.c_ssize_t
        self.kernel.SetThreadExecutionState.argtypes = [wintypes.DWORD]
        self.kernel.SetThreadExecutionState.restype = wintypes.DWORD
        self.user.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
        self.user.SendInput.restype = wintypes.UINT

    def monitor_power(self, value):
        result = ctypes.c_size_t()
        ctypes.set_last_error(0)
        accepted = self.user.SendMessageTimeoutW(0xFFFF, 0x0112, 0xF170, value, 0x0002, 1000, ctypes.byref(result))
        if not accepted:
            raise OSError(ctypes.get_last_error(), "SC_MONITORPOWER 시간 초과 또는 실패")
        return {"api": "SC_MONITORPOWER", "value": value, "accepted": True, "physical_result": "unverified"}

    def off(self):
        return self.monitor_power(2)

    def wake(self, method, allow_mouse=False):
        if method == "monitor_power":
            return self.monitor_power(-1)
        if method == "execution_state":
            # One-shot idle timer reset. No persistent sleep-policy change.
            if not self.kernel.SetThreadExecutionState(0x00000002):
                raise ctypes.WinError(ctypes.get_last_error())
        elif method == "mouse_move":
            if not allow_mouse:
                raise ValueError("마우스 이동 복귀는 명시적으로 허용해야 합니다.")
            # No clicks or keys. Relative movement may still affect hovered UI.
            events = (Input * 2)()
            for event, dx in zip(events, (1, -1)):
                event.type = 0
                event.mi = MouseInput(dx, 0, 0, 0x0001, 0, 0)
            if self.user.SendInput(2, events, ctypes.sizeof(Input)) != 2:
                raise ctypes.WinError(ctypes.get_last_error())
        else:
            raise ValueError("지원하지 않는 복귀 방식")
        return {"api": method, "accepted": True, "physical_result": "unverified"}
