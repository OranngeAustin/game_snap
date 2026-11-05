"""截图键「按住」状态不会因为丢了抬起事件而卡住（02-findings L1）。

InputListener._handle_key 用 _held 区分「新按下」和「按住不放的自动重复」。以前抬起事件丢了（切到安全桌面、别的钩子吞掉、
按住时换了截图键），_held 就一直是 True：下一次真按下被当成自动重复，键被吞掉却不截图。现在检查：
1. 正常：按下截图，自动重复只吞不截，抬起后再按又截；
2. 丢了抬起：隔 3 秒再按下，当成新按下，照样截图；
3. 按住旧键时换成新键：新键第一次按下就截图；
4. 按住时开始学键：学键结束后第一次按下就截图。
不挂钩子、不建窗口，直接调 _handle_key（时刻用假的 QPC 计数）。纯 Python，Windows 和 Linux（tests/winstubs.py 桩）都能跑。
Exit code 1 if anything failed.

usage: python -X utf8 tests/test_held_key.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import winstubs  # noqa: E402

winstubs.install()
import hotkey  # noqa: E402

failures: list[str] = []
if not getattr(hotkey, "QPC_FREQ", 0):
    hotkey.QPC_FREQ = 10_000_000   # Linux 桩下 QueryPerformanceFrequency 是假的
F = getattr(hotkey, "QPC_FREQ", 10_000_000)
DOWN, UP = hotkey.WM_KEYDOWN, hotkey.WM_KEYUP
VK, VK2 = 0x87, 0x86


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {got!r}" + ("" if ok else f"  (want {want!r})"))
    if not ok:
        failures.append(label)


shots: list[int] = []
learned: list = []
hotkey.foreground = lambda: (1, 4242)
lis = hotkey.InputListener({"type": "key", "vk": VK}, lambda pid: True, lambda t, h, p: shots.append(t),
                           lambda h, p: None, learned.append)
lis._ready.set()   # 没启动线程：让 set_binding / start_learning 里的 PostMessage 直接跳过


def key(vk: int, msg: int, sec: float) -> bool:
    return lis._handle_key(vk, msg, int(sec * F))


print("== 1. 正常")
check("按下：吞掉并截图", (key(VK, DOWN, 0), len(shots)), (True, 1))
check("自动重复：只吞不截", (key(VK, DOWN, 0.5), key(VK, DOWN, 0.53), len(shots)), (True, True, 1))
check("抬起：吞掉", key(VK, UP, 0.6), True)
check("再按：又截一张", (key(VK, DOWN, 1.0), len(shots)), (True, 2))
key(VK, UP, 1.1)

print("== 2. 丢了抬起事件")
shots.clear()
key(VK, DOWN, 10)
check("隔 3 秒再按下：当成新按下、截图", (key(VK, DOWN, 13), len(shots)), (True, 2))
key(VK, UP, 13.1)

print("== 3. 按住旧键时换成新键")
shots.clear()
key(VK, DOWN, 20)
lis.set_binding({"type": "key", "vk": VK2})
check("新键第一次按下就截图", (key(VK2, DOWN, 20.2), len(shots)), (True, 2))
key(VK2, UP, 20.3)

print("== 4. 按住时开始学键")
shots.clear()
key(VK2, DOWN, 30)
lis.start_learning()
key(VK, DOWN, 30.2)   # 学到 VK（模拟 App 收到后 set_binding 前，旧绑定还是 VK2）
check("学到了", learned[-1:], [{"type": "key", "vk": VK}])
key(VK, UP, 30.3)
check("学键结束后第一次按下就截图", (key(VK2, DOWN, 30.5), len(shots)), (True, 2))

print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
