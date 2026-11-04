"""前台切换事件钩子（SetWinEventHook）挂不上时要在日志里留下痕迹（02-findings L3）。

InputListener.run 以前不查 SetWinEventHook 的返回值：失败时截图键照样能用，但切到游戏时不再提前准备截图会话、
前台切换也收不到，日志里什么都没有，排查无从下手。这里把 user32 / kernel32 / 建窗口 / 消息循环都换成假的跑一遍 run()：
1. SetWinEventHook 返回 0：日志里有一条提到 SetWinEventHook 的警告，监听照样算启动成功；
2. 返回正常句柄：没有这条警告。
不挂钩子、不建窗口。纯 Python，Windows 和 Linux（tests/winstubs.py 桩）都能跑。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_win_event_hook.py
"""
import logging
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import winstubs  # noqa: E402

winstubs.install()
import hotkey  # noqa: E402

failures: list[str] = []
logs: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {got!r}" + ("" if ok else f"  (want {want!r})"))
    if not ok:
        failures.append(label)


class ListHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        logs.append(f"{record.levelname} {record.getMessage()}")


logging.getLogger().addHandler(ListHandler())
logging.getLogger().setLevel(logging.INFO)


class Fake:
    """什么都成功，只有 SetWinEventHook 按 we_hook 返回。"""

    def __init__(self, we_hook: int) -> None:
        self.we_hook = we_hook

    def __getattr__(self, name):
        if name == "SetWinEventHook":
            return lambda *a: self.we_hook
        return lambda *a: 1


hotkey.create_window = lambda *a, **k: 1
hotkey.message_loop = lambda: None
hotkey.unregister_class = lambda name: None
for label, we_hook in [("挂不上", 0), ("正常", 77)]:
    hotkey.user32 = hotkey.kernel32 = Fake(we_hook)
    logs.clear()
    lis = hotkey.InputListener({"type": "key", "vk": 0x87}, lambda pid: False, lambda *a: None,
                               lambda *a: None, lambda b: None)
    lis.start()
    ok = lis.wait_ready(3)
    lis.join(3)
    warned = [s for s in logs if s.startswith("WARNING") and "SetWinEventHook" in s]
    check(f"{label}：监听算启动成功", ok, True)
    check(f"{label}：有没有警告", bool(warned), we_hook == 0)

print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
