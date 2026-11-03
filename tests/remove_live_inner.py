"""Run GameSnap's main() for a live test of removing a game in the tray submenu 「游戏名单」
(test_remove_live.py starts this):
- dualsense.set_quad is a tripwire, so no system setting can change;
- toasts are written to gamesnap.log instead of shown; main.confirm logs the question and answers yes;
- <delay> seconds after the tray is ready, the line for <exe> in 「游戏名单」 is clicked: it is looked up in
  the Win32 menu pystray built for the tray icon, and the callback pystray registered for its id is called,
  which is what pystray's own click handler does with the id the popup menu returns.

usage: python -X utf8 remove_live_inner.py <project dir> <delay> <exe> [main.py args...]
"""
import ctypes
import ctypes.wintypes as wt
import logging
import sys
import threading
from pathlib import Path

proj = Path(sys.argv[1]).resolve()
delay, exe = float(sys.argv[2]), sys.argv[3]
sys.path.insert(0, str(proj))
import dualsense  # noqa: E402
import main  # noqa: E402
import toast  # noqa: E402

log = logging.getLogger("gamesnap.test")
user32 = ctypes.windll.user32
user32.GetMenuItemCount.argtypes = [wt.HMENU]
user32.GetSubMenu.argtypes = [wt.HMENU, ctypes.c_int]
user32.GetSubMenu.restype = wt.HMENU
user32.GetMenuStringW.argtypes = [wt.HMENU, wt.UINT, wt.LPWSTR, ctypes.c_int, wt.UINT]
user32.GetMenuItemID.argtypes = [wt.HMENU, ctypes.c_int]
user32.GetMenuItemID.restype = wt.UINT
MF_BYPOSITION = 0x400


def _tripwire(ep):
    raise AssertionError(f"test tripwire: set_quad({ep.item_id}) must not run")


def _toast_to_log(self, text, ok, monitor_rect, hold_ms=None):
    log.info("toast: %s | ok=%s | hold_ms=%s", text, ok, hold_ms)


def _confirm_yes(text):
    log.info("test: 确认框「%s」→ 是", text.replace("\n", " "))
    return True


def strings(h) -> list[str]:
    out = []
    for k in range(user32.GetMenuItemCount(h)):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetMenuStringW(h, k, buf, 256, MF_BYPOSITION)
        out.append(buf.value)
    return out


dualsense.set_quad = _tripwire
toast.Toast.show = _toast_to_log
main.confirm = _confirm_yes
real_on_tray_ready = main.App._on_tray_ready


def on_tray_ready(self, icon):
    real_on_tray_ready(self, icon)

    def click():
        hmenu, callbacks = icon._menu_handle
        hsub = user32.GetSubMenu(hmenu, strings(hmenu).index("游戏名单"))
        sub = strings(hsub)
        log.info("test: 「游戏名单」子菜单：%s", " | ".join(sub))
        k = next(k for k, s in enumerate(sub) if s.endswith(f"（{exe}）"))
        log.info("test: 点「%s」", sub[k])
        callbacks[user32.GetMenuItemID(hsub, k) - 1](icon)

    timer = threading.Timer(delay, click)
    timer.daemon = True
    timer.start()


main.App._on_tray_ready = on_tray_ready
sys.argv = [str(proj / "main.py"), *sys.argv[4:]]
main.main()
