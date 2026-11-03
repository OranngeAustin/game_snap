"""Run GameSnap through one lifecycle with ping.exe standing in for the game (start -> game detected ->
game closed -> auto-exit) and check the DualSense guard runs alongside. Never changes a system setting:
- source: main.py through gamesnap_tripwire.py (dualsense.set_quad replaced by a tripwire), feature on;
- exe: dist\\GameSnap\\GameSnap.exe with the feature switched off in the test config.
APPDATA points into the run folder, so the real config and logs are untouched. Writes report.txt there.
Exit code 1 if a check failed.

usage: python -X utf8 tests\\test_lifecycle.py source|exe <run dir>
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT, MODE, RUN, TRIPWIRE = HERE.parent, sys.argv[1], Path(sys.argv[2]), HERE / "gamesnap_tripwire.py"
BUILD_PY = r"D:\anaconda3\envs\gamesnap-build\python.exe"
CREATE_NO_WINDOW = 0x08000000

RUN.mkdir(parents=True, exist_ok=False)   # 每次用新文件夹，日志不和上次混在一起
appdata = RUN / "appdata"
cfg_path = RUN / "config.json"
cfg_path.write_text(json.dumps({
    "games": {"PING.EXE": "测试游戏"},
    "launchers": [],
    "poll_interval_sec": 1,
    "exit_grace_sec": 3,
    "wait_no_launcher_sec": 60,
    "toast": False,
    "sound": False,
    "copy_to_clipboard": False,
    "dualsense_quad": MODE == "source",
    "save_dir": str(RUN / "shots"),
}, ensure_ascii=False, indent=2), encoding="utf-8")

if MODE == "source":
    cmd = [BUILD_PY, "-X", "utf8", str(TRIPWIRE), str(PROJECT), "--no-elevate", "--config", str(cfg_path)]
else:
    cmd = [str(PROJECT / "dist" / "GameSnap" / "GameSnap.exe"), "--no-elevate", "--config", str(cfg_path)]
env = dict(os.environ, APPDATA=str(appdata))

report: list[str] = [f"mode={MODE}", "cmd=" + subprocess.list2cmdline(cmd)]
t0 = time.monotonic()
with open(RUN / "stderr.txt", "wb") as err:
    gs = subprocess.Popen(cmd, cwd=PROJECT, env=env, stdout=subprocess.DEVNULL, stderr=err)
    time.sleep(3)
    game = subprocess.Popen(["ping", "-n", "60", "127.0.0.1"], stdout=subprocess.DEVNULL,
                            creationflags=CREATE_NO_WINDOW)
    report.append(f"{time.monotonic() - t0:5.1f}s  fake game started (pid {game.pid})")
    time.sleep(6)
    game.kill()
    game.wait()
    report.append(f"{time.monotonic() - t0:5.1f}s  fake game closed")
    try:
        rc = gs.wait(timeout=30)
        report.append(f"{time.monotonic() - t0:5.1f}s  GameSnap exited, exit code {rc}")
    except subprocess.TimeoutExpired:
        gs.kill()
        rc = None
        report.append(f"{time.monotonic() - t0:5.1f}s  GameSnap did NOT exit within 30s; killed")

texts = {}
for name in ("gamesnap.log", "crash.log"):
    p = appdata / "GameSnap" / name
    texts[name] = p.read_text(encoding="utf-8", errors="replace").rstrip() if p.exists() else ""
    report.append(f"--- {name} ---")
    report.append(texts[name] or "(missing)")
stderr = (RUN / "stderr.txt").read_text(encoding="utf-8", errors="replace").rstrip()
report.append("--- stderr ---")
report.append(stderr or "(empty)")

failures: list[str] = []


def check(label: str, ok: bool) -> None:
    report.append(f"    {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        failures.append(label)


log = texts["gamesnap.log"]
report.append("--- checks ---")
check("exited by itself, exit code 0", rc == 0)
check("detected the fake game", f"检测到游戏：测试游戏(pid {game.pid})" in log)
check("quit after the game closed", "自动退出：游戏和启动器都已退出" in log)
check("crash.log has only the start line", len(texts["crash.log"].splitlines()) == 1)
check("stderr empty", not stderr)
if MODE == "source":
    # fails if a DualSense is plugged in but not set to quad: the tripwire then stopped a real change
    check("DualSense guard checked and changed nothing",
          ("没有插着 DualSense" in log or "DualSense 声音设置正常" in log) and "tripwire" not in log)
report.append("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
(RUN / "report.txt").write_text("\n".join(report), encoding="utf-8")
sys.exit(1 if failures else 0)
