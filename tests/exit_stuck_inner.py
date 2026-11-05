"""Run GameSnap's main() for test_exit_stuck.py:
- dualsense.set_quad is a tripwire, so no system setting can change;
- its own single-instance names, so a running GameSnap is neither replaced nor in the way;
- lost: pystray's _on_stop does nothing, so the message loop never gets WM_QUIT and stays in GetMessage. That
  is what a tray menu open at exit leaves behind (05 doc P7), without opening a menu and taking the foreground;
- normal: pystray as it is.

usage: python -X utf8 exit_stuck_inner.py <project dir> lost|normal [main.py args...]
"""
import sys
from pathlib import Path

proj = Path(sys.argv[1]).resolve()
mode = sys.argv[2]
sys.path.insert(0, str(proj))
import dualsense  # noqa: E402
import instance  # noqa: E402
import pystray._win32 as pw  # noqa: E402
import main  # noqa: E402


def _tripwire(ep):
    raise AssertionError(f"test tripwire: set_quad({ep.item_id}) must not run")


dualsense.set_quad = _tripwire
instance.MUTEX_NAME = "Local\\GameSnap_ExitStuck_Single"
instance.ELEVATED_NAME = "Local\\GameSnap_ExitStuck_Elevated"
instance.QUIT_EVENT_NAME = "Local\\GameSnap_ExitStuck_Quit"
if mode == "lost":
    pw.Icon._on_stop = lambda self, wparam, lparam: 0
sys.argv = [str(proj / "main.py"), *sys.argv[3:]]
main.main()
