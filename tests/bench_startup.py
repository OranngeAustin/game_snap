"""Measure how long the built GameSnap.exe takes to start, N times: process start -> first log line
(imports, logging and the single-instance check done; this is where --launch would fire) -> "GameSnap 启动"
(App built, tray about to start). --no-elevate, a test config that exits on its own after ~1 s, APPDATA
inside the run folder, DualSense feature off. Writes report.txt into the run folder. A measurement only:
no pass/fail.

usage: python -X utf8 tests\\bench_startup.py <run dir> [N]
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT, RUN = Path(__file__).resolve().parent.parent, Path(sys.argv[1])
N = int(sys.argv[2]) if len(sys.argv) > 2 else 5
RUN.mkdir(parents=True, exist_ok=False)
cfg = RUN / "config.json"
cfg.write_text(json.dumps({
    "games": {"PING.EXE": "测试游戏"}, "launchers": [], "poll_interval_sec": 1,
    "exit_grace_sec": 1, "wait_no_launcher_sec": 1, "toast": False, "sound": False,
    "copy_to_clipboard": False, "dualsense_quad": False, "save_dir": str(RUN / "shots"),
}, ensure_ascii=False, indent=2), encoding="utf-8")
exe = PROJECT / "dist" / "GameSnap" / "GameSnap.exe"
TS = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3})")


def stamp(line: str) -> float:
    return datetime.strptime(TS.match(line).group(1), "%Y-%m-%d %H:%M:%S,%f").timestamp()


report = [f"exe={exe}"]
for i in range(N):
    appdata = RUN / f"appdata{i}"
    t0 = time.time()
    p = subprocess.Popen([str(exe), "--no-elevate", "--config", str(cfg)], cwd=PROJECT,
                         env=dict(os.environ, APPDATA=str(appdata)),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rc = p.wait(timeout=30)
    t_exit = time.time()
    lines = (appdata / "GameSnap" / "gamesnap.log").read_text(encoding="utf-8").splitlines()
    first = stamp(lines[0])
    app = next(stamp(s) for s in lines if "GameSnap 启动" in s)
    report.append(f"run {i}: first log line {1000 * (first - t0):5.0f} ms | app ready {1000 * (app - t0):5.0f} ms"
                  f" | exited after {t_exit - t0:4.1f} s (exit code {rc})")
(RUN / "report.txt").write_text("\n".join(report), encoding="utf-8")
