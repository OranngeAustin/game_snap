"""InputListener 在一个进程里停了再建（游戏关了又开、添加游戏 / 更换截图键前后都会这样）：
新监听窗口的消息必须送到新的 InputListener 自己的窗口过程，而不是第一个、已经停掉的那个。

做法：建 L1 → 停掉（还留着引用，模拟它还没被回收）→ 建 L2 → set_binding 成鼠标侧键。
set_binding 往 L2 的窗口投递 WM_APP_REFRESH_RAW，L2 的窗口过程收到才会登记 Raw Input（_raw_registered 变 True）；
消息被送到 L1 的话，L2 永远登记不上，鼠标侧键截图和学鼠标侧键都不灵。再回收 L1、建 L3 查一遍。

用 F24 当截图键，should_capture 恒为 False：钩子挂着也不拦任何按键；不发真实按键。只在 Windows 上跑，
其他系统打印 SKIP 后退出码 0。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_listener_restart.py <run dir>
"""
import gc
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT, RUN = HERE.parent, Path(sys.argv[1])
RUN.mkdir(parents=True, exist_ok=False)
if sys.platform != "win32":
    print("SKIP  needs Windows (real keyboard hook and windows)")
    sys.exit(0)
sys.path.insert(0, str(PROJECT))
from hotkey import InputListener  # noqa: E402

F24 = {"type": "key", "vk": 0x87}
MOUSE5 = {"type": "mouse", "button": 5}
failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""), flush=True)
    if not ok:
        failures.append(label)


def noop(*a) -> None:
    pass


def make(label: str) -> InputListener:
    lst = InputListener(F24, lambda pid: False, on_shot=noop, on_foreground=noop, on_learned=noop)
    lst.start()
    check(f"{label}: ready with a window", lst.wait_ready(3) and bool(lst._hwnd), f"hwnd={lst._hwnd}")
    return lst


def wait_for(pred, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def exercise(lst: InputListener, label: str) -> None:
    lst.set_binding(MOUSE5)
    check(f"{label}: mouse binding reaches its own window (Raw Input registered)",
          wait_for(lambda: lst._raw_registered))
    lst.set_binding(F24)
    check(f"{label}: back to key binding (Raw Input removed)", wait_for(lambda: not lst._raw_registered))


def stop(lst: InputListener, label: str) -> None:
    lst.stop()
    check(f"{label}: thread stopped", not lst.is_alive())


l1 = make("L1")
exercise(l1, "L1")
stop(l1, "L1")

l2 = make("L2")          # L1 还被引用着、没被回收
exercise(l2, "L2 (L1 still alive)")
stop(l2, "L2")

del l1, l2
gc.collect()         # 旧的都回收了：它们的 ctypes 回调已释放
l3 = make("L3")
exercise(l3, "L3 (old ones collected)")
stop(l3, "L3")

print("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
