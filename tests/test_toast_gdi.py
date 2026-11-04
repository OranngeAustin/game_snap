"""提示浮层画卡片时 GDI 调用失败的处理（02-findings M3）。

Toast._show_now 以前不查 GetDC、CreateCompatibleDC、CreateDIBSection 的返回值：GDI 配额耗尽或内存不足时 bits 是 NULL，
ctypes.memmove(bits, …) 写 0 地址，进程在游戏中途直接消失；GetDC 和 ReleaseDC 之间出异常时屏幕 DC 也不还。
这里把 toast 模块的 user32 / gdi32 换成假的（不碰真的 GDI、不显示窗口），ctypes.memmove 换成「目标是 0 就报错」的版本，检查：
1. 正常时：卡片像素原样拷进位图，更新浮层、显示，屏幕 DC 还回去一次；
2. CreateDIBSection 失败、CreateCompatibleDC 失败、GetDC 失败：不写 0 地址、不显示，建了一半的 DC 删掉，屏幕 DC 还回去；
3. 更新浮层时抛异常：屏幕 DC 照样还回去。
纯 Python，Windows 和 Linux（tests/winstubs.py 桩）都能跑。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_toast_gdi.py
"""
import ctypes
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import winstubs  # noqa: E402

winstubs.install()
import toast  # noqa: E402

failures: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {got!r}" + ("" if ok else f"  (want {want!r})"))
    if not ok:
        failures.append(label)


real_memmove = ctypes.memmove
null_writes: list[int] = []


def guarded_memmove(dst, src, count):
    addr = dst.value if isinstance(dst, ctypes.c_void_p) else dst
    if not addr:
        null_writes.append(count)
        raise OSError("写 0 地址（测试拦下的访问违例）")
    return real_memmove(dst, src, count)


ctypes.memmove = guarded_memmove


class FakeGdi:
    """记下调用；fail 里列出的函数返回 NULL。"""

    def __init__(self, fail: set[str] = frozenset(), raise_in: str = "") -> None:
        self.fail, self.raise_in = fail, raise_in
        self.calls: list[str] = []
        self.buffer = None

    def _call(self, name: str, value):
        self.calls.append(name)
        if name == self.raise_in:
            raise RuntimeError(f"{name} 出错（测试）")
        return None if name in self.fail else value

    # user32
    def GetDC(self, hwnd):
        return self._call("GetDC", 11)

    def ReleaseDC(self, hwnd, hdc):
        return self._call("ReleaseDC", 1)

    def UpdateLayeredWindow(self, *a):
        return self._call("UpdateLayeredWindow", 1)

    def ShowWindow(self, *a):
        return self._call("ShowWindow", 1)

    def SetWindowPos(self, *a):
        return self._call("SetWindowPos", 1)

    def KillTimer(self, *a):
        return self._call("KillTimer", 1)

    def SetTimer(self, *a):
        return self._call("SetTimer", 1)

    # gdi32
    def CreateCompatibleDC(self, hdc):
        return self._call("CreateCompatibleDC", 22)

    def CreateDIBSection(self, hdc, pbmi, usage, ppv_bits, section, offset):
        h = self._call("CreateDIBSection", 33)
        if h:
            bmi = pbmi._obj
            self.buffer = ctypes.create_string_buffer(bmi.biWidth * -bmi.biHeight * 4)
            ppv_bits._obj.value = ctypes.addressof(self.buffer)
        return h

    def SelectObject(self, hdc, obj):
        return self._call("SelectObject", 44)

    def DeleteDC(self, hdc):
        return self._call("DeleteDC", 1)

    def DeleteObject(self, obj):
        return self._call("DeleteObject", 1)


toast._dpi_scale = lambda rect: 1.0
RECT = (0, 0, 1920, 1080)
TEXT = "已截图 · 原神"


def show(gdi: FakeGdi) -> tuple[toast.Toast, str | None]:
    toast.user32 = toast.gdi32 = gdi
    t = toast.Toast()
    t._hwnd = 99
    null_writes.clear()
    try:
        t._show_now(TEXT, True, RECT, 900)
        return t, None
    except Exception as e:   # noqa: BLE001
        return t, f"{type(e).__name__}: {e}"


print("== 1. 正常")
gdi = FakeGdi()
t, error = show(gdi)
check("没有异常", error, None)
want = toast._premultiplied_bgra(toast.render_card(TEXT, True, 1.0))
check("卡片像素原样拷进位图", gdi.buffer is not None and gdi.buffer.raw == want, True)
check("更新浮层并显示", ("UpdateLayeredWindow" in gdi.calls, "ShowWindow" in gdi.calls), (True, True))
check("屏幕 DC 还回去一次", gdi.calls.count("ReleaseDC"), 1)
check("位图留着给淡出用", (t._memdc, t._bitmap), (22, 33))

for case, fail in [("CreateDIBSection 失败", {"CreateDIBSection"}),
                   ("CreateCompatibleDC 失败", {"CreateCompatibleDC"}),
                   ("GetDC 失败", {"GetDC"})]:
    print(f"== 2. {case}")
    gdi = FakeGdi(fail=fail)
    t, error = show(gdi)
    check(f"{case}：没写 0 地址", null_writes, [])
    check(f"{case}：没有异常", error, None)
    check(f"{case}：不显示", "ShowWindow" in gdi.calls, False)
    check(f"{case}：没留下 DC 和位图", (t._memdc, t._bitmap), (None, None))
    if "GetDC" not in fail:
        check(f"{case}：屏幕 DC 还回去了", gdi.calls.count("ReleaseDC"), 1)
        check(f"{case}：建了一半的 DC 删掉了",
              "DeleteDC" in gdi.calls if "CreateCompatibleDC" not in fail else "DeleteDC" not in gdi.calls, True)

print("== 3. 更新浮层时抛异常")
gdi = FakeGdi(raise_in="UpdateLayeredWindow")
t, error = show(gdi)
check("异常照常抛给 _proc（它会记日志）", error is not None, True)
check("屏幕 DC 照样还回去了", gdi.calls.count("ReleaseDC"), 1)

ctypes.memmove = real_memmove
print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
