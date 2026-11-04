"""学键 / 添加游戏结束时，先重置「空闲起点」再清标志（02-findings L16）。

on_poll 在 learning / adding 为 True 时不判断自动退出。_finish_learning / _finish_adding 以前先把标志清掉、下一行才把
_idle_since 设成现在：GameWatcher 恰好在这两行之间轮询，就会用学键 / 添加之前的旧 _idle_since 判断，刚结束就自动退出。
这里把 learning / adding 换成属性，在标志被清掉的那一刻看 _idle_since 已经有多久：必须是刚刚设的。
另外在那一刻真的调一次 on_poll，检查不会自动退出。
用测试配置建真的 main.App，toast、托盘图标、截图线程、按键监听、自动退出都换成桩。纯 Python，Windows 和 Linux
（tests/winstubs.py 桩）都能跑。只在 <run dir> 里读写。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_idle_order.py <run dir>
"""
import json
import os
import sys
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
import main  # noqa: E402
from config import Config  # noqa: E402

failures: list[str] = []


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


seen: list[tuple[str, float]] = []
quits: list[int] = []


class WatchApp(main.App):
    """learning / adding 被清成 False 的那一刻：记下 _idle_since 已经过了多久，并像 GameWatcher 那样轮询一次。"""

    def _flag(self, name: str, value: bool) -> None:
        was = self.__dict__.get(name, False)
        self.__dict__[name] = value
        if was and not value and "_idle_since" in self.__dict__:
            seen.append((name, time.monotonic() - self._idle_since))
            self.on_poll({}, False)


for _name in ("learning", "adding"):
    setattr(WatchApp, _name, property(lambda self, n=_name: self.__dict__.get(n, False),
                                      lambda self, v, n=_name: self._flag(n, v)))

cfg_path = RUN / "config.json"
cfg_path.write_text(json.dumps({"games": {"FakeGame.exe": "假游戏"}, "toast": True, "sound": False,
                                "copy_to_clipboard": False, "dualsense_quad": False, "exit_grace_sec": 10,
                                "wait_no_launcher_sec": 60, "save_dir": str(RUN / "shots")},
                               ensure_ascii=False), encoding="utf-8")
main.InputListener = FakeListener
main.LEARN_TIMEOUT_SEC = 60
main.ADD_TIMEOUT_SEC = 60
app = WatchApp(Config(cfg_path))
app.toast = types.SimpleNamespace(show=lambda *a, **k: None)
app.icon = types.SimpleNamespace(icon=None, title="", update_menu=lambda: None)
app.worker.post = lambda *msg: None
app._quit = lambda icon, item: quits.append(1)

for label, begin, finish in [
    ("更换截图键超时", app.start_learning, app._learn_timeout),
    ("添加游戏超时", app.start_adding, lambda: app._finish_adding(0, 0, True)),
]:
    seen.clear()
    quits.clear()
    begin()
    app._idle_since = time.monotonic() - 1000   # 学键 / 添加之前就已经空闲了很久
    finish()
    check(f"{label}：标志清掉时 _idle_since 是刚设的", [age < 5 for _, age in seen], [True])
    check(f"{label}：那一刻轮询不会自动退出", quits, [])

print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
