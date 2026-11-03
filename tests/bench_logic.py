"""截图之后那段纯 Python / PIL 链路的耗时基准，Windows 和 Linux（云端容器，靠 winstubs 桩）都能跑。
只测量，不判对错。每项跑 ROUNDS 轮、每轮循环若干次取平均，报告各轮的中位数（毫秒 / 次）；
copy_to_clipboard 另报 tracemalloc 记到的 Python 侧峰值内存（PIL 自己的像素缓冲区不在其中）。

测的都是项目里的真函数：
  make_icon（每次 refresh_tray）、render_card + _premultiplied_bgra（每次提示）、copy_to_clipboard（每张截图，
  win32clipboard 换成只记录数据的假模块，不碰真剪贴板）、save_png（每张截图）、to_image 里的 BGRX→RGB 解码、
  _is_black、ProcessScanner.scan（每次轮询，进程列表是假的）。
不包括 Win32 / WGC / D3D 的部分（抓帧、托盘、浮层窗口），那些只能在 Windows 上实测（见 bench_startup.py）。

字体：Windows 上 render_card 用的是 C:\\Windows\\Fonts\\msyh.ttc，Pillow 第一下就找到。Linux 上没有它，Pillow 会把
字体目录整个翻一遍再退回默认字体，耗时完全不像 Windows。所以在 Linux 上，如果有 wqy-zenhei.ttc（约 16MB 的中文 TTC，
和 msyh.ttc 差不多大），就在临时目录里把它链接成 msyh.ttc 并切到那个目录，让 Pillow 一下就找到。

usage: python -X utf8 tests/bench_logic.py [轮数，默认 5] [--only 名字,名字]
"""
from __future__ import annotations

import os
import random
import statistics
import sys
import tempfile
import time
import tracemalloc
import types
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import winstubs  # noqa: E402

winstubs.install()

from PIL import Image  # noqa: E402

import capture  # noqa: E402
import config  # noqa: E402
import main  # noqa: E402
import output  # noqa: E402
import toast  # noqa: E402
import watcher  # noqa: E402

args = sys.argv[1:]
only = None
if "--only" in args:
    i = args.index("--only")
    only = set(args[i + 1].split(","))
    del args[i:i + 2]
ROUNDS = int(args[0]) if args else 5
W, H = 1920, 1080

# ---------------------------------------------------------------- 假剪贴板：只记下写进去的数据
clip = types.ModuleType("win32clipboard")
clip.CF_DIB = 8
clip.data = None
clip.OpenClipboard = lambda *a: None
clip.CloseClipboard = lambda: None
clip.EmptyClipboard = lambda: None


def _set_clipboard(fmt, data):
    clip.data = data


clip.SetClipboardData = _set_clipboard
sys.modules["win32clipboard"] = clip

# ---------------------------------------------------------------- 字体：Linux 上模拟 Windows 的 msyh.ttc
font_note = "Windows 自带 msyh.ttc" if sys.platform == "win32" else "Linux 默认字体（找不到 msyh.ttc，Pillow 会遍历字体目录）"
WQY = Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")
if sys.platform != "win32" and WQY.is_file():
    font_dir = Path(tempfile.mkdtemp(prefix="gamesnap_font_"))
    (font_dir / "msyh.ttc").symlink_to(WQY)
    os.chdir(font_dir)
    font_note = f"msyh.ttc → {WQY.name}（{WQY.stat().st_size // 2**20}MB，模拟 Windows 一下就找到字体）"


def game_like_frame(w: int = W, h: int = H, seed: int = 1) -> Image.Image:
    """像游戏画面的测试图：大块渐变 + 一些噪声块（纯噪声压缩不动，纯色又压得太狠，都不像真画面）。"""
    rnd = random.Random(seed)
    base = Image.linear_gradient("L").resize((w, h))
    img = Image.merge("RGB", (base, base.rotate(90).resize((w, h)),
                              base.transpose(Image.Transpose.FLIP_LEFT_RIGHT)))
    for _ in range(40):
        bw, bh = rnd.randint(40, 300), rnd.randint(40, 200)
        x, y = rnd.randint(0, w - bw), rnd.randint(0, h - bh)
        img.paste(Image.effect_noise((bw, bh), rnd.randint(10, 80)).convert("RGB"), (x, y))
    return img


def bench(name: str, fn, loops: int) -> None:
    if only and name not in only:
        return
    fn()   # 预热（导入、缓存）
    per_round = []
    for _ in range(ROUNDS):
        t0 = time.perf_counter()
        for _ in range(loops):
            fn()
        per_round.append((time.perf_counter() - t0) / loops * 1000)
    med = statistics.median(per_round)
    print(f"{name:<20} {med:9.3f} ms  (rounds: {', '.join(f'{x:.3f}' for x in per_round)})", flush=True)


def peak_python_mb(fn) -> float:
    tracemalloc.start()
    fn()
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    return peak / 2**20


frame = game_like_frame()
bgrx = frame.convert("RGBA").tobytes("raw", "BGRA")   # 和 D3D 暂存纹理一样的 BGRX 排列，pitch = 4*W
card = toast.render_card("已截图 · 原神", True, 1.5)
tmp = Path(tempfile.mkdtemp(prefix="gamesnap_bench_"))
when = datetime(2026, 11, 3, 12, 0, 0)
meta = {"Software": "GameSnap", "GameSnap": "game=原神; backend=wgc"}


def png_once() -> None:
    output.save_png(frame, tmp, "原神", when, meta).unlink()


class _FakeScanner(watcher.ProcessScanner):
    """300 个进程、其中 1 个游戏 1 个启动器；pid 不变时不做快照（和真实情况一样）。"""
    def __init__(self) -> None:
        super().__init__()
        self.all = {4 * i: f"proc{i}.exe" for i in range(1, 300)}
        self.all[4000] = "yuanshen.exe"
        self.all[4004] = "hyp.exe"

    def _pids(self) -> set[int]:
        return set(self.all)


scanner = _FakeScanner()
watcher.snapshot_names = lambda lower=True: dict(scanner.all)
games_lower = {k.lower(): v for k, v in config.DEFAULTS["games"].items()}

print(f"GameSnap bench_logic  {datetime.now():%Y-%m-%d %H:%M:%S}  python {sys.version.split()[0]}  "
      f"platform {sys.platform}  rounds {ROUNDS}  frame {W}x{H}\n字体：{font_note}")
bench("make_icon", lambda: main.make_icon("active"), 50)
bench("render_card", lambda: toast.render_card("已截图 · 原神", True, 1.5), 30)
bench("premultiplied_bgra", lambda: toast._premultiplied_bgra(card), 200)
bench("copy_to_clipboard", lambda: output.copy_to_clipboard(frame), 10)
bench("save_png", png_once, 3)
bench("to_image_decode", lambda: Image.frombuffer("RGB", (W, H), bgrx, "raw", "BGRX", 4 * W, 1), 20)
bench("is_black", lambda: capture._is_black(frame), 50)
bench("scanner_scan", lambda: scanner.scan(games_lower, {"hyp.exe"}), 2000)
if not only or "copy_to_clipboard" in only:
    print(f"copy_to_clipboard    Python 侧峰值内存 {peak_python_mb(lambda: output.copy_to_clipboard(frame)):.1f} MB"
          f"（一帧 RGB 是 {W * H * 3 / 2**20:.1f} MB）")
