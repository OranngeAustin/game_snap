"""Tests for the bigger blocklist (not_games.py) and the tray submenu 「游戏名单」 (removing games).
Builds a real main.App on a test config in <run dir> (APPDATA too), with the toast, tray icon, capture
worker and key listener stubbed like test_add_game.py, and main.confirm replaced (no dialog is shown).
process_name and window_title are stubbed for the blocklist part, so nothing has to run; the removal
part uses a renamed ping.exe (FakeGame.exe) to check that the process scanner stops tracking a removed
game. The native part builds the real Win32 menu with pystray's own code (no tray icon is shown) and
clicks items through the callbacks pystray made for them, as its WM_NOTIFY handler does.
Exit code 1 if anything failed.

usage: python -X utf8 tests\\test_blocklist_remove.py <run dir>
"""
import ctypes
import ctypes.wintypes as wt
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

PROJECT, RUN = Path(__file__).resolve().parent.parent, Path(sys.argv[1])
RUN.mkdir(parents=True, exist_ok=False)
os.environ["APPDATA"] = str(RUN / "appdata")   # config.APP_DIR is read at import: keep it in the run folder
sys.path.insert(0, str(PROJECT))
import pystray  # noqa: E402
import main  # noqa: E402
import watcher  # noqa: E402
from config import Config  # noqa: E402

failures: list[str] = []
logs: list[str] = []
CREATE_NO_WINDOW = 0x08000000
PING = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "PING.EXE"
SEP = "(separator)"


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

    def __init__(self) -> None:
        self.updates = 0

    def update_menu(self) -> None:
        self.updates += 1


class FakeListener:
    def __init__(self, binding, should_capture, on_shot, on_foreground, on_learned) -> None:
        self.stopped = False

    def start(self) -> None:
        pass

    def wait_ready(self, timeout: float = 2) -> bool:
        return True

    def stop(self) -> None:
        self.stopped = True

    def start_learning(self) -> None:
        pass


print("== setup")
shutil.copy2(PING, RUN / "FakeGame.exe")
game = subprocess.Popen([str(RUN / "FakeGame.exe"), "-n", "120", "127.0.0.1"], stdout=subprocess.DEVNULL,
                        creationflags=CREATE_NO_WINDOW)
cfg_path = RUN / "config.json"
cfg_path.write_text(json.dumps({
    "games": {"FakeGame.exe": "假游戏", "Ratchet.exe": "Ratchet & Clank", "Other.exe": "别的游戏"},
    "launchers": ["fakehyp.exe"], "hotkey": {"type": "key", "vk": 0xC0}, "exit_grace_sec": 10,
    "wait_no_launcher_sec": 60, "toast": True, "sound": False, "copy_to_clipboard": False,
    "dualsense_quad": False, "save_dir": str(RUN / "shots"),
}, ensure_ascii=False, indent=2), encoding="utf-8")
cfg = Config(cfg_path)
main.InputListener = FakeListener
app = main.App(cfg)
real_icon = app.icon   # the pystray Icon App made with its real menu; never run, so no tray icon appears
toast = app.toast = StubToast()
app.icon = StubIcon()
app.worker.post = lambda *msg: None
asked: list[str] = []
answer = [False]
main.confirm = lambda text: asked.append(text) or answer[0]

print("== blocklist (process_name stubbed)")
fake_names: dict[int, str] = {}
main.process_name = fake_names.get
main.window_title = lambda hwnd: ""


def press(pid: int) -> tuple[str, bool, int | None]:
    """What the listener does when the screenshot key goes down while adding."""
    n = len(toast.calls)
    app._on_key(0, 0, pid)
    if not toast.wait_for(n + 1):
        return ("(no toast)", None, None)
    return toast.calls[n]


BLOCKED = [
    # 常见软件，包括这次误加的 Claude
    "Claude.exe", "chrome.exe", "msedge.exe", "WeChat.exe", "Weixin.exe", "QQ.exe", "Code.exe",
    "WindowsTerminal.exe", "WINWORD.EXE", "explorer.exe", "steamwebhelper.exe", "Discord.exe",
    # 本机软件
    "Photoshop.exe", "NVIDIA Overlay.exe", "TimezoneSwitcher.exe", "pageofficetray.exe", "Zotero.exe",
    "BaiduNetdisk.exe", "HipsMain.exe", "7zFM.exe", "CAJViewer.exe", "JianyingPro.exe", "Blender.exe",
    # 游戏周边
    "launcher.exe", "Map.exe", "wallpaper64.exe", "Paradox Launcher.exe", "KalypsoLauncher.exe",
    "uu_launcher.exe", "Dock_64.exe",
]
ACCEPTED = ["Terraria.exe", "javaw.exe", "python.exe", "dotnet.exe", "Olivia.exe", "WeChatAppEx.exe",
            "yuzu.exe", "Minecraft.exe"]
