"""截图文件夹 / 文件名的清洗 output._safe_name（02-findings M2）。

游戏名来自 config.json，或者 yuzu 的窗口标题（即 ROM 里的元数据），什么都可能有。以前只替换 \\ / : * ? " < > |：
游戏名 ".." 会把截图写到 GameShots 的上一级，"." 写进 GameShots 根目录；CON、NUL、COM1 这类 Windows 保留名建不了文件夹；
控制字符让保存直接报错；名字太长时路径超长，这个游戏每张都「截图失败」。检查：
1. 以前就能用的名字一个字都不改（中文、普通英文、带非法字符的、首尾空格、以点开头的 .hack、80 个字符以内的）；
2. 只由点和空格组成的名字用「未知游戏」，控制字符换成 _，保留名前面加 _，超过 80 个字符的截断（截断后不留尾部空格和点）；
3. save_png 用 ".." 当游戏名时，截图仍在截图根目录里面。
只在 <run dir> 里读写。纯 Python，Windows 和 Linux（tests/winstubs.py 桩）都能跑。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_safe_name.py <run dir>
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


print("== 1. 以前就能用的名字不变")
SAME = [
    ("原神", "原神"),
    ("崩坏：星穹铁道", "崩坏：星穹铁道"),
    ("The Legend of Zelda: Tears of the Kingdom", "The Legend of Zelda_ Tears of the Kingdom"),
    ('a/b\\c:d*e?f"g<h>i|j', "a_b_c_d_e_f_g_h_i_j"),
    ("  Hollow Knight  ", "Hollow Knight"),
    ("", "未知游戏"),
    ("   ", "未知游戏"),
    ("\tName\t", "Name"),
    (".hack//G.U.", ".hack__G.U."),
    ("CONSOLE", "CONSOLE"),
    ("COM10", "COM10"),
    ("Con Game", "Con Game"),
    ("Nul Ex Machina", "Nul Ex Machina"),
    ("A" * 80, "A" * 80),
]
for name, want in SAME:
    check(f"_safe_name({name!r})", output._safe_name(name), want)

print("== 2. 以前会出错的名字")
FIXED = [
    (".", "未知游戏"),
    ("..", "未知游戏"),
    ("...", "未知游戏"),
    (" . . ", "未知游戏"),
    ("A\x00B", "A_B"),
    ("Tab\tName", "Tab_Name"),
    ("Line\nBreak\r", "Line_Break"),
    ("CON", "_CON"),
    ("nul", "_nul"),
    ("Com1", "_Com1"),
    ("LPT9", "_LPT9"),
    ("PRN.txt", "_PRN.txt"),
    ("AUX  ", "_AUX"),
]
for name, want in FIXED:
    check(f"_safe_name({name!r})", output._safe_name(name), want)
long_name = output._safe_name("Z" * 200)
check("200 个字符截到 80", len(long_name), 80)
cut = output._safe_name("x" * 79 + " yz")
check("截断后不留尾部空格", cut, "x" * 79)
cut = output._safe_name("y" * 79 + ".zz")
check("截断后不留尾部的点", cut, "y" * 79)

print("== 3. save_png 不会写到截图根目录外面")
root = RUN / "GameShots"
img = Image.new("RGB", (8, 8), (10, 20, 30))
when = datetime(2026, 11, 4, 12, 0, 0)
try:
    path = output.save_png(img, root, "..", when, {"Software": "GameSnap"})
    inside = root.resolve() in path.resolve().parents
    where = str(path.relative_to(RUN))
except Exception as e:   # noqa: BLE001
    inside, where = False, f"{type(e).__name__}: {e}"
check("游戏名 '..'：截图在根目录里面", inside, True)
print(f"      → {where}")
path = output.save_png(img, root, "Z" * 200, when, {"Software": "GameSnap"})
check("长名字：文件夹名 80 个字符", len(path.parent.name), 80)
check("长名字：存下来了", path.exists(), True)

print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
