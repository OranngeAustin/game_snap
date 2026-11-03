"""DualSense 手柄的声音设置：USB 连接时，原神的手柄震动要求手柄的扬声器是四声道、前后都是全音域。

Windows 按 USB 口认这只手柄（它没有序列号），换个口就是一个新的声音设备，设置从默认开始。
所以 GameSnap 运行期间一直留意声音设备：启动时查一次，之后设备插拔或设置有变化时再查。
手柄不是四声道就用 NirSoft 的 svcl.exe 改，改完重新读一遍核对；没有 svcl.exe 时只提醒。

- 认手柄看硬件编号（VID/PID），不看设备名；
- 检查和核对直接读注册表里的端点属性（只读），不依赖 svcl 输出的文字；
- 只改扬声器配置这一项，不碰默认设备、音量、格式等其他声音设置。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import re
import struct
import subprocess
import sys
import threading
import time
import winreg
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

RENDER_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"
DUALSENSE = re.compile(r"VID_054C&PID_(0CE6|0DF2)", re.IGNORECASE)   # DualSense / DualSense Edge
# 端点属性在注册表 Properties 下的值名（{fmtid},pid）
PK_INSTANCE = "{b3f8fa53-0004-438e-9003-51a46e139bfc},2"        # 所属设备实例 ID，含 VID/PID
PK_SPEAKERS = "{1da5d803-d492-4edd-8c23-e0c0ffee7f0e},3"        # PKEY_AudioEndpoint_PhysicalSpeakers
PK_FULL_RANGE = "{1da5d803-d492-4edd-8c23-e0c0ffee7f0e},6"      # PKEY_AudioEndpoint_FullRangeSpeakers
PK_DEVICE_FORMAT = "{f19f064d-082c-4e27-bc73-6882a1bb8e4c},0"   # PKEY_AudioEngine_DeviceFormat
PK_OEM_FORMAT = "{e4870e26-3cc5-4cd2-ba46-ca0a9a70ed04},0"      # PKEY_AudioEngine_OEMFormat（驱动给的默认格式）
QUAD = 0x33   # 左前、右前、左后、右后；三项都是它就是「四声道、所有扬声器都选中」
DEVICE_STATE_ACTIVE = 1

SVCL = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "tools" / "svcl" / "svcl.exe"
SVCL_TIMEOUT_SEC = 10
VERIFY_SEC = 3     # 改完后最多等这么久，看注册表里的设置变过来没有
SETTLE_SEC = 1     # 插拔时系统会连着写好几个值，等写完再看
RETRY_SEC = 2      # 没改成时隔多久再试
MAX_TRIES = 3      # 每次插入最多改几次：系统随后又改回去时能补上，又不会和别的程序没完没了地来回改

# 检查结果
OK, FIXED, NO_TOOL, FAILED, UNVERIFIED = "已符合", "已修正", "缺少 svcl", "执行失败", "验证失败"

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_kernel32.CreateEventW.restype = wt.HANDLE
_kernel32.CreateEventW.argtypes = [wt.LPVOID, wt.BOOL, wt.BOOL, wt.LPCWSTR]
_kernel32.SetEvent.argtypes = [wt.HANDLE]
_kernel32.WaitForMultipleObjects.restype = wt.DWORD
_kernel32.WaitForMultipleObjects.argtypes = [wt.DWORD, ctypes.POINTER(wt.HANDLE), wt.BOOL, wt.DWORD]
_advapi32.RegNotifyChangeKeyValue.restype = wt.LONG
_advapi32.RegNotifyChangeKeyValue.argtypes = [wt.HKEY, wt.BOOL, wt.DWORD, wt.HANDLE, wt.BOOL]

REG_NOTIFY_CHANGE_NAME = 0x1       # 增删子键：换个 USB 口会多出一个新端点
REG_NOTIFY_CHANGE_LAST_SET = 0x4   # 改值：插拔会改端点状态，改设置会改端点属性
INFINITE = 0xFFFFFFFF
WAIT_FAILED = 0xFFFFFFFF


@dataclass
class Endpoint:
    guid: str                   # 注册表里的端点键名
    channel_mask: int | None    # 设备格式的声道掩码
    speakers: int | None        # 有哪些扬声器
    full_range: int | None      # 哪些是全音域扬声器

    @property
    def item_id(self) -> str:   # svcl 和 Windows 音频接口用的端点 ID
        return "{0.0.0.00000000}." + self.guid

    @property
    def is_quad(self) -> bool:
        # 声道掩码读不出来时只看后两项
        return self.speakers == QUAD and self.full_range == QUAD and self.channel_mask in (QUAD, None)

    def describe(self) -> str:   # 顺序和 svcl 的三个参数一致
        return " / ".join(f"{name} {'?' if v is None else hex(v)}" for name, v in
                          (("声道", self.channel_mask), ("扬声器", self.speakers),
                           ("全音域", self.full_range)))


def _value(key, name: str):
    try:
        return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def _dword(key, name: str) -> int | None:
    v = _value(key, name)
    return v if isinstance(v, int) else None


def _channel_mask(blob) -> int | None:
    """格式属性（序列化的 PROPVARIANT：8 字节头 + WAVEFORMATEX）里的声道掩码。"""
    if not isinstance(blob, bytes) or len(blob) < 8 + 18:
        return None
    tag, channels = struct.unpack_from("<HH", blob, 8)
    if tag == 0xFFFE and len(blob) >= 8 + 24:   # WAVE_FORMAT_EXTENSIBLE：掩码写在格式里
        return struct.unpack_from("<I", blob, 8 + 20)[0]
    if tag in (1, 3):                            # PCM / 浮点：按声道数的默认布局
        return {1: 0x4, 2: 0x3, 4: 0x33, 6: 0x3F, 8: 0x63F}.get(channels)
    return None


def read_endpoint(guid: str) -> Endpoint | None:
    """读一个播放端点；不是插着的 DualSense 就返回 None。"""
    path = f"{RENDER_KEY}\\{guid}"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
            if (_dword(k, "DeviceState") or 0) & 0xF != DEVICE_STATE_ACTIVE:
                return None
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path + "\\Properties") as p:
            if not DUALSENSE.search(str(_value(p, PK_INSTANCE) or "")):
                return None
            mask = _channel_mask(_value(p, PK_DEVICE_FORMAT))
            if mask is None:
                mask = _channel_mask(_value(p, PK_OEM_FORMAT))
            return Endpoint(guid, mask, _dword(p, PK_SPEAKERS), _dword(p, PK_FULL_RANGE))
    except OSError:   # 端点正被系统增删
        return None


def find_dualsense() -> list[Endpoint]:
    """当前插着的 DualSense 的播放端点，一个手柄一个。"""
    guids = []
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, RENDER_KEY) as root:
        while True:
            try:
                guids.append(winreg.EnumKey(root, len(guids)))
            except OSError:
                break
    return [ep for g in guids if (ep := read_endpoint(g)) is not None]


def set_quad(ep: Endpoint) -> str:
    """用 svcl 把端点设为四声道、前后全音域（官方文档「四声道、所有扬声器选中」的写法），返回它的输出。
    svcl 的退出码没有文档，成没成功以改完后重读注册表为准。"""
    r = subprocess.run([str(SVCL), "/Stdout", "/SetSpeakersConfig", ep.item_id,
                        hex(QUAD), hex(QUAD), hex(QUAD)],
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=SVCL_TIMEOUT_SEC,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    return (r.stdout + r.stderr).decode("mbcs", "replace").strip()


def ensure_quad(ep: Endpoint) -> tuple[str, Endpoint | None]:
    """不是四声道就改。返回 (检查结果, 最后读到的端点；手柄被拔掉时为 None)。"""
    if ep.is_quad:
        return OK, ep
    if not SVCL.is_file():
        return NO_TOOL, ep
    try:
        out = set_quad(ep)
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("运行 svcl 失败：%s", e)
        return FAILED, ep
    log.info("svcl：%s", " | ".join(s for s in out.splitlines() if s.strip()) or "（没有输出）")
    deadline = time.monotonic() + VERIFY_SEC
    while True:
        now = read_endpoint(ep.guid)
        if now is not None and now.is_quad:
            return FIXED, now
        if now is None or time.monotonic() >= deadline:
            return UNVERIFIED, now
        time.sleep(0.2)


class DualSenseGuard(threading.Thread):
    """启动时查一次，之后声音设备有变化（注册表变化通知）就再查，不对就改。
    结果交给 on_result(检查结果)，由界面决定怎么提示。"""

    def __init__(self, enabled: Callable[[], bool], on_result: Callable[[str], None]) -> None:
        super().__init__(name="DualSense", daemon=True)
        self._enabled = enabled
        self._on_result = on_result
        self._changed = _kernel32.CreateEventW(None, False, False, None)
        self._recheck = _kernel32.CreateEventW(None, False, False, None)
        self._tries: dict[str, int] = {}   # 插着的手柄 → 这次插入已经改过几次
        self._reported: set[str] = set()   # 这次插入已经报告过结果、不再重复记日志和提示的手柄

    def recheck(self) -> None:
        """忘掉之前的结果，从头再查一遍（例如刚在托盘里打开这个功能）。任意线程可调用。"""
        _kernel32.SetEvent(self._recheck)

    def run(self) -> None:
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, RENDER_KEY)
        except OSError:
            log.exception("读不了声音设备列表，DualSense 检查停用")
            return
        handles = (wt.HANDLE * 2)(self._changed, self._recheck)
        armed = warned = False
        verbose = True
        while True:
            # 先登记变化通知再检查：检查期间的变化（包括自己改设置）也会触发下一轮。
            # 上次登记的还没触发时不能再登记，否则每次都多挂一个等待
            if not armed:
                armed = _advapi32.RegNotifyChangeKeyValue(
                    key.handle, True, REG_NOTIFY_CHANGE_NAME | REG_NOTIFY_CHANGE_LAST_SET,
                    self._changed, True) == 0
                if not armed and not warned:
                    warned = True
                    log.warning("声音设备变化通知登记失败，改为每 %d 秒查一次", RETRY_SEC)
            retry = False
            try:
                retry = self._check(verbose)
            except Exception:
                log.exception("DualSense 检查出错")
            hit = _kernel32.WaitForMultipleObjects(
                2, handles, False, RETRY_SEC * 1000 if retry or not armed else INFINITE)
            if hit == 0:
                armed = False
            verbose = hit == 1   # recheck()
            if verbose:
                self._tries.clear()
                self._reported.clear()
            elif hit == WAIT_FAILED:
                time.sleep(RETRY_SEC)
            time.sleep(SETTLE_SEC)

    def _check(self, verbose: bool) -> bool:
        """查一遍插着的手柄，不对就改。返回是否有没改成、过一会儿要再试的。"""
        eps = find_dualsense()
        present = {ep.guid for ep in eps}
        self._tries = {g: n for g, n in self._tries.items() if g in present}   # 拔掉的，下次插上重新算
        self._reported &= present
        if verbose and not eps:
            log.info("没有插着 DualSense（USB）")
        if not self._enabled():
            return False
        retry = False
        for ep in eps:
            if ep.is_quad:
                if ep.guid not in self._reported:
                    self._reported.add(ep.guid)
                    log.info("DualSense 声音设置正常（四声道、前后全音域）：%s", ep.item_id)
                continue
            tries = self._tries.get(ep.guid, 0)
            if tries >= MAX_TRIES:
                continue
            self._tries[ep.guid] = tries + 1
            log.info("DualSense 声音设置不对（%s），改为四声道：%s", ep.describe(), ep.item_id)
            status, now = ensure_quad(ep)
            if status == FIXED:
                log.info("DualSense 已改为四声道（%s）", now.describe())
            elif status == NO_TOOL:
                log.warning("没有 %s，只能提醒手动改", SVCL)
                self._tries[ep.guid] = MAX_TRIES   # 没有工具，再试也没用
            else:
                log.warning("DualSense 没改成（%s）：%s", status,
                            now.describe() if now else "手柄已拔掉")
                if self._tries[ep.guid] < MAX_TRIES:
                    retry = True
                    continue   # 还会再试，先不提示
            self._reported.add(ep.guid)
            self._on_result(status)
        return retry
