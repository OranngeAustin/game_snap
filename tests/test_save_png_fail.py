"""save_png 写到一半失败（磁盘满、被占用）时不留下半截文件（02-findings L11）。

save_png 先写 <名字>.png.part 再改名。以前 img.save 抛异常时 .png.part 留在截图文件夹里，越积越多。现在检查：
1. 写到一半抛异常：异常照常抛出去（finish_shot 会提示「截图失败」），文件夹里没有 .png.part，也没有 .png；
2. 正常保存不受影响，下一张照常存。
只在 <run dir> 里读写。纯 Python，Windows 和 Linux（tests/winstubs.py 桩）都能跑。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_save_png_fail.py <run dir>
"""
import sys
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


when = datetime(2026, 11, 4, 12, 0, 0)
folder = RUN / "GameShots" / "假游戏"
try:
    output.save_png(DiskFull(), RUN / "GameShots", "假游戏", when, {"Software": "GameSnap"})
    error = None
except OSError as e:
    error = e.errno
check("异常照常抛出去", error, 28)
check("没留下 .png.part", sorted(p.name for p in folder.glob("*.part")), [])
check("也没有 .png", sorted(p.name for p in folder.glob("*.png")), [])
path = output.save_png(Image.new("RGB", (8, 8)), RUN / "GameShots", "假游戏", when, {"Software": "GameSnap"})
check("下一张照常存", (path.exists(), path.name), (True, "假游戏_2026-11-04_12-00-00.png"))

print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
