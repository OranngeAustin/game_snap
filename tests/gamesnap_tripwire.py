"""Run GameSnap's main.py with dualsense.set_quad replaced by a tripwire, so a test run can never change a
system setting. If the guard ever decides to change something, the tripwire raises and the traceback
lands in gamesnap.log.

usage: python -X utf8 gamesnap_tripwire.py <project dir> [main.py args...]
"""
import runpy
import sys
from pathlib import Path

proj = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(proj))
import dualsense  # noqa: E402


def _tripwire(ep):
    raise AssertionError(f"test tripwire: set_quad({ep.item_id}) must not run")


dualsense.set_quad = _tripwire
sys.argv = [str(proj / "main.py"), *sys.argv[2:]]
runpy.run_path(str(proj / "main.py"), run_name="__main__")
