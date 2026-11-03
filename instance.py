"""单实例：同一时间只运行一个 GameSnap。

两个快捷方式可能先后启动 GameSnap（例如先开云原神、再开米哈游启动器），这时：
  - 新的有管理员权限、正在运行的没有 → 让正在运行的退出，由新的接管。
    原神以管理员身份运行，普通权限的 GameSnap 在原神里收不到按键；
  - 其他情况 → 正在运行的那个已经够用，新的只负责拉起游戏/启动器，然后退出。
命名对象都用“所有人可访问、低完整性”的安全描述符，普通权限和管理员权限的实例才能互相打开。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import threading
from typing import Callable

log = logging.getLogger(__name__)

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

MUTEX_NAME = "Local\\GameSnap_SingleInstance"
ELEVATED_NAME = "Local\\GameSnap_Elevated"   # 正在运行的实例有管理员权限时才存在
QUIT_EVENT_NAME = "Local\\GameSnap_Quit"
TAKEOVER_TIMEOUT_MS = 8000
_SDDL_OPEN_TO_ALL = "D:(A;;GA;;;WD)S:(ML;;NW;;;LW)"

ERROR_ACCESS_DENIED = 5
ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0
WAIT_ABANDONED = 0x80
INFINITE = 0xFFFFFFFF
SYNCHRONIZE = 0x00100000
EVENT_MODIFY_STATE = 0x0002


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("nLength", wt.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", wt.BOOL)]


_LPSA = ctypes.POINTER(SECURITY_ATTRIBUTES)
_advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
    wt.LPCWSTR, wt.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
_k32.CreateMutexW.restype = wt.HANDLE
_k32.CreateMutexW.argtypes = [_LPSA, wt.BOOL, wt.LPCWSTR]
_k32.OpenMutexW.restype = wt.HANDLE
_k32.OpenMutexW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
_k32.CreateEventW.restype = wt.HANDLE
_k32.CreateEventW.argtypes = [_LPSA, wt.BOOL, wt.BOOL, wt.LPCWSTR]
_k32.OpenEventW.restype = wt.HANDLE
_k32.OpenEventW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
_k32.SetEvent.argtypes = [wt.HANDLE]
_k32.WaitForSingleObject.restype = wt.DWORD
_k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
_k32.CloseHandle.argtypes = [wt.HANDLE]


def _open_to_all() -> SECURITY_ATTRIBUTES:
    sd = ctypes.c_void_p()
    if not _advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            _SDDL_OPEN_TO_ALL, 1, ctypes.byref(sd), None):
        raise ctypes.WinError(ctypes.get_last_error())
    # sd 进程退出前一直要用，不 LocalFree
    return SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), sd, False)


class Instance:
    """本进程在“单实例”里的身份。必须在主线程创建，并且由主线程调用 take_over（互斥体归线程所有）。"""

    def __init__(self, elevated: bool) -> None:
        self.elevated = elevated
        self._sa = _open_to_all()
        ctypes.set_last_error(0)
        # 第一个实例由主线程持有这个互斥体，进程退出时自动放弃，接管的新实例就能拿到
        self._mutex = _k32.CreateMutexW(ctypes.byref(self._sa), True, MUTEX_NAME)
        err = ctypes.get_last_error()
        # 拒绝访问：正在运行的是旧版建的（只有管理员能打开），也当作已在运行
        self.already_running = err in (ERROR_ALREADY_EXISTS, ERROR_ACCESS_DENIED) or not self._mutex
        self._marks: list[int] = []

    def other_is_elevated(self) -> bool:
        h = _k32.OpenMutexW(SYNCHRONIZE, False, ELEVATED_NAME)
        if h:
            _k32.CloseHandle(h)
        return bool(h)

    def should_take_over(self) -> bool:
        return self.already_running and self.elevated and bool(self._mutex) and not self.other_is_elevated()

    def take_over(self) -> bool:
        """让正在运行的实例退出，等它放开互斥体。成功后本实例就是唯一的那个。"""
        ev = _k32.OpenEventW(EVENT_MODIFY_STATE, False, QUIT_EVENT_NAME)
        if not ev:
            log.error("打不开退出信号 err=%d", ctypes.get_last_error())
            return False
        _k32.SetEvent(ev)
        _k32.CloseHandle(ev)
        r = _k32.WaitForSingleObject(self._mutex, TAKEOVER_TIMEOUT_MS)
        if r in (WAIT_OBJECT_0, WAIT_ABANDONED):
            self.already_running = False
            return True
        log.error("正在运行的 GameSnap 在 %d 秒内没有退出（Wait 返回 %#x）", TAKEOVER_TIMEOUT_MS // 1000, r)
        return False

    def serve(self, on_quit: Callable[[], None]) -> None:
        """作为正在运行的实例：标明自己的权限，并在后台等待“请退出”信号（由有管理员权限的新实例发出）。"""
        if self.elevated:
            self._marks.append(_k32.CreateMutexW(ctypes.byref(self._sa), False, ELEVATED_NAME))
        ev = _k32.CreateEventW(ctypes.byref(self._sa), False, False, QUIT_EVENT_NAME)
        if not ev:
            log.error("创建退出信号失败 err=%d，将无法被管理员权限的实例接管", ctypes.get_last_error())
            return
        self._marks.append(ev)

        def wait() -> None:
            if _k32.WaitForSingleObject(ev, INFINITE) == WAIT_OBJECT_0:
                on_quit()

        threading.Thread(target=wait, name="InstanceQuit", daemon=True).start()