app.start_adding()
for k, exe in enumerate(BLOCKED):
    fake_names[10000 + k] = exe
    text, ok, _ = press(10000 + k)
    check(f"{exe} rejected", (text, ok, app.adding),
          (f"这不是游戏窗口（{exe}），请在游戏画面里按截图键", False, True))
check("config.json untouched by the rejections",
      list(json.loads(cfg_path.read_text(encoding="utf-8"))["games"]), ["FakeGame.exe", "Ratchet.exe", "Other.exe"])
for k, exe in enumerate(ACCEPTED):
    if k:
        app.start_adding()
    fake_names[20000 + k] = exe
    name = exe.rsplit(".", 1)[0]
    text, ok, _ = press(20000 + k)
    check(f"{exe} added", (text, ok, app.adding), (f"已添加 · {name}（{exe}）", True, False))
on_disk = json.loads(cfg_path.read_text(encoding="utf-8"))["games"]
check("config.json has all of them", list(on_disk)[3:], ACCEPTED)
app._add_timer.cancel()

print("== menu")
top = list(app._menu())
texts = [item.text for item in top]
i = texts.index("添加游戏…")
check("「游戏名单」 right after 「添加游戏…」", texts[i + 1], "游戏名单")
games_item = top[i + 1]
check("「游戏名单」 opens a submenu", games_item.submenu is not None, True)


def submenu() -> list:
    """The submenu as the tray builds it: regenerated, separators cleaned up."""
    return list(list(app._menu())[i + 1].submenu)


def entry(exe: str):
    return next((s for s in submenu() if s is not pystray.Menu.SEPARATOR and s.text.endswith(f"（{exe}）")), None)


want = ["点一项即可移除（会先确认）", SEP, "假游戏（FakeGame.exe）", "Ratchet && Clank（Ratchet.exe）", "别的游戏（Other.exe）",
        *[f"{exe.rsplit('.', 1)[0]}（{exe}）" for exe in ACCEPTED]]
sub = submenu()
check("submenu texts (in config order, & doubled for Windows)",
      [SEP if s is pystray.Menu.SEPARATOR else s.text for s in sub], want)
check("hint line is greyed out", sub[0].enabled, False)
check("game lines are clickable", all(s.enabled for s in sub[2:]), True)

print("== remove: declined")
before = cfg_path.read_text(encoding="utf-8")
n_toast, n_upd = len(toast.calls), app.icon.updates
entry("Other.exe")(real_icon)
check("asked first, naming the game and its exe", "「别的游戏」（Other.exe）" in asked[-1], True)
check("declined: config.json unchanged", cfg_path.read_text(encoding="utf-8"), before)
check("declined: still listed", "Other.exe" in cfg["games"], True)
check("declined: no toast", len(toast.calls), n_toast)

print("== remove: confirmed")
answer[0] = True
old_games = cfg["games"]
item_other = entry("Other.exe")
item_other(real_icon)
on_disk = json.loads(cfg_path.read_text(encoding="utf-8"))["games"]
check("gone from config", "Other.exe" in cfg["games"], False)
check("gone from config.json", "Other.exe" in on_disk, False)
check("the rest kept, in order", list(on_disk), ["FakeGame.exe", "Ratchet.exe", *ACCEPTED])
check("old dict not changed in place (the watcher thread may be reading it)", "Other.exe" in old_games, True)
check("toast", toast.calls[-1][:2], ("已移除 · 别的游戏（Other.exe）", True))
check("log line", any("移除游戏：Other.exe（别的游戏）" in s for s in logs), True)
check("tray refreshed", app.icon.updates > n_upd, True)
check("submenu no longer lists it", entry("Other.exe"), None)
n_ask, n_toast = len(asked), len(toast.calls)
item_other(real_icon)
check("stale item (menu built before the removal): nothing asked, nothing shown",
      (len(asked), len(toast.calls)), (n_ask, n_toast))

print("== remove: a name with &")
entry("Ratchet.exe")(real_icon)
check("dialog shows a single &", "「Ratchet & Clank」（Ratchet.exe）" in asked[-1], True)
check("toast shows a single &", toast.calls[-1][0], "已移除 · Ratchet & Clank（Ratchet.exe）")

