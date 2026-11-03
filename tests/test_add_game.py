"""Tests for the tray item 「添加游戏…」 (main.App.start_adding and friends) and --launch with links.
Builds a real main.App on a test config in <run dir>, with the toast, tray icon, capture worker and key
listener stubbed (no hook is installed and no key is injected; key presses are simulated by calling
App._on_key, and once through the real InputListener._handle_key with foreground() stubbed).
Game windows are hidden windows in child python.exe processes (fake_window.py); the launcher is a renamed
copy of ping.exe (FakeHyp.exe). ShellExecuteW is replaced, so launch() starts nothing.
Covers: the menu item; the hint; should_capture while adding; no auto-quit and no listener stop while
adding; rejections (explorer, launcher, unknown pid); adding with a name from the window title, saved to
config.json and seen by the process scanner; already listed; the real key handler swallowing down+up;
routing shots when not adding; timeout with and without a game running; learning/adding exclusion;
key and timeout racing; default_game_name; process_name; launch() working folder.
Exit code 1 if anything failed.

usage: python -X utf8 tests\\test_add_game.py <run dir>
"""
import ctypes
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT, RUN, FAKE = HERE.parent, Path(sys.argv[1]), HERE / "fake_window.py"
RUN.mkdir(parents=True, exist_ok=False)
os.environ["APPDATA"] = str(RUN / "appdata")   # config.APP_DIR is read at import: keep it in the run folder
sys.path.insert(0, str(PROJECT))
import hotkey  # noqa: E402
import main  # noqa: E402
import watcher  # noqa: E402
from config import Config  # noqa: E402

failures: list[str] = []
logs: list[str] = []
CREATE_NO_WINDOW = 0x08000000


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {got!r}" + ("" if ok else f"  (want {want!r})"))
    if not ok:
        failures.append(label)


class ListHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        logs.append(record.getMessage())


logging.getLogger().addHandler(ListHandler())
logging.getLogger().setLevel(logging.INFO)


class StubToast:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool, int | None]] = []
        self.cond = threading.Condition()

    def show(self, text, ok, rect, hold_ms=None) -> None:
        with self.cond:
            self.calls.append((text, ok, hold_ms))
            self.cond.notify_all()

    def wait_for(self, n: int, timeout: float = 5) -> bool:
        with self.cond:
            return self.cond.wait_for(lambda: len(self.calls) >= n, timeout)


class StubIcon:
    icon = None
    title = ""

    def update_menu(self) -> None:
        pass


class FakeListener:
    made: list["FakeListener"] = []

    def __init__(self, binding, should_capture, on_shot, on_foreground, on_learned) -> None:
        self.started = self.stopped = False
        FakeListener.made.append(self)

    def start(self) -> None:
        self.started = True

    def wait_ready(self, timeout: float = 2) -> bool:
        return True

    def stop(self) -> None:
        self.stopped = True

    def start_learning(self) -> None:
        pass


def fake_window(title: str) -> tuple[subprocess.Popen, int]:
    child = subprocess.Popen([sys.executable, str(FAKE), title, "120"], stdout=subprocess.PIPE,
                             text=True, encoding="utf-8")
    return child, int(child.stdout.readline())


print("== default_game_name (title stubbed)")
NAME_CASES = [
    ("Hollow Knight", "hollow_knight.exe", "Hollow Knight"),
    ("ELDEN RING™", "eldenring.exe", "ELDEN RING™"),
    ("Stardew Valley - v1.6.9 (DX11)", "Stardew Valley.exe", "Stardew Valley"),
    ("Cool Game | Vulkan", "cool.exe", "Cool Game"),
    ("Some Game (64-bit, DX11)", "some.exe", "Some Game"),
    ("Half-Life 2", "hl2.exe", "Half-Life 2"),
    ("原神", "YuanShen.exe", "原神"),
    ("", "HollowKnight.exe", "HollowKnight"),
    ("   ", "Blank.exe", "Blank"),
    ("A" * 41, "LongTitle.exe", "LongTitle"),
    ("", "x.y.exe", "x.y"),
]
real_window_title = main.window_title
for title, exe, want in NAME_CASES:
    main.window_title = lambda hwnd, t=title: t
    check(f"default_game_name({title!r}, {exe!r})", main.default_game_name(1, exe), want)
main.window_title = real_window_title

print("== setup")
shutil.copy2(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "PING.EXE", RUN / "FakeHyp.exe")
hyp = subprocess.Popen([str(RUN / "FakeHyp.exe"), "-n", "120", "127.0.0.1"], stdout=subprocess.DEVNULL,
                       creationflags=CREATE_NO_WINDOW)
