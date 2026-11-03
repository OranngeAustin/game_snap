"""Check the exit rule with several things open at once: GameSnap must keep running while any listed game
or launcher is still open, and quit only after all of them have closed (plus exit_grace_sec).
Stand-ins are renamed copies of ping.exe in the run folder: fakeyuzu.exe and fakecloud.exe as games,
fakehyp.exe as the launcher. Runs dist\\GameSnap\\GameSnap.exe --no-elevate with a test config and
APPDATA inside the run folder, once per closing order. After each close but the last it waits longer than
the grace period and checks GameSnap is still running; after the last close GameSnap must exit within
the grace period plus a poll or two. Writes report.txt into the run folder.

usage: python -X utf8 tests\\test_multi_exit.py <run dir>
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT, RUN = Path(__file__).resolve().parent.parent, Path(sys.argv[1])
RUN.mkdir(parents=True, exist_ok=False)
PING = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "PING.EXE"
EXE = PROJECT / "dist" / "GameSnap" / "GameSnap.exe"
CREATE_NO_WINDOW = 0x08000000
GRACE = 3
NAMES = ("fakeyuzu.exe", "fakecloud.exe", "fakehyp.exe")
ORDERS = [("fakehyp.exe", "fakeyuzu.exe", "fakecloud.exe"),    # launcher first, then the games
          ("fakeyuzu.exe", "fakecloud.exe", "fakehyp.exe")]    # games first, launcher last

for name in NAMES:
    shutil.copy2(PING, RUN / name)
cfg = RUN / "config.json"
cfg.write_text(json.dumps({
    "games": {"fakeyuzu.exe": "假yuzu", "fakecloud.exe": "假云原神"},
    "launchers": ["fakehyp.exe"],
    "poll_interval_sec": 1, "exit_grace_sec": GRACE, "wait_no_launcher_sec": 60,
    "toast": False, "sound": False, "copy_to_clipboard": False, "dualsense_quad": False,
    "save_dir": str(RUN / "shots"),
}, ensure_ascii=False, indent=2), encoding="utf-8")

report: list[str] = [f"exe={EXE}", f"exit_grace_sec={GRACE}"]
failures: list[str] = []


def check(label: str, ok: bool) -> None:
    report.append(f"    {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        failures.append(label)


for n, order in enumerate(ORDERS):
    appdata = RUN / f"appdata{n}"
    report.append(f"\n== order {n}: close {' -> '.join(order)}")
    t0 = time.monotonic()

    def mark(text: str) -> None:
        report.append(f"  {time.monotonic() - t0:5.1f}s  {text}")

    gs = subprocess.Popen([str(EXE), "--no-elevate", "--config", str(cfg)], cwd=PROJECT,
                          env=dict(os.environ, APPDATA=str(appdata)))
    mark(f"GameSnap started (pid {gs.pid})")
    time.sleep(2)
    procs = {name: subprocess.Popen([str(RUN / name), "-n", "120", "127.0.0.1"], stdout=subprocess.DEVNULL,
                                    creationflags=CREATE_NO_WINDOW) for name in NAMES}
    mark("started fakeyuzu, fakecloud (games) and fakehyp (launcher)")
    time.sleep(4)
    for i, name in enumerate(order):
        procs[name].kill()
        procs[name].wait()
        mark(f"closed {name}")
        if i < len(order) - 1:
            time.sleep(GRACE + 3)
            check(f"{GRACE + 3}s after closing {name}, GameSnap still running", gs.poll() is None)
    t_last = time.monotonic()
    try:
        rc = gs.wait(timeout=30)
        delay = time.monotonic() - t_last
        mark(f"GameSnap exited {delay:.1f}s after the last one closed, exit code {rc}")
        # exit_grace_sec counts from the last poll that still saw a game, so up to one poll interval less
        check(f"exited within {GRACE - 1.2:g}-{GRACE + 3}s after the last close", GRACE - 1.2 <= delay <= GRACE + 3)
        check("exit code 0", rc == 0)
    except subprocess.TimeoutExpired:
        gs.kill()
        mark("GameSnap did NOT exit within 30s; killed")
        check("GameSnap exited", False)
    for p in procs.values():
        if p.poll() is None:
            p.kill()
    log = appdata / "GameSnap" / "gamesnap.log"
    report.append("  --- gamesnap.log ---")
    report.extend("  " + s for s in (log.read_text(encoding="utf-8").splitlines() if log.exists() else ["(missing)"]))

report.append("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
(RUN / "report.txt").write_text("\n".join(report), encoding="utf-8")
sys.exit(1 if failures else 0)
