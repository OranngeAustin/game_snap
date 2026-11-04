"""进程检测失败时不能当成「游戏全退出了」（02-findings L15）。

ProcessScanner 以前不查 EnumProcesses 的返回值，快照失败也只是返回空：结果是「没有任何游戏」，App 会摘掉按键钩子、
下一轮再挂；连续失败到 exit_grace_sec，GameSnap 会在游戏中途自己退出。现在失败时抛异常，GameWatcher 记日志、跳过这一轮，
保留上一次的结果。检查：
1. 正常时找到游戏；
2. EnumProcesses 失败、或者返回 0 个进程：scan 抛异常，不返回空结果；
3. 出现新进程、做快照时快照失败：scan 抛异常；
4. GameWatcher 在失败的那几轮不回调 on_poll，所以 App 不会看到「游戏没了」。
psapi 和进程快照换成假的。纯 Python，Windows 和 Linux（tests/winstubs.py 桩）都能跑。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_scan_fail.py
"""
import ctypes
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import winstubs  # noqa: E402

winstubs.install()
import watcher  # noqa: E402

failures: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {got!r}" + ("" if ok else f"  (want {want!r})"))
    if not ok:
        failures.append(label)


class FakePsapi:
    def __init__(self) -> None:
        self.mode = "ok"   # ok / fail / empty
        self.pids = [4, 4000]

    def EnumProcesses(self, buf, size, used_ref) -> int:
        if self.mode == "fail":
            return 0
        pids = [] if self.mode == "empty" else self.pids
        for i, p in enumerate(pids):
            buf[i] = p
        used_ref._obj.value = ctypes.sizeof(watcher.wt.DWORD) * len(pids)   # Linux 上 DWORD 是 8 字节
        return 1


psapi = watcher._psapi = FakePsapi()
NAMES = {4: "system", 4000: "fakegame.exe", 4004: "notepad.exe"}
snap = {"ok": True}
watcher.snapshot_names = lambda lower=True: ({p: n for p, n in NAMES.items() if p in psapi.pids}
                                             if snap["ok"] else {})
GAMES = {"fakegame.exe": "假游戏"}


def scan(scanner):
    try:
        return scanner.scan(GAMES, set()), None
    except Exception as e:   # noqa: BLE001
        return None, type(e).__name__


print("== 1. 正常")
s = watcher.ProcessScanner()
check("找到游戏", scan(s), (({4000: "假游戏"}, False), None))

print("== 2. EnumProcesses 失败")
for mode in ("fail", "empty"):
    psapi.mode = mode
    result, error = scan(s)
    check(f"{mode}：不返回空结果", result, None)
    check(f"{mode}：抛异常", error is not None, True)
psapi.mode = "ok"
check("恢复后照常", scan(s)[0], ({4000: "假游戏"}, False))

print("== 3. 新进程出现时快照失败")
psapi.pids = [4, 4000, 4004]
snap["ok"] = False
result, error = scan(s)
check("不返回空结果", result, None)
check("抛异常", error is not None, True)
snap["ok"] = True
check("恢复后照常", scan(s)[0], ({4000: "假游戏"}, False))

print("== 4. GameWatcher 在失败的那几轮不回调")
polls: list[dict] = []
w = watcher.GameWatcher(lambda: GAMES, set, lambda: 0.01, lambda games, launcher: polls.append(dict(games)))
w.start()
time.sleep(0.15)
psapi.mode = "fail"
time.sleep(0.15)
psapi.mode = "ok"
time.sleep(0.15)
w.stop()
w.join(2)
check("回调过", len(polls) > 3, True)
check("没有一次是「没有游戏」", [p for p in polls if not p], [])

print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
