"""按键监听启动失败后不能静默失效（02-findings M4）。

InputListener.run() 里建窗口或挂键盘钩子失败时，以前只记一条日志就 _ready.set() 返回，wait_ready() 照样返回 True；
App 留着这个已经结束的对象，直到游戏名单再次变空才重建。这期间截图键、更换截图键、添加游戏都没反应，用户只看到没反应。
现在检查：
1. 真的 InputListener（hotkey.create_window 换成一调用就报错，不建窗口、不挂钩子）：启动失败时 wait_ready() 返回 False，线程结束；
2. App 检测到游戏时监听启动失败：不留下死掉的监听，提示一次；之后再需要监听时（例如点「更换截图键…」）重新建；
3. 点「更换截图键…」时监听启动失败：learning 立即复位（不会卡在学键状态、挡住自动退出），不抛异常；
4. 点「添加游戏…」时监听启动失败：adding 立即复位、等待计时器取消，不抛异常；
5. 启动只是慢（wait_ready 超时但线程还活着）：照旧留着这个监听，不另建一个（否则可能挂上两个钩子）。
App 部分用测试配置建真的 main.App，toast、托盘图标、截图线程的 post、自动退出换成桩，InputListener 换成可控的假监听。
纯 Python，Windows 和 Linux（tests/winstubs.py 桩）都能跑。只在 <run dir> 里读写。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_listener_start_fail.py <run dir>
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT, RUN = HERE.parent, Path(sys.argv[1])
RUN.mkdir(parents=True, exist_ok=False)
os.environ["APPDATA"] = str(RUN / "appdata")   # config.APP_DIR 在 import 时就定了
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PROJECT))
import winstubs  # noqa: E402

winstubs.install()
import hotkey  # noqa: E402
import main  # noqa: E402
from config import Config  # noqa: E402

failures: list[str] = []
GAME = {4242: "假游戏"}


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {got!r}" + ("" if ok else f"  (want {want!r})"))
    if not ok:
        failures.append(label)


print("== 1. 真的 InputListener 启动失败")
real_create_window = hotkey.create_window


def broken_create_window(*args, **kwargs):
    raise OSError("建窗口失败（测试）")


hotkey.create_window = broken_create_window
lis = hotkey.InputListener({"type": "key", "vk": 0x87}, lambda pid: False, lambda *a: None,
                           lambda *a: None, lambda b: None)
lis.start()
check("wait_ready() 返回 False", lis.wait_ready(3), False)
lis.join(3)
check("线程已结束", lis.is_alive(), False)
hotkey.create_window = real_create_window


class StubToast:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def show(self, text, ok, rect, hold_ms=None) -> None:
        self.calls.append((text, ok))


class StubIcon:
    icon = None
    title = ""

    def update_menu(self) -> None:
        pass


class FakeListener:
    """mode：ok = 正常启动；fail = 启动失败（线程已结束）；slow = wait_ready 超时但线程还活着。"""
    mode = "ok"
    made: list["FakeListener"] = []

    def __init__(self, binding, should_capture, on_shot, on_foreground, on_learned) -> None:
        self.mode = FakeListener.mode
        self.started = self.stopped = self.learning = False
        FakeListener.made.append(self)

    def start(self) -> None:
        self.started = True

    def wait_ready(self, timeout: float = 2) -> bool:
        return self.mode == "ok"

    def join(self, timeout=None) -> None:
        pass

    def is_alive(self) -> bool:
        return self.started and self.mode != "fail" and not self.stopped

    def stop(self) -> None:
        self.stopped = True

    def start_learning(self) -> None:
        self.learning = True

    def cancel_learning(self) -> None:
        self.learning = False


print("== setup")
cfg_path = RUN / "config.json"
cfg_path.write_text(json.dumps({
    "games": {"FakeGame.exe": "假游戏"}, "launchers": ["fakehyp.exe"],
    "hotkey": {"type": "key", "vk": 0x87}, "toast": True, "sound": False, "copy_to_clipboard": False,
    "dualsense_quad": False, "save_dir": str(RUN / "shots"),
}, ensure_ascii=False, indent=2), encoding="utf-8")
main.InputListener = FakeListener
main.LEARN_TIMEOUT_SEC = 60
main.ADD_TIMEOUT_SEC = 60
app = main.App(Config(cfg_path))
toast = app.toast = StubToast()
app.icon = StubIcon()
app.worker.post = lambda *msg: None
app._quit = lambda icon, item: None


def failure_toasts() -> int:
    return sum("按键监听" in text and not ok for text, ok in toast.calls)


print("== 2. 检测到游戏时监听启动失败")
FakeListener.mode = "fail"
app._on_games_changed(dict(GAME))
check("不留下死掉的监听", app.listener, None)
check("提示了一次", failure_toasts(), 1)
FakeListener.mode = "ok"
app.start_learning()
check("再需要监听时重新建了一个", (app.listener is FakeListener.made[-1], app.listener.mode, app.listener.started),
      (True, "ok", True))
check("这次学键正常开始", (app.learning, app.listener.learning), (True, True))
app._learn_timeout()
check("学键结束，游戏还在，监听留着", (app.learning, app.listener is not None), (False, True))
app._on_games_changed({})
check("游戏退出后摘掉", app.listener, None)

print("== 3. 点「更换截图键…」时监听启动失败")
toast.calls.clear()
FakeListener.mode = "fail"
try:
    app.start_learning()
    error = None
except Exception as e:   # noqa: BLE001
    error = f"{type(e).__name__}: {e}"
check("不抛异常", error, None)
check("learning 立即复位", app.learning, False)
check("没有监听", app.listener, None)
check("提示了", failure_toasts(), 1)
check("学键计时器没开", app._learn_timer is None or not app._learn_timer.is_alive(), True)

print("== 4. 点「添加游戏…」时监听启动失败")
toast.calls.clear()
try:
    app.start_adding()
    error = None
except Exception as e:   # noqa: BLE001
    error = f"{type(e).__name__}: {e}"
check("不抛异常", error, None)
check("adding 立即复位", app.adding, False)
check("等待计时器取消了", app._add_timer is not None and app._add_timer.finished.is_set(), True)
check("没有监听", app.listener, None)
check("提示了", failure_toasts(), 1)

print("== 5. 启动只是慢：照旧留着，不另建")
FakeListener.mode = "slow"
n = len(FakeListener.made)
app._on_games_changed(dict(GAME))
check("留着这个监听", app.listener is FakeListener.made[-1] and app.listener is not None, True)
check("只建了一个", len(FakeListener.made) - n, 1)
app.start_learning()
check("学键用的就是它", (len(FakeListener.made) - n, app.listener.learning), (1, True))
app._learn_timeout()
app._on_games_changed({})

print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
