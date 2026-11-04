"""App.refresh_tray 被多个线程同时调用（02-findings M6）。

refresh_tray 会被 GameWatcher、Saver、Timer、学键 / 添加线程、托盘线程调用，pystray 的 win32 后端换图标（DestroyIcon /
LoadImage / Shell_NotifyIcon）、重建菜单（DestroyMenu）都在调用线程里直接做，不加锁。用测试配置建真的 main.App，
托盘图标换成记录调用的 StubIcon，make_icon 换成直接返回状态名，检查：
1. 8 个线程同时刷新：图标的设置不会交叠（交叠就是两个线程同时在换 HICON）；
2. 线程 A 算出「工作中」、正在换图标时，游戏退出、线程 B 刷新成「等待」：最后显示的必须是「等待」，不能被 A 用旧状态盖掉；
3. 状态没变时不重设图标（省掉每张截图一次的 PIL 绘制和写临时 ICO）；菜单照样每次刷新，提示文字跟着变。
不挂钩子、不建托盘图标。纯 Python，Windows 和 Linux（tests/winstubs.py 桩）都能跑。只在 <run dir> 里读写。
Exit code 1 if anything failed.

usage: python -X utf8 tests/test_tray_refresh.py <run dir>
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


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {got!r}" + ("" if ok else f"  (want {want!r})"))
    if not ok:
        failures.append(label)


class StubIcon:
    """记下每次设置图标（设置时停一会儿，模拟 DestroyIcon / LoadImage / Shell_NotifyIcon 的耗时）。"""

    def __init__(self) -> None:
        self._icon = None
        self.title = ""
        self.sets: list[str] = []
        self.menu_updates = 0
        self.inside = 0
        self.max_inside = 0
        self.hold = 0.0
        self.entered = threading.Event()
        self.release: threading.Event | None = None   # 设了的话，下一次设置图标先等它（最多 0.5 秒）
        self._count_lock = threading.Lock()

    @property
    def icon(self):
        return self._icon

    @icon.setter
    def icon(self, value) -> None:
        with self._count_lock:
            self.inside += 1
            self.max_inside = max(self.max_inside, self.inside)
        release, self.release = self.release, None
        self.entered.set()
        if release is not None:
            release.wait(0.5)
        time.sleep(self.hold)
        self._icon = value
        self.sets.append(value)
        with self._count_lock:
            self.inside -= 1

    def update_menu(self) -> None:
        self.menu_updates += 1


print("== setup")
cfg_path = RUN / "config.json"
cfg_path.write_text(json.dumps({
    "games": {"FakeGame.exe": "假游戏"}, "launchers": ["fakehyp.exe"],
    "hotkey": {"type": "key", "vk": 0x87}, "toast": False, "sound": False, "copy_to_clipboard": False,
    "dualsense_quad": False, "save_dir": str(RUN / "shots"),
}, ensure_ascii=False, indent=2), encoding="utf-8")
app = main.App(Config(cfg_path))
main.make_icon = lambda state: state   # 图标就是状态名，方便看最后显示的是哪个（建好 App 再换）
icon = app.icon = StubIcon()

print("== 1. 8 个线程同时刷新")
icon.hold = 0.05
for round_ in range(3):
    app.games = {} if round_ % 2 else {4242: "假游戏"}
    barrier = threading.Barrier(8)

    def go() -> None:
        barrier.wait()
        app.refresh_tray()

    threads = [threading.Thread(target=go) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
check("同一时刻最多一个线程在换图标", icon.max_inside, 1)
check("最后显示的是最后的状态", icon.icon, "active")
icon.hold = 0.0

print("== 2. A 用旧状态覆盖 B 的新状态")
app.games = {4242: "假游戏"}
app.refresh_tray()
app.games = {}
app.refresh_tray()   # 先回到「等待」，下面 A 才一定会去换图标
icon.entered.clear()
release = icon.release = threading.Event()
app.games = {4242: "假游戏"}
a = threading.Thread(target=app.refresh_tray, name="A")
a.start()
check("A 正在换成「工作中」", icon.entered.wait(5), True)


def b_job() -> None:
    app.games = {}   # 游戏刚好退出
    app.refresh_tray()


b = threading.Thread(target=b_job, name="B")
b.start()
b.join(0.2)        # 旧代码里 B 立刻做完；新代码里 B 在锁上等 A
release.set()
a.join(5)
b.join(5)
check("两个线程都做完了", (a.is_alive(), b.is_alive()), (False, False))
check("最后显示的是「等待」（游戏已退出）", icon.icon, "idle")

print("== 3. 状态没变不重设图标，菜单照样刷新")
app.games = {4242: "假游戏"}
app.refresh_tray()
n_sets, n_menu = len(icon.sets), icon.menu_updates
app.shot_count += 1   # 截了一张：提示文字变了，图标状态没变
app.refresh_tray()
app.refresh_tray()
check("图标没重设", len(icon.sets) - n_sets, 0)
check("菜单每次都刷新", icon.menu_updates - n_menu, 2)
check("提示文字更新了", "本次已截 1 张" in icon.title, True)
app.paused = True
app.refresh_tray()
check("状态变了就换图标", icon.sets[-1], "paused")
app.paused = False
app.refresh_tray()
check("再变回来", icon.sets[-1], "active")

print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
