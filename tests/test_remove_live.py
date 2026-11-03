"""Live test of removing a running game in the tray submenu 「游戏名单」 (source, through
remove_live_inner.py): real tray, real keyboard hook, real process watcher; toasts go to the log and the
screenshot key is F24. A renamed ping.exe (FakeGame.exe) is the running game. Expected: the watcher picks
it up; clicking it in 「游戏名单」 asks, then updates config.json, logs and toasts; the watcher drops it
without a restart, the hook goes off, and GameSnap quits exit_grace_sec later although FakeGame.exe is
still running. Writes report.txt into <run dir>.

usage: python -X utf8 tests\\test_remove_live.py <run dir>
"""
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT, RUN, INNER = HERE.parent, Path(sys.argv[1]), HERE / "remove_live_inner.py"
BUILD_PY = r"D:\anaconda3\envs\gamesnap-build\python.exe"
PING = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "PING.EXE"
CREATE_NO_WINDOW = 0x08000000
VK_F24 = 0x87
RUN.mkdir(parents=True, exist_ok=False)
report: list[str] = []
failures: list[str] = []


def check(label: str, ok: bool) -> None:
    report.append(f"    {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        failures.append(label)


def read_log(folder: Path) -> list[tuple[float, str]]:
    """gamesnap.log as (seconds since its first line, line)."""
    path = folder / "appdata" / "GameSnap" / "gamesnap.log"
    out, t0 = [], None
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3}) ", line)
        if m:
            t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f").timestamp()
            t0 = t if t0 is None else t0
            out.append((t - t0, line))
    return out


def when(log: list[tuple[float, str]], text: str) -> float | None:
    return next((t for t, line in log if text in line), None)


def ordered(*times) -> bool:
    return None not in times and list(times) == sorted(times)


shutil.copy2(PING, RUN / "FakeGame.exe")
game = subprocess.Popen([str(RUN / "FakeGame.exe"), "-n", "120", "127.0.0.1"], stdout=subprocess.DEVNULL,
                        creationflags=CREATE_NO_WINDOW)
folder = RUN / "remove"
folder.mkdir()
cfg = folder / "config.json"
cfg.write_text(json.dumps({
    "games": {"FakeGame.exe": "假游戏", "Other.exe": "别的游戏"}, "launchers": [],
    "hotkey": {"type": "key", "vk": VK_F24}, "poll_interval_sec": 1, "exit_grace_sec": 3, "wait_no_launcher_sec": 4,
    "toast": False, "sound": False, "copy_to_clipboard": False, "dualsense_quad": False,
    "save_dir": str(folder / "shots"),
}, ensure_ascii=False, indent=2), encoding="utf-8")
cmd = [BUILD_PY, "-X", "utf8", str(INNER), str(PROJECT), "4", "FakeGame.exe", "--no-elevate", "--config", str(cfg)]
err = open(folder / "stderr.txt", "wb")
gs = subprocess.Popen(cmd, cwd=PROJECT, env=dict(os.environ, APPDATA=str(folder / "appdata")),
                      stdout=subprocess.DEVNULL, stderr=err)
try:
    rc = gs.wait(timeout=40)
except subprocess.TimeoutExpired:
    gs.kill()
    rc = None
    report.append("    GameSnap did not exit in time; killed")
game_alive = game.poll() is None
game.kill()
game.wait()
err.close()

log = read_log(folder)
report.append("== removing a running game in 「游戏名单」")
report.append("  --- gamesnap.log ---")
report.extend(f"  {t:6.2f}s  {line}" for t, line in log)
crash = folder / "appdata" / "GameSnap" / "crash.log"
crash_lines = crash.read_text(encoding="utf-8").splitlines() if crash.exists() else []
stderr = (folder / "stderr.txt").read_text(encoding="utf-8", errors="replace").strip()
report.append("  --- stderr ---")
report.append("  " + (stderr or "(empty)"))

t_seen = when(log, f"检测到游戏：假游戏(pid {game.pid})")
t_hook_on = when(log, "按键监听已启动")
t_menu = when(log, "test: 「游戏名单」子菜单：点一项即可移除（会先确认） |  | 假游戏（FakeGame.exe） | 别的游戏（Other.exe）")
t_click = when(log, "test: 点「假游戏（FakeGame.exe）」")
t_ask = when(log, "test: 确认框「把「假游戏」（FakeGame.exe）从游戏名单里移除？")
t_removed = when(log, "移除游戏：FakeGame.exe（假游戏）")
t_toast = when(log, "toast: 已移除 · 假游戏（FakeGame.exe） | ok=True")
t_gone = when(log, "游戏已全部退出")
t_hook_off = when(log, "按键监听已停止")
t_quit = when(log, "自动退出：游戏和启动器都已退出")
check("exit code 0", rc == 0)
check("crash.log has only the start line", len(crash_lines) == 1)
check("stderr empty", not stderr)
check("watcher picked up FakeGame, then the hook went on", ordered(t_seen, t_hook_on))
check("submenu listed both games", t_menu is not None)
check("click → asked → removed → toast, in that order", ordered(t_seen, t_click, t_ask, t_removed, t_toast))
check("watcher dropped it within 2.5 s, without a restart",
      None not in (t_removed, t_gone) and 0 <= t_gone - t_removed <= 2.5)
check("hook went off after that", ordered(t_gone, t_hook_off))
# exit_grace_sec counts from the last poll that still saw the game, so up to one poll interval less
check("quit 1.8-4.5 s after the game was dropped", None not in (t_gone, t_quit) and 1.8 <= t_quit - t_gone <= 4.5)
check("FakeGame.exe was still running when GameSnap quit", game_alive)
saved = json.loads(cfg.read_text(encoding="utf-8"))["games"]
check("config.json: only the other game left", saved == {"Other.exe": "别的游戏"})

report.append("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
(RUN / "report.txt").write_text("\n".join(report), encoding="utf-8")
sys.exit(1 if failures else 0)
