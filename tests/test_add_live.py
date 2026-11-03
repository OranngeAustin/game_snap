"""Live test of 「添加游戏…」 in the real program (source, through add_live_inner.py): real tray, real
keyboard hook, real process watcher. Toasts go to the log instead of the screen, and the screenshot key
is F24, so nothing typed meanwhile can trigger it. Two runs, each with APPDATA and config in <run dir>:
A. adding times out: GameSnap must not quit while waiting, even past wait_no_launcher_sec; the hook is
   on while waiting and off afterwards; GameSnap then quits wait_no_launcher_sec later.
B. adding a running program: a renamed ping.exe (FakeNewGame.exe) is added through App._on_key (what
   the hook calls on a key press). It must land in config.json, be picked up by the watcher without a
   restart and keep GameSnap running until it closes; GameSnap then quits after exit_grace_sec.
Writes report.txt into <run dir>.

usage: python -X utf8 tests\\test_add_live.py <run dir>
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT, RUN, INNER = HERE.parent, Path(sys.argv[1]), HERE / "add_live_inner.py"
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


def start_gamesnap(folder: Path, delay: float, add_timeout: float, press_pid: int = 0):
    folder.mkdir()
    cfg = folder / "config.json"
    cfg.write_text(json.dumps({
        "games": {"FakeGame.exe": "假游戏"}, "launchers": [], "hotkey": {"type": "key", "vk": VK_F24},
        "poll_interval_sec": 1, "exit_grace_sec": 3, "wait_no_launcher_sec": 4,
        "toast": False, "sound": False, "copy_to_clipboard": False, "dualsense_quad": False,
        "save_dir": str(folder / "shots"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    cmd = [BUILD_PY, "-X", "utf8", str(INNER), str(PROJECT), str(delay), str(add_timeout), str(press_pid),
           "--no-elevate", "--config", str(cfg)]
    err = open(folder / "stderr.txt", "wb")
    gs = subprocess.Popen(cmd, cwd=PROJECT, env=dict(os.environ, APPDATA=str(folder / "appdata")),
                          stdout=subprocess.DEVNULL, stderr=err)
    return gs, cfg, err


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


def finish(folder: Path, gs, err, timeout: float) -> tuple[int | None, list[tuple[float, str]]]:
    try:
        rc = gs.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        gs.kill()
        rc = None
        report.append("    GameSnap did not exit in time; killed")
    err.close()
    log = read_log(folder)
    report.append("  --- gamesnap.log ---")
    report.extend(f"  {t:6.2f}s  {line}" for t, line in log)
    crash = folder / "appdata" / "GameSnap" / "crash.log"
    crash_lines = crash.read_text(encoding="utf-8").splitlines() if crash.exists() else []
    stderr = (folder / "stderr.txt").read_text(encoding="utf-8", errors="replace").strip()
    report.append("  --- stderr ---")
    report.append("  " + (stderr or "(empty)"))
    check("crash.log has only the start line", len(crash_lines) == 1)
    check("stderr empty", not stderr)
    return rc, log


report.append("== A. adding times out (wait_no_launcher_sec=4, add timeout 6 s)")
a = RUN / "A_timeout"
gs, cfg, err = start_gamesnap(a, delay=2, add_timeout=6)
rc, log = finish(a, gs, err, timeout=40)
t_click = when(log, "test: 托盘菜单「添加游戏…」")
t_hook_on = when(log, "按键监听已启动")
t_hint = when(log, "toast: 切到要添加的游戏里，按一下截图键")
t_timeout = when(log, "toast: 没收到截图键，没有添加游戏")
t_hook_off = when(log, "按键监听已停止")
t_quit = when(log, "自动退出：没有检测到游戏或启动器")
check("exited by itself, exit code 0", rc == 0)
check("hook turned on after the click (no game running)",
      None not in (t_click, t_hook_on) and t_hook_on >= t_click)
check("hint shown", t_hint is not None)
check("timed out 5.5-7 s after the click", None not in (t_click, t_timeout) and 5.5 <= t_timeout - t_click <= 7)
check("hook turned off after the timeout", None not in (t_timeout, t_hook_off) and t_hook_off >= t_timeout)
check("did not quit while waiting, although wait_no_launcher_sec had passed",
      None not in (t_quit, t_timeout) and t_quit > t_timeout and t_timeout > 4.5)
check("quit 3.5-6 s after the timeout", None not in (t_quit, t_timeout) and 3.5 <= t_quit - t_timeout <= 6)

report.append("\n== B. adding a running program (FakeNewGame.exe)")
b = RUN / "B_add"
shutil.copy2(PING, RUN / "FakeNewGame.exe")
game = subprocess.Popen([str(RUN / "FakeNewGame.exe"), "-n", "120", "127.0.0.1"], stdout=subprocess.DEVNULL,
                        creationflags=CREATE_NO_WINDOW)
gs, cfg, err = start_gamesnap(b, delay=2, add_timeout=15, press_pid=game.pid)
time.sleep(12)
check("still running 12 s in (only the added game keeps it alive)", gs.poll() is None)
game.kill()
game.wait()
t_closed = time.monotonic()
rc, log = finish(b, gs, err, timeout=30)
gone = time.monotonic() - t_closed
report.append(f"    GameSnap gone {gone:.1f}s after the added game closed")
check("exit code 0", rc == 0)
# exit_grace_sec counts from the last poll that still saw the game, so up to one poll interval less
check("quit 1.8-6.5 s after the added game closed", 1.8 <= gone <= 6.5)
saved = json.loads(cfg.read_text(encoding="utf-8"))["games"]
check("config.json has the new game", saved.get("FakeNewGame.exe") == "FakeNewGame")
check("config.json kept the old entry", saved.get("FakeGame.exe") == "假游戏")
t_press = when(log, f"test: 在 pid {game.pid} 的窗口里按截图键")
t_seen = when(log, f"检测到游戏：FakeNewGame(pid {game.pid})")
check("logged the add", when(log, "添加游戏：FakeNewGame.exe → FakeNewGame") is not None)
check("toast for the add", when(log, "toast: 已添加 · FakeNewGame（FakeNewGame.exe）") is not None)
# the watcher may log the detection before _finish_adding logs the add, so time it from the key press
check("picked up by the watcher within 2.5 s of the key press, without a restart",
      None not in (t_press, t_seen) and 0 <= t_seen - t_press <= 2.5)
check("hook stayed on from adding until the game closed",
      sum("按键监听已启动" in line for _, line in log) == 1 and when(log, "按键监听已停止") is not None)

report.append("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
(RUN / "report.txt").write_text("\n".join(report), encoding="utf-8")
sys.exit(1 if failures else 0)
