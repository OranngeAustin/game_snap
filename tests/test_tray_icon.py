"""main.make_icon（托盘图标）的特征测试：固定它画出来的图和调用语义。
1. 三种状态（idle / active / paused）的图逐字节等于参照实现（下面 reference 是 make_icon 原来的绘制代码）；
   64×64、RGBA；
2. 每次调用都返回新对象：改了返回的图，下一次调用不受影响（build.py 拿它存 .ico，托盘拿它显示）；
3. 不认识的状态抛 KeyError。
Windows 和 Linux（winstubs 桩）都能跑。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_tray_icon.py <run dir>
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT, RUN = HERE.parent, Path(sys.argv[1])
RUN.mkdir(parents=True, exist_ok=False)
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PROJECT))
import winstubs  # noqa: E402

winstubs.install()
from PIL import Image, ImageDraw  # noqa: E402

import main  # noqa: E402

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(label)


def reference(state: str) -> Image.Image:
    bg = {"idle": (142, 142, 147), "active": (52, 199, 89), "paused": (255, 159, 10)}[state]
    s = 256
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 8, s - 8, s - 8], radius=56, fill=bg)
    d.rounded_rectangle([44, 84, 212, 196], radius=22, fill="white")
    d.rounded_rectangle([92, 60, 164, 96], radius=12, fill="white")
    d.ellipse([90, 102, 166, 178], fill=bg)
    d.ellipse([108, 120, 148, 160], fill="white")
    return img.resize((64, 64), Image.Resampling.LANCZOS)


print("== 1. pixels")
for state in ("idle", "active", "paused"):
    for n in (1, 2):   # 第二次调用（有缓存时走缓存）也要一样
        img = main.make_icon(state)
        check(f"{state} #{n}: 64x64 RGBA", img.size == (64, 64) and img.mode == "RGBA", f"{img.size} {img.mode}")
        check(f"{state} #{n}: same pixels as reference", img.tobytes() == reference(state).tobytes())

print("== 2. a fresh object every call")
a, b = main.make_icon("active"), main.make_icon("active")
check("two calls give two objects", a is not b)
a.paste((255, 0, 0, 255), (0, 0, 64, 64))
check("changing one does not change the next", main.make_icon("active").tobytes() == reference("active").tobytes())

print("== 3. unknown state")
try:
    main.make_icon("busy")
    check("unknown state raises KeyError", False, "no exception")
except KeyError:
    check("unknown state raises KeyError", True)

print("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
