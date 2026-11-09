"""One LiveTranslate instance per Windows desktop session."""
import ctypes
import time
from ctypes import wintypes

NAME = r'Local\LiveTranslate.SingleInstance.1'
WINDOW_PROPERTY = 'LiveTranslate.MainWindow.1'
ERROR_ALREADY_EXISTS = 183

kernel = ctypes.WinDLL('kernel32', use_last_error=True)
user = ctypes.WinDLL('user32', use_last_error=True)
kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel.CreateMutexW.restype = wintypes.HANDLE
kernel.CloseHandle.argtypes = [wintypes.HANDLE]
kernel.CloseHandle.restype = wintypes.BOOL
user.GetParent.argtypes = [wintypes.HWND]
user.GetParent.restype = wintypes.HWND
user.SetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.HANDLE]
user.SetPropW.restype = wintypes.BOOL
user.GetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
user.GetPropW.restype = wintypes.HANDLE
user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user.SetForegroundWindow.argtypes = [wintypes.HWND]
ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user.EnumWindows.argtypes = [ENUMPROC, wintypes.LPARAM]
user.EnumWindows.restype = wintypes.BOOL


class SingleInstance:
    def __init__(self, name=NAME):
        ctypes.set_last_error(0)
        self.handle = kernel.CreateMutexW(None, False, name)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.is_primary = ctypes.get_last_error() != ERROR_ALREADY_EXISTS

    def close(self):
        if self.handle:
            kernel.CloseHandle(self.handle)
            self.handle = None


def register_window(root):
    root.update_idletasks()
    hwnd = user.GetParent(root.winfo_id()) or root.winfo_id()
    if not user.SetPropW(hwnd, WINDOW_PROPERTY, 1):
        raise ctypes.WinError(ctypes.get_last_error())


def activate_existing():
    found = []
    @ENUMPROC
    def visit(hwnd, _):
        if user.GetPropW(hwnd, WINDOW_PROPERTY):
            found.append(hwnd)
            return False
        return True
    # The first process may still be creating its window.
    for _ in range(30):
        user.EnumWindows(visit, 0)
        if found:
            user.ShowWindow(found[0], 9)  # Restore a minimized window.
            user.SetForegroundWindow(found[0])
            return True
        time.sleep(0.1)
    return False
