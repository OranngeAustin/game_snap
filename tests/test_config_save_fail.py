"""保存 config.json 时文件被短暂占用（杀毒软件、同步盘）的处理（02-findings L18）。

Config.save 以前遇到 os.replace 抛 PermissionError 就直接抛出去：内存里已经改了，调用方后面的步骤全被打断
（更换截图键后监听没换新键、没游戏时钩子不摘、托盘不刷新）。现在检查：
1. 被占用两次后放开：重试后存上了，不提示；
2. 一直被占用：set() 不抛异常、返回 False，内存里是新值，提示「设置没保存上」一次；
3. App 更换截图键时保存失败：监听照样换成新键、提示新键和「没保存上」，没游戏时钩子照样摘掉，托盘照样刷新；
4. 启动时读不出来也没另存上（Config.read_only，05-windows-verification P2）：托盘就绪时弹窗提醒一次，不挡住 setup 线程；
   平时不弹。
os.replace 换成会抛 PermissionError 的版本。纯 Python，Windows 和 Linux（tests/winstubs.py 桩）都能跑。
只在 <run dir> 里读写。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_config_save_fail.py <run dir>
"""
import json
import os
import sys
import threading
import time
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT, RUN = HERE.parent, Path(sys.argv[1])
RUN.mkdir(parents=True, exist_ok=False)
os.environ["APPDATA"] = str(RUN / "appdata")
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PROJECT))
import winstubs  # noqa: E402

winstubs.install()
import config  # noqa: E402
import main  # noqa: E402

failures: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {got!r}" + ("" if ok else f"  (want {want!r})"))
    if not ok:
        failures.append(label)


real_replace = os.replace
busy = {"left": 0}


def flaky_replace(src, dst):
    if busy["left"]:
        busy["left"] -= 1
        raise PermissionError(13, "另一个程序正在使用此文件（假）")
    return real_replace(src, dst)


cfg_path = RUN / "config.json"
cfg_path.write_text(json.dumps({"games": {"FakeGame.exe": "假游戏"}, "hotkey": {"type": "key", "vk": 0x87},
                                "toast": True, "sound": False, "copy_to_clipboard": False,
                                "dualsense_quad": False, "save_dir": str(RUN / "shots")},
                               ensure_ascii=False), encoding="utf-8")
cfg = config.Config(cfg_path)
errors: list[int] = []
cfg.on_save_error = lambda: errors.append(1)
os.replace = flaky_replace


def on_disk(key):
    return json.loads(cfg_path.read_text(encoding="utf-8"))[key]


print("== 1. 被占用两次后放开")
busy["left"] = 2
try:
    cfg.set("sound", True)
    error = None
except Exception as e:   # noqa: BLE001
    error = type(e).__name__
check("不抛异常", error, None)
check("重试后存上了", on_disk("sound"), True)
check("不提示", errors, [])

print("== 2. 一直被占用")
busy["left"] = 10_000
try:
    result, error = cfg.set("toast", False), None
except Exception as e:   # noqa: BLE001
    result, error = None, type(e).__name__
check("不抛异常", error, None)
check("set() 返回 False", result, False)
check("内存里是新值", cfg["toast"], False)
check("文件里还是旧值", on_disk("toast"), True)
check("提示了一次", errors, [1])
busy["left"] = 0


class FakeListener:
    made: list["FakeListener"] = []

    def __init__(self, binding, *a, **k) -> None:
        self.binding, self.stopped = dict(binding), False
        FakeListener.made.append(self)

    def start(self) -> None:
        pass

    def wait_ready(self, timeout: float = 2) -> bool:
        return True

    def stop(self) -> None:
        self.stopped = True

    def start_learning(self) -> None:
        pass

    def set_binding(self, binding) -> None:
        self.binding = dict(binding)


print("== 3. 更换截图键时保存失败")
main.InputListener = FakeListener
main.LEARN_TIMEOUT_SEC = 60
main.winsound.MessageBeep = lambda *a: None
app = main.App(cfg)
toasts: list[str] = []
app.toast = types.SimpleNamespace(show=lambda text, ok, rect, hold_ms=None: toasts.append(text))
refreshed: list[int] = []
app.icon = types.SimpleNamespace(icon=None, title="", update_menu=lambda: refreshed.append(1))
app.worker.post = lambda *msg: None
app.start_learning()
lis = FakeListener.made[-1]
busy["left"] = 10_000
toasts.clear()
refreshed.clear()
try:
    app._finish_learning({"type": "key", "vk": 0x86})
    error = None
except Exception as e:   # noqa: BLE001
    error = type(e).__name__
busy["left"] = 0
check("不抛异常", error, None)
check("监听换成新键", lis.binding, {"type": "key", "vk": 0x86})
check("提示了新键", any(t.startswith("截图键已设为") for t in toasts), True)
check("提示了没保存上", any("没保存上" in t for t in toasts), True)
check("没游戏：钩子摘掉了", (lis.stopped, app.listener), (True, None))
check("托盘刷新了", len(refreshed) > 0, True)
os.replace = real_replace

print("== 4. 启动时读不出来也没另存上：弹窗提醒")
boxes: list[str] = []
release = threading.Event()


def box(text: str) -> None:
    boxes.append(text)
    release.wait(5)   # 模拟对话框一直没人点


main.message_box = box
app.watcher = types.SimpleNamespace(start=lambda: None)
app.dualsense = types.SimpleNamespace(start=lambda: None)
app.refresh_tray = lambda: None
served: list[int] = []
app.on_tray_ready = lambda: served.append(1)
tray = types.SimpleNamespace(visible=False)
app._on_tray_ready(tray)
check("平时不弹", boxes, [])
cfg.read_only = True
served.clear()
app._on_tray_ready(tray)   # 对话框没人点也要立刻返回
check("等单实例退出信号的那一步照常走", served, [1])
notice = next(t for t in threading.enumerate() if t.name == "ReadOnlyNotice")
check("弹窗在后台线程里", notice.daemon, True)
for _ in range(100):
    if boxes:
        break
    time.sleep(0.01)
check("弹了一次", len(boxes), 1)
check("写明了是哪个文件", str(cfg.path) in boxes[0] if boxes else None, True)
release.set()
notice.join(5)
toasts.clear()
check("这时 set() 不写文件", (cfg.set("sound", False), on_disk("sound")), (False, True))
check("这时也提示没保存上", any("没保存上" in t for t in toasts), True)

print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
