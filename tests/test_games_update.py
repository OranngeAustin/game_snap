"""「添加游戏」和「移除游戏」同时改游戏名单，两边的改动都要留下（02-findings L17）。

两处以前都是「读 cfg["games"] → 算出新 dict → cfg.set」，读和写之间不加锁：一边刚读完旧名单，另一边改完写回，
先读的那边再写回时就把对方的改动盖掉了。这里把 config 的 data 换成在写 games 的那一刻让另一个线程插进来的 dict，
重放两种先后顺序，检查最后的名单（内存和 config.json）同时有新加的游戏、没有被移除的游戏。
用测试配置建真的 main.App，toast、托盘图标、截图线程、按键监听换成桩，确认框自动答「是」。纯 Python，Windows 和 Linux
（tests/winstubs.py 桩）都能跑。只在 <run dir> 里读写。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_games_update.py <run dir>
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


injected: list[threading.Thread] = []


class HookDict(dict):
    """线程 A 写 games 的那一刻，先让线程 B 去做它的事（B 在锁上等着的话，0.5 秒后放 A 先写）。"""
    armed = None

    def __setitem__(self, key, value) -> None:
        armed = HookDict.armed
        if key == "games" and armed and threading.current_thread().name == "A":
            HookDict.armed = None
            t = threading.Thread(target=armed, name="B", daemon=True)
            t.start()
            t.join(0.5)
            injected.append(t)
        super().__setitem__(key, value)


START = {"FakeGame.exe": "假游戏", "Other.exe": "别的游戏"}
WANT = {"FakeGame.exe": "假游戏", "NewGame.exe": "新游戏"}
cfg_path = RUN / "config.json"
main.InputListener = FakeListener
main.ADD_TIMEOUT_SEC = 60
main.process_name = lambda pid: "NewGame.exe"
main.default_game_name = lambda hwnd, exe: "新游戏"
main.confirm = lambda text: True


def run(a, b, label: str) -> None:
    cfg_path.write_text(json.dumps({"games": START, "toast": True, "sound": False, "copy_to_clipboard": False,
                                    "dualsense_quad": False, "save_dir": str(RUN / "shots")},
                                   ensure_ascii=False), encoding="utf-8")
    cfg = Config(cfg_path)
    cfg.data = HookDict(cfg.data)
    app = main.App(cfg)
    app.toast = types.SimpleNamespace(show=lambda *x, **k: None)
    app.icon = types.SimpleNamespace(icon=None, title="", update_menu=lambda: None)
    app.worker.post = lambda *msg: None
    app.start_adding()
    add = lambda: app._finish_adding(0, 4321)                    # noqa: E731
    remove = lambda: app._remove_game("Other.exe")(None, None)   # noqa: E731
    HookDict.armed = {"add": add, "remove": remove}[b]
    t = threading.Thread(target={"add": add, "remove": remove}[a], name="A")
    t.start()
    t.join(5)
    for i in injected:
        i.join(5)
    injected.clear()
    check(f"{label}：插队真的发生了", HookDict.armed, None)
    check(f"{label}：内存里两边的改动都在", dict(cfg["games"]), WANT)
    check(f"{label}：config.json 里两边的改动都在",
          json.loads(cfg_path.read_text(encoding="utf-8"))["games"], WANT)


run("add", "remove", "添加时插进来移除")
run("remove", "add", "移除时插进来添加")

print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
