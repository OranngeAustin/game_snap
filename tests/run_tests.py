"""Run GameSnap's tests, each in its own folder under <out>, and write summary.txt there.

usage: python -X utf8 tests\\run_tests.py [quick | all | <test> ...] [--out <dir>]

- quick (the default): the in-process tests, about half a minute. They start no GameSnap, so they can run
  anywhere, also inside the Claude app's container.
- all: quick plus the tests that start GameSnap itself (the source with the real tray, keyboard hook and
  process watcher, and the built dist\\GameSnap\\GameSnap.exe), about 3 minutes. Quit any running GameSnap
  first, rebuild dist if the source changed, and start this outside the Claude app's container (CLAUDE.md).
- <test>: names from QUICK and SLOW below, e.g. `add_game remove_live`.
<out> defaults to build\\test_runs\\suite_<date>_<time>. Each test's console output goes to <out>\\<name>.txt,
its own files (config, logs, report.txt) to <out>\\<name>\\. Exit code 1 if a test failed.
Run it with the gamesnap-build interpreter: the tests run with the same one.
"""
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
# name -> script and arguments; {run} is the test's own folder, which the test creates
QUICK = {
    "not_games": ["test_not_games.py"],
    "toast_card": ["test_toast_card.py", "{run}"],
    "toast_gdi": ["test_toast_gdi.py"],
    "config": ["test_config.py", "{run}"],
    "config_values": ["test_config_values.py", "{run}"],
    "add_game": ["test_add_game.py", "{run}"],
    "tray_icon": ["test_tray_icon.py", "{run}"],
    "tray_refresh": ["test_tray_refresh.py", "{run}"],
    "blocklist_remove": ["test_blocklist_remove.py", "{run}"],
    "yuzu_naming": ["test_yuzu_naming.py", "{run}"],
    "safe_name": ["test_safe_name.py", "{run}"],
    "clipboard": ["test_clipboard.py", "{run}"],
    "capture_resize": ["test_capture_resize.py"],
    "dualsense": ["test_dualsense.py"],
    "listener_restart": ["test_listener_restart.py", "{run}"],
    "listener_sync": ["test_listener_sync.py", "{run}"],
    "listener_start_fail": ["test_listener_start_fail.py", "{run}"],
    "instance_quit": ["test_instance_quit.py", "{run}"],
    "clipboard_error": ["test_clipboard_error.py", "{run}"],
    "save_png_fail": ["test_save_png_fail.py", "{run}"],
    "scan_fail": ["test_scan_fail.py"],
    "idle_order": ["test_idle_order.py", "{run}"],
    "learn_race": ["test_learn_race.py", "{run}"],
    "games_update": ["test_games_update.py", "{run}"],
    "config_save_fail": ["test_config_save_fail.py", "{run}"],
    "held_key": ["test_held_key.py"],
    "key_name": ["test_key_name.py"],
    "win_event_hook": ["test_win_event_hook.py"],
    "d3d_staging": ["test_d3d_staging.py"],
}
SLOW = {
    "lifecycle_source": ["test_lifecycle.py", "source", "{run}"],
    "add_live": ["test_add_live.py", "{run}"],
    "remove_live": ["test_remove_live.py", "{run}"],
    "lifecycle_exe": ["test_lifecycle.py", "exe", "{run}"],
    "multi_exit": ["test_multi_exit.py", "{run}"],
}
TESTS = {**QUICK, **SLOW}
TIMEOUT_SEC = 300

args = sys.argv[1:]
out = None
if "--out" in args:
    i = args.index("--out")
    out = Path(args[i + 1])
    del args[i:i + 2]
label = " ".join(args) or "quick"
names = {"quick": list(QUICK), "all": list(TESTS)}.get(label, args)
unknown = [n for n in names if n not in TESTS]
if unknown:
    sys.exit(f"unknown test(s) {unknown}; known: quick, all, {', '.join(TESTS)}")
try:
    import pystray  # noqa: F401  (the tests import the project, which needs the gamesnap-build packages)
except ImportError:
    sys.exit(r"run this with D:\anaconda3\envs\gamesnap-build\python.exe")
if any(n in SLOW for n in names):
    sys.path.insert(0, str(PROJECT))
    from watcher import snapshot_names
    if "gamesnap.exe" in snapshot_names().values():
        sys.exit("GameSnap.exe is running: quit it first (a test instance would exit or take its place)")

out = out or PROJECT / "build" / "test_runs" / f"suite_{datetime.now():%Y%m%d_%H%M%S}"
out.mkdir(parents=True, exist_ok=False)
summary = [f"GameSnap tests {datetime.now():%Y-%m-%d %H:%M:%S} ({label})"]
failed = 0
for name in names:
    script, *rest = TESTS[name]
    cmd = [sys.executable, "-X", "utf8", str(HERE / script), *(a.replace("{run}", str(out / name)) for a in rest)]
    t0 = time.monotonic()
    with open(out / f"{name}.txt", "wb") as f:
        try:
            rc = subprocess.run(cmd, cwd=PROJECT, stdout=f, stderr=subprocess.STDOUT, timeout=TIMEOUT_SEC).returncode
        except subprocess.TimeoutExpired:
            rc = "timeout"
    summary.append(f"{'PASS' if rc == 0 else 'FAIL'}  {name:<18} {time.monotonic() - t0:6.1f}s"
                   + ("" if rc == 0 else f"  (exit code {rc})"))
    if rc != 0:
        failed += 1
        text = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                         for p in (out / f"{name}.txt", out / name / "report.txt") if p.exists())
        lines = [s.strip() for s in text.splitlines() if s.strip().startswith("FAIL")]
        summary.extend("      " + s for s in (lines or text.strip().splitlines()[-1:]))
summary.append(f"\n{len(names) - failed} passed, {failed} failed -> {out}")
(out / "summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
print("\n".join(summary))
sys.exit(1 if failed else 0)
