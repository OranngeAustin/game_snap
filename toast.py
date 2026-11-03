"""截图成功/失败提示浮层。

- 不抢焦点：WS_EX_NOACTIVATE + SW_SHOWNOACTIVATE，鼠标穿透（WS_EX_TRANSPARENT），
  所以全屏游戏不会因为它最小化。
- 不进截图：SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)，连按时下一张截不到它。
- 跑在独立线程里，自带消息循环；其他线程通过 show() 投递消息。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import functools
import logging
import threading

from PIL import Image, ImageChops, ImageDraw, ImageFont

from winapi import (
    WM_APP, WM_CLOSE, WM_DESTROY, WM_TIMER, WNDPROC,
    WS_EX_LAYERED, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST, WS_EX_TRANSPARENT,
    create_window, gdi32, message_loop, unique_class_name, unregister_class, user32,
)

log = logging.getLogger(__name__)

WM_APP_SHOW = WM_APP + 1
WDA_EXCLUDEFROMCAPTURE = 0x11
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
HWND_TOPMOST = wt.HWND(-1)
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10
ULW_ALPHA = 2
AC_SRC_ALPHA = 1
TIMER_HOLD, TIMER_FADE = 1, 2
MONITOR_DEFAULTTONEAREST = 2

GREEN = (52, 199, 89, 255)
RED = (255, 69, 58, 255)


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


user32.SetWindowDisplayAffinity.argtypes = [wt.HWND, wt.DWORD]
user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wt.UINT]
user32.SetTimer.restype = ctypes.c_size_t
user32.SetTimer.argtypes = [wt.HWND, ctypes.c_size_t, wt.UINT, ctypes.c_void_p]
user32.KillTimer.argtypes = [wt.HWND, ctypes.c_size_t]
user32.GetDC.restype = wt.HDC
user32.GetDC.argtypes = [wt.HWND]
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.UpdateLayeredWindow.argtypes = [
    wt.HWND, wt.HDC, ctypes.POINTER(wt.POINT), ctypes.POINTER(wt.SIZE), wt.HDC,
    ctypes.POINTER(wt.POINT), wt.COLORREF, ctypes.POINTER(BLENDFUNCTION), wt.DWORD]
user32.MonitorFromPoint.restype = wt.HMONITOR
user32.MonitorFromPoint.argtypes = [wt.POINT, wt.DWORD]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateDIBSection.restype = wt.HBITMAP
gdi32.CreateDIBSection.argtypes = [wt.HDC, ctypes.POINTER(BITMAPINFOHEADER), wt.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wt.HDC]


def _dpi_scale(rect: tuple[int, int, int, int]) -> float:
    try:
        hmon = user32.MonitorFromPoint(wt.POINT((rect[0] + rect[2]) // 2,
                                                (rect[1] + rect[3]) // 2),
                                       MONITOR_DEFAULTTONEAREST)
        x, y = wt.UINT(), wt.UINT()
        ctypes.windll.shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(x), ctypes.byref(y))
        return max(1.0, x.value / 96)
    except Exception:
        return 1.0


def _font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def render_card(text: str, ok: bool, scale: float) -> Image.Image:
    """画一张半透明圆角卡片：左边绿色✓/红色!圆标，右边文字。3 倍超采样抗锯齿。
    同样的参数只画一次（每张截图的提示都是同一句「已截图 · 游戏名」），每次返回一份拷贝。
    缓存的是画好的小图（几十 KB）。不缓存字体对象：大号中文 TTC 每个字号要常驻约 3.5MB
    （拿 16MB 的 wqy-zenhei.ttc 冒充 msyh.ttc 实测），见 docs/review/03-perf-plan.md P3。"""
    return _render_card(text, ok, scale).copy()


@functools.lru_cache(maxsize=4)
def _render_card(text: str, ok: bool, scale: float) -> Image.Image:
    ss = 3
    k = scale * ss
    font = _font(round(15 * k))
    pad_x, pad_y, icon, gap = round(14 * k), round(10 * k), round(22 * k), round(9 * k)
    l, t, r, b = font.getbbox(text)
    text_w, text_h = r - l, b - t
    h = max(icon, text_h) + 2 * pad_y
    w = pad_x + icon + gap + text_w + pad_x
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=round(10 * k), fill=(28, 28, 30, 225))
    cx, cy = pad_x + icon / 2, h / 2
    d.ellipse([pad_x, cy - icon / 2, pad_x + icon, cy + icon / 2], fill=GREEN if ok else RED)
    lw = max(2, round(2.4 * k))
    if ok:
        u = icon / 22
        d.line([(cx - 5.5 * u, cy + 0.3 * u), (cx - 1.6 * u, cy + 4.2 * u),
                (cx + 5.8 * u, cy - 4.2 * u)], fill="white", width=lw, joint="curve")
    else:
        u = icon / 22
        d.line([(cx, cy - 6 * u), (cx, cy + 1.5 * u)], fill="white", width=lw)
        d.ellipse([cx - lw / 1.6, cy + 4.2 * u - lw / 1.6, cx + lw / 1.6, cy + 4.2 * u + lw / 1.6],
                  fill="white")
    d.text((pad_x + icon + gap - l, (h - text_h) / 2 - t), text, font=font, fill="white")
    return img.resize((round(w / ss), round(h / ss)), Image.Resampling.LANCZOS)


def _premultiplied_bgra(img: Image.Image) -> bytes:
    r, g, b, a = img.split()
    r, g, b = (ImageChops.multiply(c, a) for c in (r, g, b))
    return Image.merge("RGBA", (b, g, r, a)).tobytes()


class Toast(threading.Thread):
    HOLD_MS = 900
    FADE_STEP_MS = 30
    FADE_STEP = 30

    def __init__(self) -> None:
        super().__init__(name="Toast", daemon=True)
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._pending: tuple[str, bool, tuple[int, int, int, int], int] | None = None
        self._hwnd = 0
        self._class_name = unique_class_name("GameSnapToast")
        self._wndproc = WNDPROC(self._proc)
        self._memdc = None
        self._bitmap = None
        self._old_bmp = None
        self._alpha = 0
        self._max_alpha = 245

    # ---------- 对外（任意线程） ----------
    def show(self, text: str, ok: bool, monitor_rect: tuple[int, int, int, int],
             hold_ms: int | None = None) -> None:
        if not self._ready.wait(2) or not self._hwnd:
            return
        with self._lock:
            self._pending = (text, ok, monitor_rect, hold_ms or self.HOLD_MS)
        user32.PostMessageW(self._hwnd, WM_APP_SHOW, 0, 0)

    def stop(self) -> None:
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)

    # ---------- 浮层线程 ----------
    def run(self) -> None:
        try:
            ex = (WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
                  | WS_EX_TOPMOST | WS_EX_TOOLWINDOW)
            self._hwnd = create_window(self._class_name, self._wndproc, ex)
            if not user32.SetWindowDisplayAffinity(self._hwnd, WDA_EXCLUDEFROMCAPTURE):
                log.warning("SetWindowDisplayAffinity 失败，提示浮层可能会被截进图里")
        except Exception:
            log.exception("提示浮层创建失败")
            self._ready.set()
            return
        self._ready.set()
        message_loop()
        self._free_bitmap()
        unregister_class(self._class_name)

    def _proc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_APP_SHOW:
                with self._lock:
                    pending, self._pending = self._pending, None
                if pending:
                    self._show_now(*pending)
                return 0
            if msg == WM_TIMER:
                if wparam == TIMER_HOLD:
                    user32.KillTimer(hwnd, TIMER_HOLD)
                    user32.SetTimer(hwnd, TIMER_FADE, self.FADE_STEP_MS, None)
                elif wparam == TIMER_FADE:
                    self._alpha -= self.FADE_STEP
                    if self._alpha <= 0:
                        user32.KillTimer(hwnd, TIMER_FADE)
                        user32.ShowWindow(hwnd, SW_HIDE)
                    else:
                        self._set_alpha(self._alpha)
                return 0
            if msg == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
        except Exception:
            log.exception("提示浮层出错")
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _show_now(self, text: str, ok: bool, rect: tuple[int, int, int, int],
                  hold_ms: int) -> None:
        scale = _dpi_scale(rect)
        card = render_card(text, ok, scale)
        w, h = card.size
        margin = round(24 * scale)
        x, y = rect[2] - w - margin, rect[1] + margin

        self._free_bitmap()
        screen = user32.GetDC(None)
        self._memdc = gdi32.CreateCompatibleDC(screen)
        bmi = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=w,
                               biHeight=-h, biPlanes=1, biBitCount=32, biCompression=0)
        bits = ctypes.c_void_p()
        self._bitmap = gdi32.CreateDIBSection(screen, ctypes.byref(bmi), 0,
                                              ctypes.byref(bits), None, 0)
        data = _premultiplied_bgra(card)
        ctypes.memmove(bits, data, len(data))
        self._old_bmp = gdi32.SelectObject(self._memdc, self._bitmap)

        self._alpha = self._max_alpha
        blend = BLENDFUNCTION(0, 0, self._alpha, AC_SRC_ALPHA)
        user32.UpdateLayeredWindow(self._hwnd, screen, ctypes.byref(wt.POINT(x, y)),
                                   ctypes.byref(wt.SIZE(w, h)), self._memdc,
                                   ctypes.byref(wt.POINT(0, 0)), 0,
                                   ctypes.byref(blend), ULW_ALPHA)
        user32.ReleaseDC(None, screen)

        user32.ShowWindow(self._hwnd, SW_SHOWNOACTIVATE)
        user32.SetWindowPos(self._hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        user32.KillTimer(self._hwnd, TIMER_FADE)
        user32.SetTimer(self._hwnd, TIMER_HOLD, hold_ms, None)

    def _set_alpha(self, alpha: int) -> None:
        blend = BLENDFUNCTION(0, 0, max(0, min(255, alpha)), AC_SRC_ALPHA)
        user32.UpdateLayeredWindow(self._hwnd, None, None, None, None, None, 0,
                                   ctypes.byref(blend), ULW_ALPHA)

    def _free_bitmap(self) -> None:
        if self._memdc:
            if self._old_bmp:
                gdi32.SelectObject(self._memdc, self._old_bmp)
            gdi32.DeleteDC(self._memdc)
        if self._bitmap:
            gdi32.DeleteObject(self._bitmap)
        self._memdc = self._bitmap = self._old_bmp = None
