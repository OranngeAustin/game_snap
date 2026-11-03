"""toast.py / hotkey.py 共用的 Win32 声明（ctypes，显式 argtypes 保证 64 位下指针不被截断）。"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import itertools

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = wt.LPARAM
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_TIMER = 0x0113
WM_INPUT = 0x00FF
WM_APP = 0x8000

WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.UINT),
        ("style", wt.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
        ("hIconSm", wt.HICON),
    ]


kernel32.GetModuleHandleW.restype = wt.HMODULE
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]

user32.RegisterClassExW.restype = wt.ATOM
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.UnregisterClassW.argtypes = [wt.LPCWSTR, wt.HINSTANCE]
user32.CreateWindowExW.restype = wt.HWND
user32.CreateWindowExW.argtypes = [
    wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID,
]
user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.DestroyWindow.argtypes = [wt.HWND]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]


_class_ids = itertools.count(1)


def unique_class_name(prefix: str) -> str:
    """每个窗口用自己的窗口类：prefix 加上本进程内递增的序号。
    同名的类在一个进程里只能注册一次，之后 CreateWindowExW 用的一直是第一次注册时的窗口过程。
    InputListener 停了还会再建，类名固定的话，新窗口的消息会送进第一个 InputListener 的回调：
    它的状态早就过时了，它被回收之后那个回调更是已释放的内存（docs/review/02-findings.md H1）。"""
    return f"{prefix}_{next(_class_ids)}"


def create_window(class_name: str, wndproc, ex_style: int, style: int = WS_POPUP) -> int:
    """注册窗口类并创建一个（不显示的）窗口，返回 hwnd。
    class_name 每次都要不同（用 unique_class_name），窗口销毁后调用 unregister_class；
    wndproc 需由调用方保持引用。"""
    hinst = kernel32.GetModuleHandleW(None)
    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.lpfnWndProc = wndproc
    wc.hInstance = hinst
    wc.lpszClassName = class_name
    if not user32.RegisterClassExW(ctypes.byref(wc)):
        raise ctypes.WinError(ctypes.get_last_error())
    hwnd = user32.CreateWindowExW(ex_style, class_name, class_name, style,
                                  0, 0, 0, 0, None, None, hinst, None)
    if not hwnd:
        err = ctypes.get_last_error()
        user32.UnregisterClassW(class_name, hinst)
        raise ctypes.WinError(err)
    return hwnd


def unregister_class(class_name: str) -> None:
    """窗口销毁后注销它的窗口类，不在进程里留下挂着旧回调的类。"""
    user32.UnregisterClassW(class_name, kernel32.GetModuleHandleW(None))


def message_loop() -> None:
    msg = wt.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
