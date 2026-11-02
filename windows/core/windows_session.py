"""Read-only session and input state; failure prevents automatic screen off."""
import ctypes
from ctypes import wintypes


class LastInput(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


class WindowsSession:
    def __init__(self):
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user.GetLastInputInfo.argtypes = [ctypes.POINTER(LastInput)]
        self.user.GetLastInputInfo.restype = wintypes.BOOL
        self.kernel.GetTickCount.restype = wintypes.DWORD
        self.user.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.user.OpenInputDesktop.restype = wintypes.HANDLE
        self.user.CloseDesktop.argtypes = [wintypes.HANDLE]
        self.user.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID,
                                                        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        self.user.GetUserObjectInformationW.restype = wintypes.BOOL

    def input_age(self):
        value = LastInput(ctypes.sizeof(LastInput), 0)
        if not self.user.GetLastInputInfo(ctypes.byref(value)):
            return None
        return ((self.kernel.GetTickCount() - value.dwTime) & 0xffffffff) / 1000

    def locked(self):
        # Read the active input desktop name; never switch or unlock desktops.
        handle = self.user.OpenInputDesktop(0, False, 0x0001)
        if not handle:
            return True
        try:
            name = ctypes.create_unicode_buffer(256)
            needed = wintypes.DWORD()
            if not self.user.GetUserObjectInformationW(handle, 2, name, ctypes.sizeof(name), ctypes.byref(needed)):
                return True
            return name.value.lower() != "default"
        finally:
            self.user.CloseDesktop(handle)
