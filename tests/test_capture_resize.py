"""画面尺寸变化时 capture._Session._take_all 重建帧池（02-findings M1）。

游戏切全屏、改分辨率后，帧池里会来一帧新尺寸的帧，_take_all 要按新尺寸重建帧池。以前先 frame.close() 再把
frame.content_size 传给 pool.recreate：WinRT 的 IClosable 对象关闭后再读成员，通常报 RO_E_CLOSED，于是抛异常，
这次截图走重建会话或 GDI，「重建帧池」这段逻辑形同虚设。

这里用假的 WinRT 对象建一个真的 _Session（假帧关闭后读 content_size 就抛 OSError，模拟 RO_E_CLOSED），检查：
1. 尺寸没变时不重建，只留最新一帧（原有行为）；
2. 尺寸变化时不抛异常，按新尺寸重建一次帧池，会话记下新尺寸；新尺寸的那帧和更早的帧都关掉了，
   手里留的是之后来的最新一帧。
不碰 WGC / D3D。纯 Python，Windows 和 Linux（tests/winstubs.py 桩）都能跑。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_capture_resize.py
"""
import sys
from datetime import timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import winstubs  # noqa: E402

winstubs.install()
import capture  # noqa: E402

failures: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {got!r}" + ("" if ok else f"  (want {want!r})"))
    if not ok:
        failures.append(label)


class Size:
    def __init__(self, width: int, height: int) -> None:
        self.width, self.height = width, height


class Frame:
    """关闭之后读 content_size 抛错，和 WinRT 关闭后访问成员报 RO_E_CLOSED 一样。"""

    def __init__(self, name: str, w: int, h: int) -> None:
        self.name, self._size, self.closed = name, Size(w, h), False
        self.system_relative_time = timedelta(seconds=1)

    @property
    def content_size(self) -> Size:
        if self.closed:
            raise OSError("RO_E_CLOSED：对象已关闭（假）")
        return self._size

    def close(self) -> None:
        self.closed = True

    def __repr__(self) -> str:
        return self.name


class Pool:
    def __init__(self) -> None:
        self.frames: list[Frame] = []
        self.recreated: list[tuple[int, int]] = []

    def try_get_next_frame(self):
        return self.frames.pop(0) if self.frames else None

    def recreate(self, device, fmt, n, size) -> None:
        self.recreated.append((size.width, size.height))

    def create_capture_session(self, item):
        return type("Session", (), {"start_capture": lambda self: None})()


pool = Pool()


class Wgc:
    BGRA = "BGRA"

    class FramePool:
        @staticmethod
        def create_free_threaded(device, fmt, n, size):
            return pool

    @staticmethod
    def create_for_monitor(hmon):
        return type("Item", (), {"size": Size(1920, 1080)})()


gpu = type("Gpu", (), {"winrt": "device"})()
session = capture._Session(Wgc(), gpu, 1)
check("新会话的尺寸", session.size, (1920, 1080))

print("== 1. 尺寸不变：只留最新一帧")
a, b = Frame("a", 1920, 1080), Frame("b", 1920, 1080)
pool.frames = [a, b]
session._take_all()
check("留下最新一帧", session.held, b)
check("旧帧关掉了", a.closed, True)
check("没有重建帧池", pool.recreated, [])

print("== 2. 尺寸变了：按新尺寸重建帧池")
c, d = Frame("c", 2560, 1440), Frame("d", 2560, 1440)
pool.frames = [c, d]
try:
    session._take_all()
    error = None
except Exception as e:   # noqa: BLE001
    error = f"{type(e).__name__}: {e}"
check("不抛异常", error, None)
check("按新尺寸重建了一次帧池", pool.recreated, [(2560, 1440)])
check("会话记下新尺寸", session.size, (2560, 1440))
check("新尺寸的那帧和之前留着的帧都关掉了", (c.closed, b.closed), (True, True))
check("手里留的是之后来的最新一帧", session.held, d)
check("d 还没关", d.closed, False)

print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
