"""写剪贴板时出错（02-findings L10）。

copy_to_clipboard 以前只在 OpenClipboard 失败时重试，EmptyClipboard / SetClipboardData 抛异常会一路冒到 App.finish_shot：
PNG 明明已经存好，却提示「截图失败」、计数不加。现在检查：
1. EmptyClipboard 或 SetClipboardData 抛异常：copy_to_clipboard 返回 False、不抛出去，剪贴板照样关上；
2. App.finish_shot 里写剪贴板失败：仍提示「已截图」，计数加一，PNG 在。
win32clipboard 换成假的，不碰真剪贴板。纯 Python，Windows 和 Linux（tests/winstubs.py 桩）都能跑。
只在 <run dir> 里读写。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_clipboard_error.py <run dir>
"""
import json
import os
import sys
import types
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT, RUN = HERE.parent, Path(sys.argv[1])
RUN.mkdir(parents=True, exist_ok=False)
os.environ["APPDATA"] = str(RUN / "appdata")
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PROJECT))
import winstubs  # noqa: E402

winstubs.install()
from PIL import Image  # noqa: E402

failures: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {got!r}" + ("" if ok else f"  (want {want!r})"))
    if not ok:
        failures.append(label)


clip = types.ModuleType("win32clipboard")
clip.CF_DIB = 8
clip.calls = []
clip.fail_in = ""


def _call(name):
    def f(*a):
        clip.calls.append(name)
        if name == clip.fail_in:
            raise RuntimeError(f"{name} 出错（假）")
    return f


for _n in ("OpenClipboard", "EmptyClipboard", "SetClipboardData", "CloseClipboard"):
    setattr(clip, _n, _call(_n))
sys.modules["win32clipboard"] = clip

import main  # noqa: E402
import output  # noqa: E402
from config import Config  # noqa: E402

img = Image.new("RGB", (16, 9), (40, 80, 120))
print("== 1. copy_to_clipboard 内部出错")
for where in ("EmptyClipboard", "SetClipboardData"):
    clip.calls, clip.fail_in = [], where
    try:
        result, error = output.copy_to_clipboard(img), None
    except Exception as e:   # noqa: BLE001
        result, error = None, f"{type(e).__name__}: {e}"
    check(f"{where} 出错：不抛异常", error, None)
    check(f"{where} 出错：返回 False", result, False)
    check(f"{where} 出错：剪贴板关上了", clip.calls.count("CloseClipboard"), 1)
clip.calls, clip.fail_in = [], ""
check("正常时返回 True", output.copy_to_clipboard(img), True)

print("== 2. finish_shot：剪贴板失败不算截图失败")
cfg_path = RUN / "config.json"
cfg_path.write_text(json.dumps({"games": {"FakeGame.exe": "假游戏"}, "toast": True, "sound": False,
                                "copy_to_clipboard": True, "dualsense_quad": False,
                                "save_dir": str(RUN / "shots")}, ensure_ascii=False), encoding="utf-8")
if not main.QPC_FREQ:
    main.QPC_FREQ = 10_000_000   # Linux 桩下 QueryPerformanceFrequency 是假的
app = main.App(Config(cfg_path))
toasts: list[tuple[str, bool]] = []
app.toast = types.SimpleNamespace(show=lambda text, ok, rect, hold_ms=None: toasts.append((text, ok)))
app.icon = types.SimpleNamespace(icon=None, title="", update_menu=lambda: None)
shot = types.SimpleNamespace(image=img, backend="wgc", frame_ticks=100, grabbed_ticks=200)
clip.calls, clip.fail_in = [], "SetClipboardData"
app.finish_shot(shot, "假游戏", datetime(2026, 11, 4, 12, 0, 0), 50, (0, 0, 1920, 1080))
check("提示「已截图」", toasts[-1:], [("已截图 · 假游戏", True)])
check("计数加一", app.shot_count, 1)
check("PNG 存下来了", len(list((RUN / "shots" / "假游戏").glob("*.png"))), 1)

print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
