"""更换截图键时，按键和 10 秒超时同时到，只能有一个结果（02-findings L2）。

_finish_learning 以前「先查 learning、再置 False」不加锁（_finish_adding 有锁）。按键恰好在超时那一刻到时，学键线程和
超时 Timer 各跑一次：既把新键存进 config.json，又提示「已取消更换截图键」。这里把 learning 换成属性：线程 A 读 learning
的那一刻，让线程 B 把 _finish_learning 先做完（新代码里 B 会在锁上等，0.5 秒后放 A 先走），检查最后只有一个结果。
用测试配置建真的 main.App，toast、托盘图标、截图线程、按键监听换成桩，不发声音。纯 Python，Windows 和 Linux
（tests/winstubs.py 桩）都能跑。只在 <run dir> 里读写。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_learn_race.py <run dir>
"""
import json
import os
import sys
import threading
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
import main  # noqa: E402
from config import Config  # noqa: E402

failures: list[str] = []
NEW_KEY = {"type": "key", "vk": 0x86}


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {got!r}" + ("" if ok else f"  (want {want!r})"))
    if not ok:
        failures.append(label)


class FakeListener:
    def __init__(self, *a, **k) -> None:
        pass

    def start(self) -> None:
        pass

    def wait_ready(self, timeout: float = 2) -> bool:
        return True

    def stop(self) -> None:
        pass

    def start_learning(self) -> None:
        pass

    def cancel_learning(self) -> None:
        pass

    def set_binding(self, binding) -> None:
        pass


injected: list[threading.Thread] = []


class RaceApp(main.App):
    _armed = None

    @property
    def learning(self):
        value = self.__dict__.get("learning", False)
        armed = self._armed
        if armed and threading.current_thread().name == "A":
            self._armed = None
            t = threading.Thread(target=armed, name="B", daemon=True)
            t.start()
            t.join(0.5)
            injected.append(t)
        return value

    @learning.setter
    def learning(self, value) -> None:
        self.__dict__["learning"] = value


cfg_path = RUN / "config.json"
cfg_path.write_text(json.dumps({"games": {"FakeGame.exe": "假游戏"}, "hotkey": {"type": "key", "vk": 0x87},
                                "toast": True, "sound": False, "copy_to_clipboard": False,
                                "dualsense_quad": False, "save_dir": str(RUN / "shots")},
                               ensure_ascii=False), encoding="utf-8")
main.InputListener = FakeListener
main.LEARN_TIMEOUT_SEC = 60
main.winsound.MessageBeep = lambda *a: None
app = RaceApp(Config(cfg_path))
toasts: list[str] = []
app.toast = types.SimpleNamespace(show=lambda text, ok, rect, hold_ms=None: toasts.append(text))
app.icon = types.SimpleNamespace(icon=None, title="", update_menu=lambda: None)
app.worker.post = lambda *msg: None

for a_args, b_args, label in [((NEW_KEY,), (None,), "按键先查、超时插进来"),
                              ((None,), (NEW_KEY,), "超时先查、按键插进来")]:
    app.start_learning()
    toasts.clear()
    app._armed = lambda b=b_args: app._finish_learning(*b)
    a = threading.Thread(target=app._finish_learning, args=a_args, name="A")
    a.start()
    a.join(5)
    for t in injected:
        t.join(5)
    injected.clear()
    outcomes = [t for t in toasts if t.startswith(("截图键已设为", "已取消更换截图键"))]
    check(f"{label}：插队真的发生了", app._armed, None)
    check(f"{label}：只有一个结果", len(outcomes), 1)
    check(f"{label}：学键结束", app.learning, False)
    saved = json.loads(cfg_path.read_text(encoding="utf-8"))["hotkey"]
    check(f"{label}：存下的键和提示一致",
          saved == NEW_KEY if outcomes[-1:] and outcomes[-1].startswith("截图键已设为") else True, True)
    app.cfg.set("hotkey", {"type": "key", "vk": 0x87})

print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
