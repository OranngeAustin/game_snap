"""按键监听「该不该挂」的判断和真正挂 / 摘不能被别的线程插进来（02-findings M7）。

用测试配置建真的 main.App：toast、托盘图标、截图线程的 post、自动退出都换成桩，main.InputListener 换成只记状态的
FakeListener，不挂钩子、不发按键。App 的 games / learning / adding 换成属性：arm() 之后，被测线程第一次读到指定属性时，
先在另一个线程里做一件事（相当于用户恰好在这一刻点了托盘菜单，或者 GameWatcher 恰好在这一刻检测到游戏），
再把「读的那一刻」的旧值返回。这样 M7 说的几种交错每次都一样地发生，不靠运气：

A. 游戏全部退出的同时点「更换截图键…」：监听必须还在、处于学键状态；10 秒超时后 learning 复位、监听摘掉、能自动退出。
B. 游戏全部退出的同时点「添加游戏…」：等按键期间监听必须还在；超时后摘掉。
C. 取消更换截图键的同时检测到游戏：这局游戏的监听必须挂着。
D. 添加游戏超时的同时检测到游戏：同上。
另有不插队时的基本行为：没游戏时学键挂上、结束摘掉；有游戏时学键结束不摘。

插进来的动作在新代码里会在 App._listener_lock 上等着：等 0.5 秒还没做完就让被测线程先往下走，锁放开后它接着做完。
纯 Python，Windows 和 Linux（tests/winstubs.py 桩）都能跑。只在 <run dir> 里读写。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_listener_sync.py <run dir>
"""
import json
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
GAME = {4242: "假游戏"}


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {got!r}" + ("" if ok else f"  (want {want!r})"))
    if not ok:
        failures.append(label)


class StubToast:
    def show(self, text, ok, rect, hold_ms=None) -> None:
        pass


class StubIcon:
    icon = None
    title = ""

    def update_menu(self) -> None:
        pass


class FakeListener:
    made: list["FakeListener"] = []

    def __init__(self, binding, should_capture, on_shot, on_foreground, on_learned) -> None:
        self.binding = dict(binding)
        self.started = self.stopped = self.learning = False
        FakeListener.made.append(self)

    def start(self) -> None:
        self.started = True

    def wait_ready(self, timeout: float = 2) -> bool:
        return True

    def stop(self) -> None:
        self.stopped = True

    def start_learning(self) -> None:
        self.learning = True

    def cancel_learning(self) -> None:
        self.learning = False

    def set_binding(self, binding: dict) -> None:
        self.binding = dict(binding)


VICTIM = "被插队的线程"
injected: list[threading.Thread] = []


class RaceApp(main.App):
    """games / learning / adding 读写都经过这里；arm 之后 VICTIM 线程第一次读那个属性时先插进一个动作。"""
    _armed = None   # (属性名, 动作)

    def _read(self, name: str):
        value = self.__dict__[name]
        armed = self._armed
        if armed and armed[0] == name and threading.current_thread().name == VICTIM:
            self._armed = None
            t = threading.Thread(target=armed[1], name="插进来的线程", daemon=True)
            t.start()
            t.join(0.5)
            injected.append(t)
        return value


for _name in ("games", "learning", "adding"):
    setattr(RaceApp, _name, property(lambda self, n=_name: self._read(n),
                                     lambda self, v, n=_name: self.__dict__.__setitem__(n, v)))


def race(attr: str, victim, intruder) -> None:
    """在 VICTIM 线程里跑 victim；它第一次读 attr 时，intruder 插进来。"""
    app._armed = (attr, intruder)
    t = threading.Thread(target=victim, name=VICTIM, daemon=True)
    t.start()
    t.join(10)
    for i in injected:
        i.join(10)
    alive = t.is_alive() or any(i.is_alive() for i in injected)
    injected.clear()
    check(f"  插队真的发生在读 {attr} 的那一刻", app._armed, None)
    check("  两个线程都跑完了（没有卡死）", alive, False)


def live() -> bool:
    lis = app.listener
    return lis is not None and lis.started and not lis.stopped


def reset() -> None:
    """回到「没游戏、没在学键 / 添加、没监听」。"""
    app.learning = app.adding = False
    app.games = {}
    with app._listener_lock:
        if app.listener is not None:
            app.listener.stop()
            app.listener = None


print("== setup")
cfg_path = RUN / "config.json"
cfg_path.write_text(json.dumps({
    "games": {"FakeGame.exe": "假游戏"}, "launchers": ["fakehyp.exe"],
    "hotkey": {"type": "key", "vk": 0x87}, "exit_grace_sec": 10, "wait_no_launcher_sec": 60,
    "toast": True, "sound": False, "copy_to_clipboard": False, "dualsense_quad": False,
    "save_dir": str(RUN / "shots"),
}, ensure_ascii=False, indent=2), encoding="utf-8")
main.InputListener = FakeListener
main.LEARN_TIMEOUT_SEC = 60   # 计时器不自己到点，超时由测试直接调用
main.ADD_TIMEOUT_SEC = 60
app = RaceApp(Config(cfg_path))
app.toast = StubToast()
app.icon = StubIcon()
app.worker.post = lambda *msg: None
quits: list[int] = []
app._quit = lambda icon, item: quits.append(1)

print("== 不插队：没游戏时学键挂上监听，结束后摘掉；有游戏时结束不摘")
app.start_learning()
check("学键时监听挂着", (live(), app.listener.learning), (True, True))
app._learn_timeout()
check("超时后 learning 复位、监听摘掉", (app.learning, app.listener), (False, None))
app._on_games_changed(dict(GAME))
lis = app.listener
app.start_learning()
check("有游戏时学键用的是同一个监听", app.listener is lis, True)
app._learn_timeout()
check("有游戏时学键结束，监听不摘", (app.learning, live()), (False, True))
reset()

print("== A. 游戏全部退出的同时点「更换截图键…」")
app._on_games_changed(dict(GAME))
race("learning", lambda: app._on_games_changed({}), app.start_learning)
check("learning 已开始", app.learning, True)
check("监听挂着，而且在学键", (live(), app.listener is not None and app.listener.learning), (True, True))
app._learn_timeout()
check("10 秒超时后 learning 复位", app.learning, False)
check("没游戏：超时后监听摘掉", app.listener, None)
app._seen_game = True
app._idle_since = time.monotonic() - 1000
app.on_poll({}, False)
check("之后能自动退出", quits, [1])
quits.clear()
reset()

print("== B. 游戏全部退出的同时点「添加游戏…」")
app._on_games_changed(dict(GAME))
race("adding", lambda: app._on_games_changed({}), app.start_adding)
check("adding 已开始", app.adding, True)
check("等按键期间监听挂着", live(), True)
app._finish_adding(0, 0, True)
check("超时后 adding 复位、监听摘掉", (app.adding, app.listener), (False, None))
reset()

print("== C. 取消更换截图键的同时检测到游戏")
app.start_learning()
race("games", lambda: app._finish_learning(None), lambda: app._on_games_changed(dict(GAME)))
check("learning 已结束", app.learning, False)
check("游戏在运行", app.games, GAME)
check("C 这局游戏的监听挂着", live(), True)
reset()

print("== D. 添加游戏超时的同时检测到游戏")
app.start_adding()
race("games", lambda: app._finish_adding(0, 0, True), lambda: app._on_games_changed(dict(GAME)))
check("adding 已结束", app.adding, False)
check("游戏在运行", app.games, GAME)
check("D 这局游戏的监听挂着", live(), True)
reset()

print(f"\n（共建了 {len(FakeListener.made)} 个 FakeListener）")
print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
