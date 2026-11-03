"""游戏 / 启动器进程检测：每隔几秒看一次进程列表。"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_psapi = ctypes.WinDLL("psapi", use_last_error=True)
_psapi.EnumProcesses.argtypes = [ctypes.POINTER(wt.DWORD), wt.DWORD, ctypes.POINTER(wt.DWORD)]

FULL_REFRESH_SEC = 30   # pid 被复用（旧进程退出、新进程恰好拿到同一个 pid）时，最晚这么久后认出来

TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = wt.HANDLE(-1).value


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", wt.WCHAR * 260),
    ]


_kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
_kernel32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
_kernel32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
_kernel32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
_kernel32.CloseHandle.argtypes = [wt.HANDLE]
_user32.GetForegroundWindow.restype = wt.HWND
_user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
_user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]


def snapshot_names(lower: bool = True) -> dict[int, str]:
    """一次进程快照：{pid: 进程名}，默认转成小写。约 7ms CPU（逐个读 300 来个进程），所以只在需要时调用。"""
    names: dict[int, str] = {}
    snap = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE or not snap:
        return names
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = _kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            names[entry.th32ProcessID] = entry.szExeFile.lower() if lower else entry.szExeFile
            ok = _kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snap)
    return names


def process_name(pid: int) -> str | None:
    """某个进程的进程名（保留大小写），查不到时返回 None。同样只用快照，不打开那个进程。"""
    return snapshot_names(lower=False).get(pid)


class ProcessScanner:
    """平时只用 EnumProcesses 拿 pid 列表（约 0.05ms）；出现新 pid 时才做一次快照查进程名。
    不用 OpenProcess 打开别的进程，所以游戏的反作弊拦不拦句柄都不影响。"""

    def __init__(self) -> None:
        self._names: dict[int, str] = {}
        self._buf = (wt.DWORD * 1024)()
        self._next_full = 0.0

    def _pids(self) -> set[int]:
        while True:
            used = wt.DWORD()
            _psapi.EnumProcesses(self._buf, ctypes.sizeof(self._buf), ctypes.byref(used))
            n = used.value // ctypes.sizeof(wt.DWORD)
            if n < len(self._buf):
                return set(self._buf[:n])
            self._buf = (wt.DWORD * (len(self._buf) * 2))()   # 缓冲区满了，可能没列全

    def scan(self, games_lower: dict[str, str],
             launchers_lower: set[str]) -> tuple[dict[int, str], bool]:
        """返回 ({游戏pid: 显示名}, 是否有启动器在运行)。名单的键都是小写进程名。"""
        pids = self._pids()
        now = time.monotonic()
        if not pids <= self._names.keys() or now >= self._next_full:
            self._names = snapshot_names()
            self._next_full = now + FULL_REFRESH_SEC
        else:
            for gone in self._names.keys() - pids:
                del self._names[gone]
        games: dict[int, str] = {}
        launcher = False
        for pid, exe in self._names.items():
            name = games_lower.get(exe)
            if name:
                games[pid] = name
            elif exe in launchers_lower:
                launcher = True
        return games, launcher


def foreground() -> tuple[int, int]:
    """返回 (前台窗口 hwnd, 所属 pid)。"""
    hwnd = _user32.GetForegroundWindow()
    pid = wt.DWORD()
    if hwnd:
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return hwnd or 0, pid.value


def window_title(hwnd: int) -> str:
    """窗口标题。别的进程的窗口不发消息，直接读系统记下的标题，对方卡住也不用等。"""
    buf = ctypes.create_unicode_buffer(512)
    _user32.GetWindowTextW(hwnd, buf, len(buf))
    return buf.value


class GameWatcher(threading.Thread):
    """定时扫描进程，每次都回调 on_poll(游戏, 启动器是否在运行)，由调用方判断状态变化。"""

    def __init__(self, get_games: Callable[[], dict[str, str]],
                 get_launchers: Callable[[], set[str]],
                 get_interval: Callable[[], float],
                 on_poll: Callable[[dict[int, str], bool], None]) -> None:
        super().__init__(name="GameWatcher", daemon=True)
        self._get_games = get_games
        self._get_launchers = get_launchers
        self._get_interval = get_interval
        self._on_poll = on_poll
        self._stop_event = threading.Event()
        self._scanner = ProcessScanner()

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                games, launcher = self._scanner.scan(self._get_games(), self._get_launchers())
                self._on_poll(games, launcher)
            except Exception:
                log.exception("进程检测出错")
            self._stop_event.wait(self._get_interval())

    def stop(self) -> None:
        self._stop_event.set()
