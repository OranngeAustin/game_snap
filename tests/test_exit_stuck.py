"""Live test of the exit watchdog (05 doc P7), source through exit_stuck_inner.py: real tray, real message loop.
- lost: the message loop never gets WM_QUIT, as when a tray menu is open at exit. GameSnap must still end by
  itself with exit code 0, about EXIT_WATCHDOG_SEC after 「退出」, and say so in the log;
- normal: nothing lost. It ends right after 「退出」 and the watchdog stays silent.
Nothing runs from the config's game list, so GameSnap quits after wait_no_launcher_sec. Writes report.txt into <run dir>.

usage: python -X utf8 tests\\test_exit_stuck.py <run dir>
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT, RUN, INNER = HERE.parent, Path(sys.argv[1]), HERE / "exit_stuck_inner.py"
BUILD_PY = r"D:\anaconda3\envs\gamesnap-build\python.exe"
VK_F24 = 0x87
WATCHDOG_TEXT = "秒内没有退出"
RUN.mkdir(parents=True, exist_ok=False)
report: list[str] = []
failures: list[str] = []


def check(label: str, ok: bool) -> None:
    report.append(f"    {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        failures.append(label)


def read_log(folder: Path) -> list[tuple[float, str]]:
    path = folder / "appdata" / "GameSnap" / "gamesnap.log"
    out = []
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3}) ", line)
        if m:
            out.append((datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f").timestamp(), line))
    return out


def run(mode: str) -> tuple[int | None, list[tuple[float, str]], list[str], str, float]:
    folder = RUN / mode
    folder.mkdir()
    cfg = folder / "config.json"
    cfg.write_text(json.dumps({
        "games": {"NeverRunsGame.exe": "测试"}, "launchers": ["NeverRunsLauncher.exe"],
        "hotkey": {"type": "key", "vk": VK_F24}, "poll_interval_sec": 1, "exit_grace_sec": 3,
        "wait_no_launcher_sec": 2, "toast": False, "sound": False, "copy_to_clipboard": False,
        "dualsense_quad": False, "save_dir": str(folder / "shots"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    cmd = [BUILD_PY, "-X", "utf8", str(INNER), str(PROJECT), mode, "--no-elevate", "--config", str(cfg)]
    with open(folder / "stderr.txt", "wb") as err:
        gs = subprocess.Popen(cmd, cwd=PROJECT, env=dict(os.environ, APPDATA=str(folder / "appdata")),
                              stdout=subprocess.DEVNULL, stderr=err)
        try:
            rc = gs.wait(timeout=30)
        except subprocess.TimeoutExpired:
            gs.kill()
            gs.wait()
            rc = None
            report.append(f"    {mode}: GameSnap did not exit within 30 s; killed")
    ended = time.time()
    crash = folder / "appdata" / "GameSnap" / "crash.log"
    crash_lines = crash.read_text(encoding="utf-8").splitlines() if crash.exists() else []
    stderr = (folder / "stderr.txt").read_text(encoding="utf-8", errors="replace").strip()
    log = read_log(folder)
    report.append(f"== {mode}: exit code {rc}")
    report.extend(f"  {line}" for _, line in log)
    report.append("  --- stderr ---")
    report.append("  " + (stderr or "(empty)"))
    return rc, log, crash_lines, stderr, ended


def when(log: list[tuple[float, str]], text: str) -> float | None:
    return next((t for t, line in log if text in line), None)


rc, log, crash_lines, stderr, ended = run("lost")
t_auto = when(log, "自动退出：")
t_dog = when(log, WATCHDOG_TEXT)
check("message loop stuck: ended by itself with exit code 0", rc == 0)
check("auto-exit started", t_auto is not None)
check("watchdog said so in the log", t_dog is not None)
check("watchdog fired 2.5-4.5 s after auto-exit", None not in (t_auto, t_dog) and 2.5 <= t_dog - t_auto <= 4.5)
check("process gone within 3 s of the watchdog line", t_dog is not None and ended - t_dog <= 3)
check("crash.log has only the start line", len(crash_lines) == 1)
check("stderr empty", not stderr)

rc, log, crash_lines, stderr, ended = run("normal")
t_auto = when(log, "自动退出：")
check("normal exit: exit code 0", rc == 0)
check("normal exit: auto-exit started", t_auto is not None)
check("normal exit: watchdog stayed silent", when(log, WATCHDOG_TEXT) is None)
check("normal exit: process gone within 2.5 s of auto-exit", t_auto is not None and ended - t_auto <= 2.5)
check("normal exit: crash.log has only the start line", len(crash_lines) == 1)
check("normal exit: stderr empty", not stderr)

report.append("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
(RUN / "report.txt").write_text("\n".join(report), encoding="utf-8")
sys.exit(1 if failures else 0)