hk, hk_hwnd = fake_window("Hollow Knight")
check("child window created", bool(hk_hwnd), True)
cfg_path = RUN / "config.json"
cfg_path.write_text(json.dumps({
    "games": {"FakeGame.exe": "假游戏"}, "launchers": ["fakehyp.exe"],
    "hotkey": {"type": "key", "vk": 0xC0}, "exit_grace_sec": 10, "wait_no_launcher_sec": 60,
    "toast": True, "sound": False, "copy_to_clipboard": False, "dualsense_quad": False,
    "save_dir": str(RUN / "shots"),
}, ensure_ascii=False, indent=2), encoding="utf-8")
cfg = Config(cfg_path)
main.InputListener = FakeListener
app = main.App(cfg)
toast = app.toast = StubToast()
app.icon = StubIcon()
posts: list[tuple] = []
app.worker.post = lambda *msg: posts.append(msg)
quits: list[int] = []
app._quit = lambda icon, item: quits.append(1)
time.sleep(0.5)   # let the children show up in a fresh process snapshot

print("== process_name")
check("process_name keeps the case", watcher.process_name(hyp.pid), "FakeHyp.exe")
check("snapshot_names lowercases", watcher.snapshot_names()[hyp.pid], "fakehyp.exe")
check("process_name of a pid that does not exist", watcher.process_name(0xFFFFFFF0), None)
check("process_name of the game window's process", watcher.process_name(hk.pid), "python.exe")

print("== menu")
texts = [item.text for item in app._menu().items]
i = texts.index("更换截图键…")
check("「添加游戏…」 right after 「更换截图键…」", texts[i + 1], "添加游戏…")

print("== start adding")
n = len(toast.calls)
app.start_adding()
check("adding on", app.adding, True)
check("listener started for it (no game running)", FakeListener.made[-1].started, True)
text, ok, hold = toast.calls[n]
check("hint text", text, f"切到要添加的游戏里，按一下截图键 {hotkey.key_name(cfg['hotkey'])}")
check("hint is green", ok, True)
check("hint stays up for the whole wait (14-15 s)", 14000 <= hold <= 15000, True)
check("should_capture: any other program", app.should_capture(hk.pid), True)
check("should_capture: pid 0", app.should_capture(0), False)
check("should_capture: GameSnap itself", app.should_capture(os.getpid()), False)
app.paused = True
check("should_capture ignores pause while adding", app.should_capture(hk.pid), True)
app.paused = False

app._seen_game = True
app._idle_since = time.monotonic() - 1000
app.on_poll({}, False)
check("no auto-quit while adding", quits, [])
app.games = {hk.pid: "x"}
app._on_games_changed({})
check("games gone while adding: listener kept", FakeListener.made[-1].stopped, False)
app.start_learning()
check("start_learning ignored while adding", app.learning, False)


def press(hwnd: int, pid: int) -> tuple[str, bool, int | None]:
    """What the listener does when the screenshot key goes down and should_capture said yes."""
    n = len(toast.calls)
    app._on_key(0, hwnd, pid)
    if not toast.wait_for(n + 1):
        return ("(no toast)", None, None)
    return toast.calls[n]


print("== rejections")
explorer = next((p for p, name in watcher.snapshot_names().items() if name == "explorer.exe"), None)
if explorer:
    text, ok, hold = press(0, explorer)
    check("explorer rejected", (ok, "explorer.exe" in text, app.adding), (False, True, True))
    check("rejection hint lasts until the deadline", 1000 <= hold < 15000, True)
else:
    print("SKIP  no explorer.exe running")
text, ok, _ = press(0, hyp.pid)
check("launcher rejected", (ok, "FakeHyp.exe" in text, app.adding), (False, True, True))
text, ok, _ = press(0, 0xFFFFFFF0)
check("unknown process rejected", (ok, "未知程序" in text, app.adding), (False, True, True))

print("== add")
text, ok, hold = press(hk_hwnd, hk.pid)
check("added toast", (text, ok), ("已添加 · Hollow Knight（python.exe）", True))
check("adding off", app.adding, False)
check("timeout timer cancelled", app._add_timer.finished.is_set(), True)
on_disk = json.loads(cfg_path.read_text(encoding="utf-8"))["games"]
check("saved to config.json under the exe's own case", on_disk.get("python.exe"), "Hollow Knight")
check("existing entries kept", on_disk.get("FakeGame.exe"), "假游戏")
check("log line", any("添加游戏：python.exe → Hollow Knight" in s for s in logs), True)
games, _ = watcher.ProcessScanner().scan(cfg.games_lower(), cfg.launchers_lower())
check("the process scanner now sees the game", games.get(hk.pid), "Hollow Knight")
check("listener left running for the new game", FakeListener.made[-1].stopped, False)
app.on_poll({}, False)
check("countdown restarted after adding: no quit yet", quits, [])
app._idle_since = time.monotonic() - 1000
app.on_poll({}, False)
check("auto-quit works again once adding is over", quits, [1])

