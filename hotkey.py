"""全局截图键监听（独立线程 + 消息循环）。

- 键盘：WH_KEYBOARD_LL 低级钩子。只有「绑定的键 + 前台是游戏」时才吞掉按键并触发截图，
  其他情况一律放行，所以平时打字不受影响。
- 鼠标侧键：Raw Input（RIDEV_INPUTSINK），只在绑定为侧键或学习模式时注册；
  不挂鼠标钩子，不会给鼠标移动增加延迟。
- 前台窗口切换：SetWinEventHook(EVENT_SYSTEM_FOREGROUND)，事件驱动。
回调都在本线程里执行，调用方必须让它们尽快返回（只往队列里放东西）。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import threading
from typing import Callable

from capture import QPC_FREQ, qpc_now
from watcher import foreground
from winapi import (
    LRESULT, WM_APP, WM_CLOSE, WM_DESTROY, WM_INPUT, WNDPROC, WS_EX_TOOLWINDOW,
    create_window, kernel32, message_loop, unique_class_name, unregister_class, user32,
)

log = logging.getLogger(__name__)

WH_KEYBOARD_LL = 13
HC_ACTION = 0
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x100, 0x101, 0x104, 0x105
VK_ESCAPE = 0x1B
EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT = 0
OBJID_WINDOW = 0
RID_INPUT = 0x10000003
RIM_TYPEMOUSE = 0
RIDEV_REMOVE = 0x00000001
RIDEV_INPUTSINK = 0x00000100
RI_MOUSE_BUTTON_4_DOWN = 0x0040
RI_MOUSE_BUTTON_5_DOWN = 0x0100
MAPVK_VK_TO_VSC, MAPVK_VK_TO_CHAR, MAPVK_VK_TO_VSC_EX = 0, 2, 4
# PgUp PgDn End Home ← ↑ → ↓ Insert Delete：MAPVK_VK_TO_VSC_EX 不一定带 0xE0 前缀（本机键盘布局 0x8040804 的
# Home 返回 0x47），不加扩展键标志就显示成小键盘的「Num 7」（docs/review/05-windows-verification.md P6）
_EXTENDED_VKS = frozenset({0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E})
# 这几个键 MAPVK_VK_TO_VSC_EX 的结果换算不出自己的名字，直接写 GetKeyNameTextW 要的（扫描码, 是否扩展键）
_NAME_SCANS = {
    0x13: (0x45, False),   # Pause：返回 0xE11D，低字节是 Right Ctrl 的扫描码
    0x2C: (0x37, True),    # Print Screen：返回 0x54，是 Sys Req
    0x90: (0x45, True),    # Num Lock：返回 0x45，不加标志是 Pause
}
# 截图键按下后这么久没再收到它的按下事件，就不算「按住不放」：抬起事件可能丢了（L1）。
# 系统的按键重复延迟最长 1 秒，之后约每 33ms 重复一次，所以真按住时不会隔这么久
HELD_STALE_SEC = 1.5
WM_APP_REFRESH_RAW = WM_APP + 1


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wt.DWORD), ("scanCode", wt.DWORD), ("flags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", wt.USHORT), ("usUsage", wt.USHORT),
                ("dwFlags", wt.DWORD), ("hwndTarget", wt.HWND)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", wt.DWORD), ("dwSize", wt.DWORD),
                ("hDevice", wt.HANDLE), ("wParam", wt.WPARAM)]


class _RawMouseButtons(ctypes.Structure):
    _fields_ = [("usButtonFlags", wt.USHORT), ("usButtonData", wt.USHORT)]


class _RawMouseUnion(ctypes.Union):
    _fields_ = [("ulButtons", wt.ULONG), ("s", _RawMouseButtons)]


class RAWMOUSE(ctypes.Structure):
    _fields_ = [("usFlags", wt.USHORT), ("u", _RawMouseUnion), ("ulRawButtons", wt.ULONG),
                ("lLastX", wt.LONG), ("lLastY", wt.LONG), ("ulExtraInformation", wt.ULONG)]


class RAWINPUT(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER), ("mouse", RAWMOUSE)]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)
WINEVENTPROC = ctypes.WINFUNCTYPE(None, wt.HANDLE, wt.DWORD, wt.HWND, wt.LONG, wt.LONG,
                                  wt.DWORD, wt.DWORD)

user32.SetWindowsHookExW.restype = wt.HHOOK
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
user32.CallNextHookEx.restype = LRESULT
user32.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]
user32.UnhookWindowsHookEx.argtypes = [wt.HHOOK]
user32.SetWinEventHook.restype = wt.HANDLE
user32.SetWinEventHook.argtypes = [wt.DWORD, wt.DWORD, wt.HMODULE, WINEVENTPROC,
                                   wt.DWORD, wt.DWORD, wt.DWORD]
user32.UnhookWinEvent.argtypes = [wt.HANDLE]
user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), wt.UINT, wt.UINT]
user32.GetRawInputData.restype = wt.UINT
user32.GetRawInputData.argtypes = [wt.HANDLE, wt.UINT, ctypes.c_void_p,
                                   ctypes.POINTER(wt.UINT), wt.UINT]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.MapVirtualKeyW.restype = wt.UINT
user32.MapVirtualKeyW.argtypes = [wt.UINT, wt.UINT]
user32.GetKeyNameTextW.argtypes = [wt.LONG, wt.LPWSTR, ctypes.c_int]


def key_name(binding: dict) -> str:
    if binding.get("type") == "mouse":
        return "鼠标侧键（后退）" if binding.get("button") == 4 else "鼠标侧键（前进）"
    vk = int(binding.get("vk", 0))
    ch = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_CHAR) & 0x7FFF
    if ch and chr(ch).isprintable() and not chr(ch).isspace():
        return chr(ch)
    buf = ctypes.create_unicode_buffer(64)
    if vk in _NAME_SCANS:
        scan, extended = _NAME_SCANS[vk]
    else:
        vsc = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC_EX)
        # 0xE0 前缀还要看：Left Windows、Right Ctrl 这些靠它区分（02-findings L4）
        scan, extended = vsc & 0xFF, vk in _EXTENDED_VKS or vsc & 0xFF00 == 0xE000
    lparam = scan << 16
    if extended:
        lparam |= 1 << 24
    if user32.GetKeyNameTextW(lparam, buf, 64):
        return buf.value
    return f"VK {vk:#04x}"


class InputListener(threading.Thread):
    def __init__(self, binding: dict,
                 should_capture: Callable[[int], bool],
                 on_shot: Callable[[int, int, int], None],
                 on_foreground: Callable[[int, int], None],
                 on_learned: Callable[[dict | None], None]) -> None:
        super().__init__(name="InputListener", daemon=True)
        self.binding = dict(binding)
        self._should_capture = should_capture   # pid -> 是否该截图（是游戏且未暂停）
        self._on_shot = on_shot                 # (t_key_qpc, hwnd, pid)
        self._on_foreground = on_foreground     # (hwnd, pid)
        self._on_learned = on_learned           # 学到的新绑定；None 表示取消
        self._learning = False
        self._held = False            # 绑定键正按着（用于忽略自动重复）
        self._held_at = 0             # 最近一次收到绑定键按下事件的 QPC 时刻
        self._held_swallowed = False  # 这次按下是否被吞掉（抬起时也要吞）
        self._swallow_up_vk = None    # 学习模式吞掉的键，其抬起也吞掉
        self._raw_registered = False
        self._hwnd = 0
        self._failed = False          # run() 里建窗口或挂钩子失败
        self._class_name = unique_class_name("GameSnapInput")   # 每个监听一个窗口类，见 winapi.unique_class_name
        self._ready = threading.Event()
        # ctypes 回调必须保持引用，否则会被回收导致崩溃
        self._wndproc = WNDPROC(self._proc)
        self._kb_proc_c = HOOKPROC(self._kb_proc)
        self._we_proc_c = WINEVENTPROC(self._we_proc)

    # ---------- 对外（任意线程） ----------
    def set_binding(self, binding: dict) -> None:
        self.binding = dict(binding)
        self._held = False   # 旧键的抬起不会再匹配，不清掉的话新键第一次按下会被当成自动重复（L1）
        self._post(WM_APP_REFRESH_RAW)

    def start_learning(self) -> None:
        self._learning = True
        self._held = False   # 同上：学键时按着的键，它的抬起被学键吞掉了
        self._post(WM_APP_REFRESH_RAW)

    def cancel_learning(self) -> None:
        self._learning = False
        self._post(WM_APP_REFRESH_RAW)

    def stop(self) -> None:
        self._post(WM_CLOSE)
        self.join(timeout=2)

    def wait_ready(self, timeout: float = 2) -> bool:
        """True = 已就绪；False = 启动失败（线程随即结束），或者 timeout 内还没就绪（02-findings M4）。"""
        return self._ready.wait(timeout) and not self._failed

    def _post(self, msg: int) -> None:
        if self._ready.wait(2) and self._hwnd:
            user32.PostMessageW(self._hwnd, msg, 0, 0)

    # ---------- 监听线程 ----------
    def run(self) -> None:
        kb_hook = we_hook = None
        try:
            self._hwnd = create_window(self._class_name, self._wndproc, WS_EX_TOOLWINDOW)
            kb_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kb_proc_c,
                                               kernel32.GetModuleHandleW(None), 0)
            if not kb_hook:
                raise ctypes.WinError(ctypes.get_last_error())
            we_hook = user32.SetWinEventHook(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND,
                                             None, self._we_proc_c, 0, 0, WINEVENT_OUTOFCONTEXT)
            if not we_hook:   # 截图键照样能用，但前台切换收不到、不会提前准备截图会话：留个痕迹（02-findings L3）
                log.warning("SetWinEventHook 失败 err=%d：切到游戏时不会提前准备截图会话，第一张截图会慢一些",
                            ctypes.get_last_error())
            self._refresh_raw()
            log.info("按键监听已启动")
        except Exception:
            log.exception("按键监听启动失败")
            self._failed = True
            if kb_hook:   # 挂上一半的钩子拆掉，不留给没有消息循环的线程
                user32.UnhookWindowsHookEx(kb_hook)
            if we_hook:
                user32.UnhookWinEvent(we_hook)
            self._ready.set()
            return
        self._ready.set()
        message_loop()
        user32.UnhookWindowsHookEx(kb_hook)
        if we_hook:
            user32.UnhookWinEvent(we_hook)
        unregister_class(self._class_name)   # 窗口在 WM_CLOSE 里已销毁
        log.info("按键监听已停止")

    def _proc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_INPUT:
                self._on_raw_input(lparam)
            elif msg == WM_APP_REFRESH_RAW:
                self._refresh_raw()
                return 0
            elif msg == WM_CLOSE:
                self._set_raw(False)
                user32.DestroyWindow(hwnd)
                return 0
            elif msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
        except Exception:
            log.exception("监听窗口消息处理出错")
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # ---------- 键盘 ----------
    def _kb_proc(self, ncode, wparam, lparam):
        if ncode == HC_ACTION:
            t_key = qpc_now()   # 第一时间记下按键时刻
            try:
                kb = KBDLLHOOKSTRUCT.from_address(lparam)
                if self._handle_key(kb.vkCode, wparam, t_key):
                    return 1
            except Exception:
                log.exception("键盘钩子出错")
        return user32.CallNextHookEx(None, ncode, wparam, lparam)

    def _handle_key(self, vk: int, msg: int, t_key: int) -> bool:
        """返回 True 表示吞掉这个按键事件。"""
        down = msg in (WM_KEYDOWN, WM_SYSKEYDOWN)
        if not down and vk == self._swallow_up_vk:
            self._swallow_up_vk = None
            return True
        if self._learning and down:
            self._learning = False
            self._swallow_up_vk = vk
            self._post(WM_APP_REFRESH_RAW)
            self._on_learned(None if vk == VK_ESCAPE else {"type": "key", "vk": int(vk)})
            return True

        b = self.binding
        if b.get("type") != "key" or vk != b.get("vk"):
            return False
        if down:
            if self._held and t_key - self._held_at <= HELD_STALE_SEC * QPC_FREQ:   # 按住不放产生的自动重复
                self._held_at = t_key
                return self._held_swallowed
            # 新按下；或者「按着」的状态已经过时（抬起事件丢了：安全桌面、别的钩子吞掉），以前会一直当成自动重复（L1）
            self._held = True
            self._held_at = t_key
            hwnd, pid = foreground()
            self._held_swallowed = self._should_capture(pid)
            if self._held_swallowed:
                self._on_shot(t_key, hwnd, pid)
            return self._held_swallowed
        self._held = False
        swallowed, self._held_swallowed = self._held_swallowed, False
        return swallowed

    # ---------- 鼠标侧键（Raw Input） ----------
    def _refresh_raw(self) -> None:
        self._set_raw(self._learning or self.binding.get("type") == "mouse")

    def _set_raw(self, want: bool) -> None:
        if want == self._raw_registered:
            return
        dev = RAWINPUTDEVICE(1, 2, RIDEV_INPUTSINK if want else RIDEV_REMOVE,
                             self._hwnd if want else None)
        if user32.RegisterRawInputDevices(ctypes.byref(dev), 1, ctypes.sizeof(dev)):
            self._raw_registered = want
        else:
            log.warning("RegisterRawInputDevices 失败：%s", ctypes.get_last_error())

    def _on_raw_input(self, hraw) -> None:
        t_key = qpc_now()
        size = wt.UINT(0)
        hdr = ctypes.sizeof(RAWINPUTHEADER)
        user32.GetRawInputData(hraw, RID_INPUT, None, ctypes.byref(size), hdr)
        buf = ctypes.create_string_buffer(max(size.value, ctypes.sizeof(RAWINPUT)))
        if user32.GetRawInputData(hraw, RID_INPUT, buf, ctypes.byref(size), hdr) == 0xFFFFFFFF:
            return
        ri = RAWINPUT.from_buffer(buf)
        if ri.header.dwType != RIM_TYPEMOUSE:
            return
        flags = ri.mouse.u.s.usButtonFlags
        button = 4 if flags & RI_MOUSE_BUTTON_4_DOWN else 5 if flags & RI_MOUSE_BUTTON_5_DOWN else 0
        if not button:
            return
        if self._learning:
            self._learning = False
            self._refresh_raw()
            self._on_learned({"type": "mouse", "button": button})
            return
        b = self.binding
        if b.get("type") == "mouse" and b.get("button") == button:
            hwnd, pid = foreground()
            if self._should_capture(pid):
                self._on_shot(t_key, hwnd, pid)

    # ---------- 前台切换 ----------
    def _we_proc(self, hook, event, hwnd, id_object, id_child, thread, time_ms):
        if id_object != OBJID_WINDOW or not hwnd:
            return
        try:
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            self._on_foreground(hwnd, pid.value)
        except Exception:
            log.exception("前台切换回调出错")
