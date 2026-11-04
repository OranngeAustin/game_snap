"""截图会话建到一半失败时，已经建好的帧池 / 会话不能被回收关掉（02-findings L9）。

Capturer 的约定是会话开了就不关（关会话偶尔崩溃，见 capture.Capturer）。_Session.__init__ 以前中途抛错（建会话、设置边框、
start_capture 失败）时，已经建好的帧池和会话没人引用，被 GC 回收就等于关闭。这里用假的 WinRT 对象：帧池 / 会话被回收时
记一笔「关掉了」，检查各处失败后 gc.collect() 也不会关掉已建的对象，异常照常抛出去；正常建好的会话不受影响。
纯 Python，Windows 和 Linux（tests/winstubs.py 桩）都能跑。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_session_init_fail.py
"""
import gc
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import winstubs  # noqa: E402

winstubs.install()
import capture  # noqa: E402

failures: list[str] = []
closed: list[str] = []
fail = {"where": ""}


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {got!r}" + ("" if ok else f"  (want {want!r})"))
    if not ok:
        failures.append(label)


class Size:
    width, height = 1920, 1080


class Tracked:
    def __init__(self, name: str) -> None:
        self.name = name

    def __del__(self) -> None:
        closed.append(self.name)


class Session(Tracked):
    def start_capture(self) -> None:
        if fail["where"] == "start_capture":
            raise OSError("start_capture 失败（假）")


class Pool(Tracked):
    def create_capture_session(self, item):
        if fail["where"] == "create_capture_session":
            raise OSError("建会话失败（假）")
        return Session("会话")


class Wgc:
    BGRA = "BGRA"

    class FramePool:
        @staticmethod
        def create_free_threaded(device, fmt, n, size):
            return Pool("帧池")

    @staticmethod
    def create_for_monitor(hmon):
        item = Tracked("item")
        item.size = Size()
        return item


gpu = type("Gpu", (), {"winrt": "device"})()
for where, should_live in [("create_capture_session", ["帧池"]), ("start_capture", ["帧池", "会话"])]:
    closed.clear()
    fail["where"] = where
    try:
        capture._Session(Wgc(), gpu, 1)
        error = None
    except OSError as e:
        error = str(e)
    gc.collect()
    check(f"{where} 失败：异常照常抛出去", error is not None, True)
    check(f"{where} 失败：已建的没被关掉", [n for n in should_live if n in closed], [])
fail["where"] = ""
closed.clear()
sess = capture._Session(Wgc(), gpu, 1)
check("正常建好：可以用", (sess.size, closed), ((1920, 1080), []))

print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
