"""save_png 写到一半失败（磁盘满）或改名时被占用（杀毒软件、同步盘）的处理（02-findings L11、05-windows-verification P5）。

save_png 先写 <名字>.png.part 再改名。以前 img.save 抛异常时 .png.part 留在截图文件夹里，越积越多；改名时被占用直接失败，
完整的 PNG 留在 .part 里；删 .part 也被占用时再抛一次异常。现在检查：
1. 写到一半抛异常：异常照常抛出去（finish_shot 会提示「截图失败」），文件夹里没有 .png.part，也没有 .png；
2. 正常保存不受影响，下一张照常存；
3. 改名时被占用两次后放开：重试后存上了，没有 .png.part；
4. 一直被占用：试 5 次后异常照常抛出去，.png.part 删掉；
5. 删 .png.part 也被占用：抛出去的还是改名的异常，日志记下留在哪里；放开后下一张照常存；
6. 只在 Windows 上：另一个句柄真的开着 .png.part，再跑一遍 3 和 5。
只在 <run dir> 里读写。纯 Python，Windows 和 Linux（tests/winstubs.py 桩）都能跑。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_save_png_fail.py <run dir>
"""
import logging
import sys
import threading
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT, RUN = HERE.parent, Path(sys.argv[1])
RUN.mkdir(parents=True, exist_ok=False)
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PROJECT))
import winstubs  # noqa: E402

winstubs.install()
from PIL import Image  # noqa: E402

import output  # noqa: E402

failures: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {got!r}" + ("" if ok else f"  (want {want!r})"))
    if not ok:
        failures.append(label)


class DiskFull:
    """写了一半就报「磁盘满」的图。"""

    def save(self, path, *a, **k) -> None:
        Path(path).write_bytes(b"\x89PNG half")
        raise OSError(28, "No space left on device（假）")


class Logged(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


logged = Logged()
output.log.addHandler(logged)
when = datetime(2026, 11, 4, 12, 0, 0)
META = {"Software": "GameSnap"}
IMG = Image.new("RGB", (8, 8))


def names(folder: Path, pattern: str) -> list[str]:
    return sorted(p.name for p in folder.glob(pattern))


print("== 1、2. 写到一半失败")
root = RUN / "GameShots"
folder = root / "假游戏"
try:
    output.save_png(DiskFull(), root, "假游戏", when, META)
    error = None
except OSError as e:
    error = e.errno
check("异常照常抛出去", error, 28)
check("没留下 .png.part", names(folder, "*.part"), [])
check("也没有 .png", names(folder, "*.png"), [])
path = output.save_png(IMG, root, "假游戏", when, META)
check("下一张照常存", (path.exists(), path.name), (True, "假游戏_2026-11-04_12-00-00.png"))

real_replace, real_unlink = Path.replace, Path.unlink
calls = {"replace": 0}


def busy_replace(times: int) -> None:
    calls["replace"] = 0

    def fake(self, target):
        calls["replace"] += 1
        if calls["replace"] <= times:
            raise PermissionError(13, "另一个程序正在使用此文件（假）")
        return real_replace(self, target)
    Path.replace = fake


print("== 3. 改名时被占用两次后放开")
root = RUN / "busy_twice"
busy_replace(2)
path = output.save_png(IMG, root, "假游戏", when, META)
Path.replace = real_replace
check("存上了", path.is_file(), True)
check("试了 3 次", calls["replace"], 3)
check("没有 .png.part", names(path.parent, "*.part"), [])
check("读得出来", Image.open(path).text.get("Software"), "GameSnap")

print("== 4. 一直被占用")
root = RUN / "busy_always"
busy_replace(10_000)
try:
    output.save_png(IMG, root, "假游戏", when, META)
    error = None
except PermissionError as e:
    error = e.errno
Path.replace = real_replace
check("异常照常抛出去", error, 13)
check("试了 5 次", calls["replace"], 5)
check("没留下 .png.part", names(root / "假游戏", "*.part"), [])
check("也没有 .png", names(root / "假游戏", "*.png"), [])

print("== 5. 删 .png.part 也被占用")
root = RUN / "busy_unlink"


def no_unlink(self, missing_ok=False):
    raise PermissionError(32, "删不掉（假）")


busy_replace(10_000)
Path.unlink = no_unlink
logged.lines.clear()
try:
    output.save_png(IMG, root, "假游戏", when, META)
    error = None
except PermissionError as e:
    error = e.errno
Path.replace, Path.unlink = real_replace, real_unlink
check("抛出去的还是改名的异常", error, 13)
check(".png.part 留下了", len(names(root / "假游戏", "*.part")), 1)
check("日志记下留在哪里", any("留在了" in s and ".png.part" in s for s in logged.lines), True)
path = output.save_png(IMG, root, "假游戏", when, META)
check("下一张照常存", path.is_file(), True)

if sys.platform == "win32":
    print("== 6. 另一个句柄真的开着 .png.part")

    class Held:
        """正常存完，然后开着 .png.part 不放（Python 的 open 不给删除共享，和杀毒软件在读时一样）。"""

        def __init__(self, seconds: float | None) -> None:
            self.seconds, self.handle = seconds, None

        def save(self, path, *a, **k) -> None:
            IMG.save(path, *a, **k)
            self.handle = open(path, "rb")
            if self.seconds is not None:
                threading.Timer(self.seconds, self.handle.close).start()

    root = RUN / "held_short"
    path = output.save_png(Held(0.3), root, "假游戏", when, META)
    check("占用 0.3 秒：存上了", path.is_file(), True)
    check("占用 0.3 秒：没有 .png.part", names(path.parent, "*.part"), [])

    root = RUN / "held_long"
    img = Held(None)
    logged.lines.clear()
    try:
        output.save_png(img, root, "假游戏", when, META)
        error = None
    except PermissionError as e:
        error = e.winerror
    check("一直占用：抛出的是 WinError 32", error, 32)
    check("一直占用：日志记下留在哪里", any("留在了" in s for s in logged.lines), True)
    img.handle.close()
    parts = list((root / "假游戏").glob("*.part"))
    check("放开后 .png.part 还在", len(parts), 1)
    path = output.save_png(IMG, root, "假游戏", when, META)
    check("放开后下一张照常存", path.is_file(), True)
else:
    print("SKIP  真的占用：只在 Windows 上跑")

print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