print("== remove: a game that is running")
scanner = watcher.ProcessScanner()
running, _ = scanner.scan(cfg.games_lower(), cfg.launchers_lower())
check("before: the scanner tracks FakeGame", running.get(game.pid), "假游戏")
entry("FakeGame.exe")(real_icon)
running, _ = scanner.scan(cfg.games_lower(), cfg.launchers_lower())
check("after: the same scanner no longer tracks it", game.pid in running, False)
check("FakeGame itself still running", game.poll(), None)

print("== remove everything")
for exe in ACCEPTED:
    entry(exe)(real_icon)
check("config.json games empty", json.loads(cfg_path.read_text(encoding="utf-8"))["games"], {})
sub = submenu()
check("empty list: one greyed-out line", [(s.text, s.enabled) for s in sub], [("名单是空的，用「添加游戏…」添加", False)])

print("== native Win32 menu (pystray's own code)")
cfg.set("games", {"FakeGame.exe": "假游戏", "Ratchet.exe": "Ratchet & Clank"})
user32 = ctypes.windll.user32
user32.GetMenuItemCount.argtypes = [wt.HMENU]
user32.GetSubMenu.argtypes = [wt.HMENU, ctypes.c_int]
user32.GetSubMenu.restype = wt.HMENU
user32.GetMenuStringW.argtypes = [wt.HMENU, wt.UINT, wt.LPWSTR, ctypes.c_int, wt.UINT]
user32.GetMenuItemID.argtypes = [wt.HMENU, ctypes.c_int]
user32.GetMenuItemID.restype = wt.UINT
user32.GetMenuState.argtypes = [wt.HMENU, wt.UINT, wt.UINT]
user32.GetMenuState.restype = wt.UINT
user32.DestroyMenu.argtypes = [wt.HMENU]
MF_BYPOSITION, MF_GRAYED_OR_DISABLED = 0x400, 0x3


def menu_strings(h) -> list[str]:
    out = []
    for k in range(user32.GetMenuItemCount(h)):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetMenuStringW(h, k, buf, 256, MF_BYPOSITION)
        out.append(buf.value)
    return out


def native() -> tuple[int, int, list]:
    callbacks: list = []
    hmenu = real_icon._create_menu(real_icon.menu, callbacks)
    k = menu_strings(hmenu).index("游戏名单")
    return hmenu, user32.GetSubMenu(hmenu, k), callbacks


hmenu, hsub, callbacks = native()
strings = menu_strings(hmenu)
k = strings.index("游戏名单")
check("native: 「游戏名单」 after 「添加游戏…」", strings[k - 1], "添加游戏…")
check("native: it is a popup", bool(hsub), True)
check("native: submenu strings (&& shows as one &)", menu_strings(hsub),
      ["点一项即可移除（会先确认）", "", "假游戏（FakeGame.exe）", "Ratchet && Clank（Ratchet.exe）"])
check("native: hint greyed out", bool(user32.GetMenuState(hsub, 0, MF_BYPOSITION) & MF_GRAYED_OR_DISABLED), True)
check("native: game line enabled", user32.GetMenuState(hsub, 3, MF_BYPOSITION) & MF_GRAYED_OR_DISABLED, 0)
item_id = user32.GetMenuItemID(hsub, 3)
asked.clear()
callbacks[item_id - 1](real_icon)   # what Icon._on_notify does with the id TrackPopupMenuEx returns
check("native click: asked about the right game", bool(asked) and "「Ratchet & Clank」（Ratchet.exe）" in asked[-1], True)
check("native click: removed", list(json.loads(cfg_path.read_text(encoding="utf-8"))["games"]), ["FakeGame.exe"])
user32.DestroyMenu(hmenu)
hmenu, hsub, callbacks = native()
check("native: rebuilt submenu", menu_strings(hsub), ["点一项即可移除（会先确认）", "", "假游戏（FakeGame.exe）"])
user32.DestroyMenu(hmenu)
cfg.set("games", {})
hmenu, hsub, callbacks = native()
check("native: empty list", menu_strings(hsub), ["名单是空的，用「添加游戏…」添加"])
check("native: empty-list line greyed out",
      bool(user32.GetMenuState(hsub, 0, MF_BYPOSITION) & MF_GRAYED_OR_DISABLED), True)
user32.DestroyMenu(hmenu)

game.kill()
game.wait()
print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
