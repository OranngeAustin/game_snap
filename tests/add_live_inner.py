"""Run GameSnap's main() for a live test of 「添加游戏…」 (test_add_live.py starts this):
- dualsense.set_quad is a tripwire, so no system setting can change;
- toasts are written to gamesnap.log instead of shown (the hint would otherwise sit on the screen);
- ADD_TIMEOUT_SEC is <add timeout>;
- <delay> seconds after the tray is ready, App.start_adding runs as if clicked in the tray menu, and if
  <press pid> is not 0, one second later the screenshot key is "pressed" in that process's window:
  should_capture and App._on_key are called the way the keyboard hook calls them.

usage: python -X utf8 add_live_inner.py <project dir> <delay> <add timeout> <press pid> [main.py args...]
"""
import logging
import sys
import threading
import time
from pathlib import Path

proj = Path(sys.argv[1]).resolve()
delay, add_timeout, press_pid = float(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4])
sys.path.insert(0, str(proj))
import capture  # noqa: E402
import dualsense  # noqa: E402
import main  # noqa: E402
import toast  # noqa: E402

log = logging.getLogger("gamesnap.test")


def _tripwire(ep):
    raise AssertionError(f"test tripwire: set_quad({ep.item_id}) must not run")


def _toast_to_log(self, text, ok, monitor_rect, hold_ms=None):
    log.info("toast: %s | ok=%s | hold_ms=%s", text, ok, hold_ms)


dualsense.set_quad = _tripwire
toast.Toast.show = _toast_to_log
main.ADD_TIMEOUT_SEC = add_timeout
real_on_tray_ready = main.App._on_tray_ready


def on_tray_ready(self, icon):
    real_on_tray_ready(self, icon)

    def click():
        log.info("test: 托盘菜单「添加游戏…」")
        self.start_adding()
        if press_pid:
            time.sleep(1)
            log.info("test: 在 pid %d 的窗口里按截图键", press_pid)
            if self.should_capture(press_pid):
                self._on_key(capture.qpc_now(), 0, press_pid)

    timer = threading.Timer(delay, click)
    timer.daemon = True
    timer.start()


main.App._on_tray_ready = on_tray_ready
sys.argv = [str(proj / "main.py"), *sys.argv[5:]]
main.main()