print("== already listed")
app.start_adding()
text, ok, _ = press(hk_hwnd, hk.pid)
check("already-listed toast", (text, ok), ("已经在名单里了 · Hollow Knight", True))
check("config.json unchanged", json.loads(cfg_path.read_text(encoding="utf-8"))["games"], on_disk)

print("== the real key handler")
lis = hotkey.InputListener(cfg["hotkey"], app.should_capture, app._on_key, lambda h, p: None, lambda b: None)
hotkey.foreground = lambda: (hk_hwnd, hk.pid)
VK = cfg["hotkey"]["vk"]
app.start_adding()
n = len(toast.calls)
down = lis._handle_key(VK, hotkey.WM_KEYDOWN, 0)
toast.wait_for(n + 1)
up = lis._handle_key(VK, hotkey.WM_KEYUP, 0)
check("key swallowed while adding (down, up)", (down, up), (True, True))
check("the press was used for adding", toast.calls[n][0], "已经在名单里了 · Hollow Knight")
app.games = {}
down = lis._handle_key(VK, hotkey.WM_KEYDOWN, 0)
up = lis._handle_key(VK, hotkey.WM_KEYUP, 0)
check("not adding, not a running game: key passes through (down, up)", (down, up), (False, False))

print("== shots when not adding")
posts.clear()
app.games = {hk.pid: "Hollow Knight"}
app._on_key(123, hk_hwnd, hk.pid)
app._on_key(456, 0, 4242)
check("only the game's key press goes to the capture worker", posts, [("shot", 123, hk_hwnd, hk.pid)])

print("== timeout")
main.ADD_TIMEOUT_SEC = 1
app.games = {}
app.start_adding()
lis_obj = app.listener
time.sleep(1.6)
check("timed out", app.adding, False)
check("timeout toast", toast.calls[-1][:2], ("没收到截图键，没有添加游戏", False))
check("no game running: listener stopped", (lis_obj.stopped, app.listener), (True, None))
app.games = {hk.pid: "Hollow Knight"}
app.start_adding()
time.sleep(1.6)
check("game running: listener kept after timeout",
      (app.adding, app.listener is not None and not app.listener.stopped), (False, True))
app.games = {}
app.learning = True
app.start_adding()
check("start_adding ignored while learning", app.adding, False)
app.learning = False

print("== key and timeout at the same moment")
main.ADD_TIMEOUT_SEC = 60
outcomes = []
for _ in range(30):
    app.start_adding()
    n = len(toast.calls)
    barrier = threading.Barrier(2)

    def go(*args) -> None:
        barrier.wait()
        app._finish_adding(*args)

    pair = [threading.Thread(target=go, args=(hk_hwnd, hk.pid)), threading.Thread(target=go, args=(0, 0, True))]
    for t in pair:
        t.start()
    for t in pair:
        t.join()
    outcomes.append(sum(c[0].startswith(("已经在名单里了", "没收到截图键")) for c in toast.calls[n:]))
check("exactly one outcome per round (30 rounds)", set(outcomes), {1})
check("nothing left waiting", app.adding, False)

print("== launch")
shell32 = ctypes.windll.shell32
real_shell_execute = shell32.ShellExecuteW
calls: list[tuple] = []
boxes: list[str] = []
main.message_box = boxes.append
shell32.ShellExecuteW = lambda *a: calls.append(a) or 42
ping = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "PING.EXE"
main.launch(str(ping), "")
main.launch("steam://rungameid/1145360", "")
APPS = r"shell:AppsFolder\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"
main.launch("explorer.exe", APPS)
check("program: started in its own folder", calls[0][4], str(ping.parent))
check("program: no arguments -> None", calls[0][3], None)
check("steam link: passed as is, no working folder", (calls[1][2], calls[1][4]), ("steam://rungameid/1145360", None))
check("explorer + AppsFolder: arguments passed, no working folder", (calls[2][3], calls[2][4]), (APPS, None))
check("no error box when it starts", boxes, [])
shell32.ShellExecuteW = lambda *a: 2
main.launch("steam://rungameid/1", "")
check("error box when it fails", len(boxes), 1)
shell32.ShellExecuteW = real_shell_execute

for child in (hk, hyp):
    child.kill()
    child.wait()
print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
