"""退出看门狗（05 文档 P7）。

退出时托盘菜单开着，pystray 的 WM_QUIT 被菜单的模态循环吃掉，主线程关掉菜单后一直等在 GetMessage，进程留下了。
现在 main() 给 App.on_quitting 挂上 start_exit_watchdog：到时间消息循环还没退出就直接结束进程。检查：
1. 看门狗：到时间之前不动手；到时间去掉托盘图标、结束进程（退出码 0）、日志记一笔；去图标出错也照样结束。
2. App._quit：先开看门狗再 icon.stop()（stop 可能阻塞、可能抛异常）；前面的步骤出错也开；看门狗开不起来也让托盘退出；
   重复调用只开一次；没设 on_quitting（测试里建的 App）时不开，不会把测试进程结束掉。
os._exit、logging.shutdown 换成只记录的桩，不真的结束进程。真实进程里丢了 WM_QUIT 的情况见 test_exit_stuck.py。
纯 Python，Windows 和 Linux（tests/winstubs.py 桩）都能跑。只在 <run dir> 里读写。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_exit_watchdog.py <run dir>
"""
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT, RUN = HERE.parent, Path(sys.argv[1])
RUN.mkdir(parents=True, exist_ok=False)
os.environ["APPDATA"] = str(RUN / "appdata")   # config.APP_DIR 在 import 时就定了
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PROJECT))
import winstubs  # noqa: E402

winstubs.install()
import main  # noqa: E402
from config import Config  # noqa: E402

failures: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {got!r}" + ("" if ok else f"  (want {want!r})"))
    if not ok:
        failures.append(label)


class Records(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


class WatchedIcon:
    """只记 visible 被设成了什么；raises=True 时设的时候抛异常。"""
    icon = None
    title = ""

    def __init__(self, raises: bool = False) -> None:
        self.raises = raises
        self.set_to: list[bool] = []

    @property
    def visible(self) -> bool:
        return True

    @visible.setter
    def visible(self, value: bool) -> None:
        self.set_to.append(value)
        if self.raises:
            raise OSError("测试：去图标失败")


records = Records()
main.log.addHandler(records)
main.log.setLevel(logging.INFO)
exits: list[int] = []
exited = threading.Event()
shutdowns: list[int] = []


def fake_exit(code: int) -> None:
    exits.append(code)
    exited.set()


real_exit, real_shutdown = os._exit, logging.shutdown
os._exit = fake_exit
logging.shutdown = lambda: shutdowns.append(1)
main.EXIT_WATCHDOG_SEC = 0.5

print("== 1. 看门狗")
icon = WatchedIcon()
t0 = time.monotonic()
main.start_exit_watchdog(icon)
time.sleep(0.2)
check("到时间之前不动手", (exits, icon.set_to), ([], []))
check("到时间结束进程", exited.wait(3), True)
check("等够了时间才动手", time.monotonic() - t0 >= 0.45, True)
check("退出码 0", exits, [0])
check("托盘图标去掉了", icon.set_to, [False])
check("日志冲刷过", shutdowns, [1])
check("日志里记了一笔", any("消息循环" in s and "直接结束进程" in s for s in records.lines), True)

exits.clear()
exited.clear()
records.lines.clear()
icon = WatchedIcon(raises=True)
main.start_exit_watchdog(icon)
check("去图标出错也照样结束", exited.wait(3), True)
check("退出码 0（去图标出错）", exits, [0])
check("错误记进日志", "去掉托盘图标时出错" in records.lines, True)
exits.clear()
exited.clear()

print("== 2. App._quit")
cfg_path = RUN / "config.json"
cfg_path.write_text(json.dumps({"games": {"FakeGame.exe": "假游戏"}, "toast": False, "sound": False,
                                "dualsense_quad": False, "save_dir": str(RUN / "shots")},
                               ensure_ascii=False), encoding="utf-8")


class StubToast:
    def stop(self) -> None:
        pass


class StubIcon:
    icon = None
    title = ""
    visible = False

    def __init__(self, order: list[str]) -> None:
        self.order = order

    def update_menu(self) -> None:
        pass

    def stop(self) -> None:
        self.order.append("icon.stop")


keep_icons: list = []


def make_app() -> tuple[main.App, StubIcon, list[str]]:
    app = main.App(Config(cfg_path))
    # pystray 的窗口类名里有 id(icon)，用完也不注销：旧图标被回收后地址可能给新图标，注册时报「类已存在」。留着不回收
    keep_icons.append(app.icon)
    order: list[str] = []
    stub = app.icon = StubIcon(order)
    app.toast = StubToast()
    return app, stub, order


app, stub, order = make_app()
app.on_quitting = lambda: order.append("on_quitting")
app._quit(stub, None)
check("先开看门狗，再让托盘退出", order, ["on_quitting", "icon.stop"])
app._quit(stub, None)
check("重复调用只开一次", order, ["on_quitting", "icon.stop"])

app, stub, order = make_app()
app.on_quitting = lambda: order.append("on_quitting")


def boom() -> None:
    raise RuntimeError("测试：停检测线程失败")


app.watcher.stop = boom
app._quit(stub, None)
check("前面的步骤出错也开看门狗", order, ["on_quitting", "icon.stop"])

app, stub, order = make_app()


def no_thread() -> None:
    order.append("on_quitting")
    raise RuntimeError("测试：线程开不起来")


app.on_quitting = no_thread
try:
    app._quit(stub, None)
    error = None
except RuntimeError as e:
    error = str(e)
check("看门狗开不起来也让托盘退出", order, ["on_quitting", "icon.stop"])
check("这个异常不抛给调用方（和前面的步骤一样记日志）", error, None)

app, stub, order = make_app()
check("默认不设 on_quitting", app.on_quitting, None)
app._quit(stub, None)
check("没设时只让托盘退出", order, ["icon.stop"])
time.sleep(0.8)
check("没设时不会结束进程", exits, [])

os._exit, logging.shutdown = real_exit, real_shutdown
print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
