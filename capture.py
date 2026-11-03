"""屏幕抓帧：Windows Graphics Capture（WGC），GDI（mss）兜底。

D3D 设备只建在“驱动游戏所在显示器的那块显卡”上（双显卡笔记本上通常是核显）：
  - 只加载这一块显卡的驱动。在 NVIDIA 独显上建设备，光驱动就要约 48MB 私有内存；核显约 4MB；
  - 画面本来就由这块显卡合成，抓帧不用跨显卡搬运，也不占独显显存。
截图会话在游戏第一次切到前台时打开，之后和设备一样一直留着，直到进程退出都不关（原因见 Capturer）。

所有方法都必须在同一个线程里调用（由 main.CaptureWorker 保证）。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import time
from dataclasses import dataclass

from PIL import Image

import d3d

log = logging.getLogger(__name__)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

MONITOR_DEFAULTTOPRIMARY = 1
FRESH_FRAME_TIMEOUT = 0.15   # 等“按键之后的帧”最多等这么久（秒）
WARM_UP_TIMEOUT = 0.3        # 新会话等第一帧最多等这么久（秒）
POOL_SIZE = 2                # 帧池 2 帧：手里留着最新一帧时，另一格还能收新帧


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("rcMonitor", wt.RECT),
        ("rcWork", wt.RECT),
        ("dwFlags", wt.DWORD),
        ("szDevice", wt.WCHAR * 32),
    ]


_user32.MonitorFromWindow.restype = wt.HMONITOR
_user32.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
_user32.GetMonitorInfoW.argtypes = [wt.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]
_kernel32.GetModuleHandleExW.argtypes = [wt.DWORD, wt.LPCWSTR, ctypes.POINTER(wt.HMODULE)]
GET_MODULE_HANDLE_EX_FLAG_PIN = 0x1


def _pin_module(name: str) -> None:
    """让已加载的 DLL 一直留到进程退出。
    实际使用中出现过：截图会话关闭约 1 秒后，进程因执行已被卸载的 GraphicsCapture.dll 里的代码而崩溃
    （会话关闭后它内部还有延迟执行的回调，DLL 却已被当作闲置卸载了）。钉住后就不会被卸载。"""
    h = wt.HMODULE()
    if not _kernel32.GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_PIN, name, ctypes.byref(h)):
        log.warning("没能钉住 %s（err=%d）", name, ctypes.get_last_error())


def qpc_now() -> int:
    v = ctypes.c_longlong()
    _kernel32.QueryPerformanceCounter(ctypes.byref(v))
    return v.value


def qpc_freq() -> int:
    v = ctypes.c_longlong()
    _kernel32.QueryPerformanceFrequency(ctypes.byref(v))
    return v.value


QPC_FREQ = qpc_freq()


def monitor_of_window(hwnd: int) -> tuple[str, tuple[int, int, int, int]]:
    """返回窗口所在显示器的设备名（如 \\\\.\\DISPLAY1）和桌面坐标矩形。"""
    hmon = _user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTOPRIMARY)
    info = MONITORINFOEXW()
    info.cbSize = ctypes.sizeof(MONITORINFOEXW)
    _user32.GetMonitorInfoW(hmon, ctypes.byref(info))
    r = info.rcMonitor
    return info.szDevice, (r.left, r.top, r.right, r.bottom)


@dataclass
class Shot:
    image: Image.Image          # RGB
    backend: str                # "wgc" / "gdi"
    frame_ticks: int            # 这一帧上屏的时刻（QPC tick）；gdi 为抓取时刻
    grabbed_ticks: int          # 拿到帧数据的时刻（QPC tick）


def _is_black(img: Image.Image) -> bool:
    # 缩小后看最大亮度，几乎为 0 就认为是黑帧（独占全屏抓取失败的典型表现）
    small = img.resize((64, 36), Image.Resampling.NEAREST).convert("L")
    return small.getextrema()[1] <= 8


class _Wgc:
    """WinRT 绑定，第一次用到时才导入（等待进游戏时不占内存）。"""

    def __init__(self) -> None:
        from winrt.windows.graphics.capture import Direct3D11CaptureFramePool
        from winrt.windows.graphics.capture.interop import create_for_monitor
        from winrt.windows.graphics.directx import DirectXPixelFormat
        from winrt.windows.graphics.directx.direct3d11.interop import (
            create_direct3d11_device_from_dxgi_device, get_dxgi_surface_from_object)
        self.FramePool = Direct3D11CaptureFramePool
        self.create_for_monitor = create_for_monitor
        self.BGRA = DirectXPixelFormat.B8_G8_R8_A8_UINT_NORMALIZED
        self.wrap_device = create_direct3d11_device_from_dxgi_device
        self.surface_of = get_dxgi_surface_from_object


class _GpuDevice:
    """一块显卡上的 D3D 设备，以及包装给 WinRT 用的同一个设备。"""

    def __init__(self, wgc: _Wgc, device_name: str) -> None:
        luid = d3d.display_adapter_luid(device_name)
        adapter, self.name = d3d.find_adapter(luid)
        try:
            self.d3d = d3d.Device(adapter)
        finally:
            d3d.release(adapter)
        self.name = self.name or "系统默认显卡"
        dxgi_device = self.d3d.dxgi_device()
        try:
            self.winrt = wgc.wrap_device(dxgi_device)
        finally:
            d3d.release(dxgi_device)


class _Session:
    """一块显示器上的截图会话。帧池满了就不再收新帧，所以平时不耗资源。"""

    def __init__(self, wgc: _Wgc, gpu: _GpuDevice, hmon: int) -> None:
        self._wgc, self._gpu = wgc, gpu
        self.item = wgc.create_for_monitor(hmon)
        self.size = (self.item.size.width, self.item.size.height)
        self.pool = wgc.FramePool.create_free_threaded(gpu.winrt, wgc.BGRA, POOL_SIZE, self.item.size)
        self.session = self.pool.create_capture_session(self.item)
        for attr in ("is_border_required", "is_cursor_capture_enabled"):
            try:
                setattr(self.session, attr, False)   # 不画黄色边框、不截鼠标
            except Exception:
                log.info("当前 Windows 不支持设置 %s", attr)
        self.held = None   # 手里留着的最新一帧（等新帧超时就用它）
        self.session.start_capture()

    @staticmethod
    def ticks(frame) -> int:
        return int(frame.system_relative_time.total_seconds() * QPC_FREQ)

    def _take_all(self) -> None:
        """取出池里所有帧，只留最新一帧，腾出格子让新帧进来。"""
        while True:
            frame = self.pool.try_get_next_frame()
            if frame is None:
                return
            if (frame.content_size.width, frame.content_size.height) != self.size:
                # 分辨率变了：按新尺寸重建帧池，旧帧都不要了
                self.size = (frame.content_size.width, frame.content_size.height)
                log.info("画面尺寸变为 %dx%d，重建帧池", *self.size)
                frame.close()
                self._drop_held()
                self.pool.recreate(self._gpu.winrt, self._wgc.BGRA, POOL_SIZE, frame.content_size)
                continue
            self._drop_held()
            self.held = frame

    def wait_frame(self, after_ticks: int, timeout: float):
        """等到一帧上屏时刻 ≥ after_ticks 的帧；超时就返回手里最新的那帧（可能为 None）。"""
        deadline = qpc_now() + int(timeout * QPC_FREQ)
        self._take_all()
        while self.held is None or self.ticks(self.held) < after_ticks:
            if qpc_now() > deadline:
                break
            time.sleep(0.0005)
            self._take_all()
        return self.held

    def to_image(self, frame) -> Image.Image:
        w, h = self.size
        surface = self._wgc.surface_of(frame.surface)   # 借用的指针，不 release（同 dxcam 的做法）
        texture = d3d.query_interface(surface, d3d.IID_ID3D11Texture2D)
        out = []

        def consume(addr: int, pitch: int) -> None:
            data = (ctypes.c_char * (pitch * h)).from_address(addr)
            # BGRX → RGB 需要解码，frombuffer 此时会拷贝数据，不引用映射内存
            out.append(Image.frombuffer("RGB", (w, h), data, "raw", "BGRX", pitch, 1))

        try:
            self._gpu.d3d.read_texture(texture, w, h, consume)
        finally:
            d3d.release(texture)
        return out[0]

    def _drop_held(self) -> None:
        if self.held is not None:
            self.held.close()
            self.held = None


class Capturer:
    """截图会话和显卡设备开了就一直留着，不关闭也不释放，退出时也不清理（见 main.main）。
    实际用下来，关会话后 1–3 秒进程偶尔会崩在 Windows 自己延迟执行的清理代码里，Python 这边拦不住：
      - 2026-10-12：执行已被卸载的 GraphicsCapture.dll 里的代码（之后加了 _pin_module）；
      - 2026-10-29：游戏退出后关会话，combase 的 COM 工作线程读了已释放的内存。
    崩了之后这一局都截不了图，所以干脆不关。会话开着几乎不耗资源：帧池满了就不再收新帧，
    只是一直占着帧池里两帧画面的显存（1080p 约 16MB）。"""

    def __init__(self) -> None:
        self._wgc: _Wgc | None = None
        self._gpus: dict[str, _GpuDevice] = {}     # 显示器设备名 → 驱动它的显卡上的设备
        self._sessions: dict[int, _Session] = {}   # 显示器句柄 → 这块显示器上的截图会话
        self._retired: list[_Session | _GpuDevice] = []   # 出错后换下来的：只留着引用，不关闭
        self._wgc_broken = False                   # WGC 在本机不可用就不再每次重试
        self._pinned = False

    # ---------- 生命周期 ----------
    def _gpu_for(self, device_name: str) -> _GpuDevice:
        gpu = self._gpus.get(device_name)
        if gpu is None:
            if self._wgc is None:
                self._wgc = _Wgc()
            gpu = self._gpus[device_name] = _GpuDevice(self._wgc, device_name)
            log.info("截图设备建在 %s 上（%s）", gpu.name, device_name)
        return gpu

    def prepare(self, hwnd: int) -> None:
        """游戏刚启动时调用：先导入 WinRT、建好 D3D 设备，第一次切到前台时开会话就很快。"""
        if self._wgc_broken:
            return
        try:
            self._gpu_for(monitor_of_window(hwnd)[0])
        except Exception:
            self._wgc_broken = True
            log.exception("WGC 初始化失败，将使用 GDI")

    def open(self, hwnd: int) -> None:
        """游戏切到前台时调用：确保游戏所在显示器有截图会话，并等到切回游戏后上屏的第一帧。
        游戏切走时会话也开着，帧池里留的是切走前后的旧画面；先换上新画面，
        按键时画面恰好静止（WGC 只在画面变化时出帧）也不会截到旧画面。"""
        t0 = qpc_now()
        hmon = _user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTOPRIMARY)
        device_name = monitor_of_window(hwnd)[0]
        sess = self._sessions.get(hmon)
        if sess is None:
            self._open_session(hmon, device_name)   # 新会话自己会等第一帧
            return
        try:
            sess.wait_frame(t0, WARM_UP_TIMEOUT)
        except Exception:
            log.exception("WGC 取帧失败，换下这个会话并重建设备")
            self._retire(hmon, device_name)

    def _open_session(self, hmon: int, device_name: str) -> None:
        if self._wgc_broken:
            return
        t0 = qpc_now()
        try:
            gpu = self._gpu_for(device_name)
        except Exception:
            self._wgc_broken = True
            log.exception("WGC 初始化失败，将使用 GDI")
            return
        try:
            assert self._wgc is not None
            sess = self._sessions[hmon] = _Session(self._wgc, gpu, hmon)
            if not self._pinned:   # 第一次开会话时 GraphicsCapture.dll 才被加载
                _pin_module("GraphicsCapture.dll")
                self._pinned = True
            # 新会话要等一会儿才出第一帧：切到前台时就先等到它，按键时就不用再等
            sess.wait_frame(t0, WARM_UP_TIMEOUT)
            log.info("截图会话就绪（%.0fms）", (qpc_now() - t0) / QPC_FREQ * 1000)
        except Exception:
            log.exception("打开 WGC 截图会话失败，下次重建设备")
            self._retire(hmon, device_name)

    def _retire(self, hmon: int, device_name: str) -> None:
        """会话或设备可能已失效（驱动重置、显卡切换等）：换下来，下次用到时重建。
        换下来的只留着引用，不关闭也不释放，原因见类说明。"""
        for old in (self._sessions.pop(hmon, None), self._gpus.pop(device_name, None)):
            if old is not None:
                self._retired.append(old)

    # ---------- 抓帧 ----------
    def _grab_wgc(self, hmon: int, device_name: str, t_key: int) -> Shot | None:
        sess = self._sessions.get(hmon)
        if sess is None:
            return None
        try:
            # 帧池满了就不再收新帧，池里可能是很久以前的旧帧：一直等到“按键之后上屏的第一帧”。
            # 画面一直没变化（WGC 只在画面变化时出帧）就用手里最新的那帧
            frame = sess.wait_frame(t_key, FRESH_FRAME_TIMEOUT)
            if frame is None:
                return None
            return Shot(sess.to_image(frame), "wgc", sess.ticks(frame) or qpc_now(), qpc_now())
        except Exception:
            log.exception("WGC 抓帧失败，换下这个会话并重建设备")
            self._retire(hmon, device_name)
            return None

    def _grab_gdi(self, rect: tuple[int, int, int, int]) -> Shot:
        import mss

        left, top, right, bottom = rect
        with mss.mss() as sct:
            raw = sct.grab({"left": left, "top": top,
                            "width": right - left, "height": bottom - top})
        grabbed = qpc_now()
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        return Shot(img, "gdi", grabbed, grabbed)

    def grab(self, hwnd: int, t_key: int) -> Shot:
        device_name, rect = monitor_of_window(hwnd)
        hmon = _user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTOPRIMARY)
        if hmon not in self._sessions:
            self._open_session(hmon, device_name)
        shot = self._grab_wgc(hmon, device_name, t_key)
        if shot is None and hmon not in self._sessions and not self._wgc_broken:
            # 会话刚因异常被换下：重开一次再试
            self._open_session(hmon, device_name)
            shot = self._grab_wgc(hmon, device_name, t_key)
        if shot is not None and not _is_black(shot.image):
            return shot
        if shot is not None:
            log.warning("WGC 得到全黑帧，改用 GDI")
        return self._grab_gdi(rect)
