"""GameSnap 入口：游戏内一键全屏截图。不常驻：随游戏退出。

生命周期：
  等待   —— 没有游戏在运行：每 2 秒查一次进程（启动器开着就一直等）
  工作   —— 游戏在运行：挂上按键监听；游戏切到前台时建好截图通道
  退出   —— 游戏和启动器都关掉若干秒后，GameSnap 自己退出
同一时间只运行一个 GameSnap，规则见 instance.py。
运行期间顺带照看 DualSense 手柄的声音设置（原神的手柄震动要求四声道），见 dualsense.py。
运行：python main.py [--launch 启动器.exe [--launch-args 参数]] [--no-elevate] [--console] [--config 配置文件]
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import faulthandler
import functools
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time
import winsound
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

# 必须在创建任何窗口之前：按物理像素工作，浮层位置和截图尺寸才对得上
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import pystray  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from capture import QPC_FREQ, Capturer, monitor_of_window  # noqa: E402
from config import APP_DIR, LOG_PATH, Config  # noqa: E402
from dualsense import FIXED, NO_TOOL, DualSenseGuard  # noqa: E402
from hotkey import InputListener, key_name  # noqa: E402
from instance import Instance  # noqa: E402
from not_games import NOT_GAMES  # noqa: E402
from output import copy_to_clipboard, save_png, shots_root  # noqa: E402
from toast import Toast  # noqa: E402
from watcher import GameWatcher, foreground, process_name, window_title  # noqa: E402

log = logging.getLogger("gamesnap")

CRASH_LOG = APP_DIR / "crash.log"
LEARN_TIMEOUT_SEC = 10
ADD_TIMEOUT_SEC = 15     # 「添加游戏」等用户在游戏里按截图键的时间
TRIM_INTERVAL_SEC = 60   # 等待进游戏时，每隔这么久把闲置内存页交还系统
EXIT_WATCHDOG_SEC = 3    # 退出时等托盘消息循环结束的时间，过了就直接结束进程（见 start_exit_watchdog）

_psapi = ctypes.WinDLL("psapi")
_psapi.EmptyWorkingSet.argtypes = [wt.HANDLE]


def trim_working_set() -> None:
    """把闲置的内存页交还系统（物理内存占用降到 1–2MB，提交内存不变，用到时再调回）。
    只在等待进游戏时调用：游戏中要保证按键钩子的代码常驻内存、响应及时。"""
    _psapi.EmptyWorkingSet(wt.HANDLE(-1))   # GetCurrentProcess() 伪句柄


def primary_rect() -> tuple[int, int, int, int]:
    return monitor_of_window(0)[1]


def emulator_game(hwnd: int) -> str | None:
    """模拟器里正在玩的游戏，从窗口标题取，截图按它分文件夹。yuzu 玩游戏时标题是
    「yuzu Early Access 4167 | 游戏名 | 版本 | 显卡」（没有版本号时少一段）；停在游戏列表时
    只有「yuzu Early Access 4167」，这时返回 None，用游戏名单里的名字。"""
    parts = window_title(hwnd).split(" | ")
    if len(parts) >= 3 and parts[0].lower().startswith("yuzu"):
        return parts[1].strip() or None
    return None


def default_game_name(hwnd: int, exe: str) -> str:
    """新加游戏的名字（也是截图文件夹名）：窗口标题，去掉「 - 」「 | 」「 (」后面的版本、渲染器之类；
    没有标题或太长时用进程名。之后可以在 config.json 里改。"""
    title = re.split(r" - | \| | \(", window_title(hwnd))[0].strip()
    return title if 0 < len(title) <= 40 else exe.rsplit(".", 1)[0]


# ---------------------------------------------------------------- 截图工作线程
class CaptureWorker(threading.Thread):
    """唯一拥有 Capturer（D3D 设备和截图会话）的线程；保存/剪贴板交给单线程池，保证顺序。"""

    def __init__(self, app: "App") -> None:
        super().__init__(name="CaptureWorker", daemon=True)
        self.app = app
        self.q: queue.Queue = queue.Queue()
        self.saver = ThreadPoolExecutor(max_workers=1, thread_name_prefix="Saver")
        # 只由本线程使用；挂在实例上，线程结束后也不会被回收（回收就等于关会话，见 capture.Capturer）
        self.cap: Capturer | None = None

    def post(self, *msg) -> None:
        self.q.put(msg)

    def run(self) -> None:
        cap = self.cap = Capturer()
        while True:
            msg = self.q.get()
            kind = msg[0]
            try:
                if kind == "quit":
                    self.saver.shutdown(wait=True)
                    return
                if kind == "fg":
                    _, hwnd, pid = msg
                    if pid in self.app.games:   # 切到别的窗口时会话照常开着，见 capture.Capturer
                        cap.open(hwnd)
                elif kind == "warmup":
                    cap.prepare(msg[1])   # 游戏刚启动时先建好设备，别等到切到前台/按键
                elif kind == "shot":
                    _, t_key, hwnd, pid = msg
                    self._shot(cap, t_key, hwnd, pid)
            except Exception:
                log.exception("截图线程处理 %s 出错", kind)

    def _shot(self, cap: Capturer, t_key: int, hwnd: int, pid: int) -> None:
        game = emulator_game(hwnd) or self.app.games.get(pid, "未知游戏")
        rect = monitor_of_window(hwnd)[1]
        try:
            shot = cap.grab(hwnd, t_key)
        except Exception:
            log.exception("抓帧失败")
            self.app.notify("截图失败", False, rect)
            return
        self.saver.submit(self.app.finish_shot, shot, game, datetime.now(), t_key, rect)


# ---------------------------------------------------------------- 主程序
class App:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        # 设置重试后仍没写进 config.json（文件被占用）：提示一下，程序照常往下走（L18）
        cfg.on_save_error = lambda: self.toast.show("设置没保存上（config.json 被占用），详见日志", False,
                                                    primary_rect(), 3000)
        self.games: dict[int, str] = {}   # 正在运行的游戏 {pid: 显示名}
        self.paused = False
        self.shot_count = 0
        self.listener: InputListener | None = None
        self._listener_lock = threading.Lock()
        self._learn_timer: threading.Timer | None = None
        self._learn_lock = threading.Lock()   # 学到的键和超时可能同时到（L2）
        self.learning = False
        self.adding = False                  # 「添加游戏」：在等用户到游戏里按截图键
        self._add_lock = threading.Lock()
        self._add_timer: threading.Timer | None = None
        self._add_deadline = 0.0
        self._started = time.monotonic()
        self._seen_game = False              # 本次运行是否已经进过游戏
        self.launcher_running = False
        self._idle_since = time.monotonic()  # 从这时起既没有游戏也没有启动器
        self._next_trim = time.monotonic() + 4   # 启动后几秒、初始化都做完了再第一次修剪
        self._quitting = False
        self._tray_lock = threading.Lock()   # refresh_tray 会被多个线程调用，pystray 自己不加锁（M6）
        self._tray_state = "idle"            # 托盘上现在显示的图标
        self.on_tray_ready = None            # 托盘就绪后调用（main 在这时才开始等单实例的退出信号，M8）
        self.on_quitting = None              # 让托盘退出之前调用（main 在这时开始退出看门狗）

        self.toast = Toast()
        self.worker = CaptureWorker(self)
        self.watcher = GameWatcher(cfg.games_lower, cfg.launchers_lower,
                                   lambda: float(cfg["poll_interval_sec"]), self.on_poll)
        self.dualsense = DualSenseGuard(lambda: cfg["dualsense_quad"], self._on_dualsense)
        self.icon = pystray.Icon("GameSnap", make_icon(self._tray_state), "GameSnap", self._menu())

    def run(self) -> None:
        self.toast.start()
        self.worker.start()
        log.info("GameSnap 启动，截图键：%s，游戏名单：%s",
                 key_name(self.cfg["hotkey"]), ", ".join(self.cfg["games"]))
        self.icon.run(setup=self._on_tray_ready)   # 阻塞主线程直到退出

    def _on_tray_ready(self, icon: pystray.Icon) -> None:
        # 托盘就绪后再开始检测进程，避免游戏已在运行时提前刷新托盘
        icon.visible = True
        self.refresh_tray()
        self.watcher.start()
        self.dualsense.start()
        if self.on_tray_ready is not None:
            self.on_tray_ready()
        if self.cfg.read_only:
            # 单独一个线程：对话框没人点时不拖住这个 setup 线程，icon.stop() 退出时要等它（等到 pystray 的超时才放行）
            threading.Thread(target=message_box, name="ReadOnlyNotice", daemon=True, args=(
                f"配置文件现在读不出来（可能被别的程序占着），也没能另存一份：\n{self.cfg.path}\n\n"
                "这次用默认配置运行，游戏名单是默认的，设置也不会保存，原文件不会被改动。\n"
                "请退出 GameSnap，等占着它的程序结束后再打开。",)).start()

    # ---------- 状态 ----------
    def should_capture(self, pid: int) -> bool:
        if self.adding:   # 添加游戏：在别的程序里按截图键也收下，交给 _on_key
            return pid not in (0, os.getpid())
        return not self.paused and pid in self.games

    def on_poll(self, games: dict[int, str], launcher_running: bool) -> None:
        """GameWatcher 线程每次扫描后回调：处理游戏进出，并决定何时自动退出。"""
        if games != self.games:
            self._on_games_changed(games)
        now = time.monotonic()
        if games:
            self._seen_game = True
            self._idle_since = now
            return
        if self.learning or self.adding:
            return
        if launcher_running != self.launcher_running:
            self.launcher_running = launcher_running
            self.refresh_tray()
        if launcher_running:
            # 启动器开着就一直等：可能在下载大版本更新，或者待会儿还要从它进游戏
            # （例如云原神关了，但启动器还开着）
            self._idle_since = now
        else:
            limit = self.cfg["exit_grace_sec"] if self._seen_game else self.cfg["wait_no_launcher_sec"]
            if now - self._idle_since >= limit:
                self._auto_quit("游戏和启动器都已退出" if self._seen_game else "没有检测到游戏或启动器")
                return
        if now >= self._next_trim:   # 等待进游戏期间：定期把闲置内存交还系统
            self._next_trim = now + TRIM_INTERVAL_SEC
            trim_working_set()

    def _on_games_changed(self, games: dict[int, str]) -> None:
        self.games = games
        if games:
            log.info("检测到游戏：%s", ", ".join(f"{n}(pid {p})" for p, n in games.items()))
            self._sync_listener()
            hwnd, pid = foreground()
            self.worker.post("warmup", hwnd)
            self.worker.post("fg", hwnd, pid)
        else:
            log.info("游戏已全部退出；启动器也关掉后 %d 秒，GameSnap 退出", self.cfg["exit_grace_sec"])
            self._sync_listener()   # 正在更换截图键、添加游戏时不摘
        self.refresh_tray()

    def _auto_quit(self, reason: str) -> None:
        log.info("自动退出：%s", reason)
        self._quit(self.icon, None)

    def _sync_listener(self) -> InputListener | None:
        """按当前状态挂上或摘掉按键监听，返回挂着的那个（没挂时为 None）。
        有游戏在运行、正在更换截图键或添加游戏时挂，否则摘。

        「该不该挂」的判断和真正挂 / 摘在同一把锁里（02-findings M7）。改 games / learning / adding 的线程
        改完都调一次这里，最后拿到锁的那次看到的是各线程都改完之后的状态。以前是锁外先判断、再进锁挂或摘，
        中间别的线程可能刚开始用这个监听（更换截图键、添加游戏）或刚检测到游戏，结果监听被摘掉，
        学键永远不结束、GameSnap 不再自动退出，或者这局游戏截图键没反应。"""
        with self._listener_lock:
            want = bool(self.games) or self.learning or self.adding
            if want and self.listener is None:
                listener = InputListener(
                    self.cfg["hotkey"], self.should_capture,
                    on_shot=self._on_key,
                    on_foreground=lambda h, p: self.worker.post("fg", h, p),
                    on_learned=self._on_learned,
                )
                listener.start()
                if not listener.wait_ready():
                    listener.join(0.5)   # 启动失败时线程马上结束；只是启动得慢就还活着，照旧留着
                    if not listener.is_alive():
                        # 以前留着这个死掉的监听，截图键、学键、添加游戏都静默失效（02-findings M4）
                        log.warning("按键监听没启动起来，截图键暂时无效；之后需要监听时"
                                    "（检测到游戏、更换截图键、添加游戏）会再试")
                        self.toast.show("按键监听没启动起来，截图键暂时无效，详见日志", False, primary_rect(), 3000)
                        return None
                self.listener = listener
            elif not want and self.listener is not None:
                self.listener.stop()
                self.listener = None
            return self.listener

    def _stop_listener(self) -> None:
        with self._listener_lock:
            if self.listener is not None:
                self.listener.stop()
                self.listener = None

    # ---------- 截图收尾（Saver 线程） ----------
    def finish_shot(self, shot, game: str, when: datetime, t_key: int,
                    rect: tuple[int, int, int, int]) -> None:
        frame_minus_key = (shot.frame_ticks - t_key) / QPC_FREQ * 1000
        key_to_grab = (shot.grabbed_ticks - t_key) / QPC_FREQ * 1000
        try:
            path = save_png(shot.image, shots_root(self.cfg["save_dir"]), game, when, {
                "Software": "GameSnap",
                "GameSnap": f"game={game}; backend={shot.backend}; "
                            f"frame_minus_key_ms={frame_minus_key:+.1f}; "
                            f"key_to_grab_ms={key_to_grab:.1f}",
            })
            if self.cfg["copy_to_clipboard"]:
                copy_to_clipboard(shot.image)
        except Exception:
            log.exception("保存截图失败")
            self.notify("截图失败", False, rect)
            return
        self.shot_count += 1
        log.info("截图 #%d %s | 后端 %s | 帧上屏-按键 %+.1fms | 按键→抓到 %.1fms | %s",
                 self.shot_count, game, shot.backend, frame_minus_key, key_to_grab, path)
        self.notify(f"已截图 · {game}", True, rect)
        self.refresh_tray()

    def notify(self, text: str, ok: bool, rect, hold_ms: int | None = None) -> None:
        if self.cfg["toast"]:
            self.toast.show(text, ok, rect, hold_ms)
        if self.cfg["sound"]:
            winsound.MessageBeep(winsound.MB_OK if ok else winsound.MB_ICONHAND)

    # ---------- 更换截图键 ----------
    def start_learning(self, icon=None, item=None) -> None:
        if self.learning or self.adding:
            return
        self.learning = True
        listener = self._sync_listener()   # learning 已置位，挂上之后别的线程不会摘
        if listener is None:               # 监听没启动起来（已提示），不进入学键状态
            self.learning = False
            self._sync_listener()
            return
        listener.start_learning()
        self.toast.show("请按下新的截图键或鼠标侧键（Esc 取消）", True, primary_rect(),
                        LEARN_TIMEOUT_SEC * 1000)
        self._learn_timer = threading.Timer(LEARN_TIMEOUT_SEC, self._learn_timeout)
        self._learn_timer.daemon = True
        self._learn_timer.start()

    def _learn_timeout(self) -> None:
        if not self.learning:
            return
        listener = self.listener
        if listener is not None:
            listener.cancel_learning()
        self._finish_learning(None)   # 监听不在了也要结束学键，否则 learning 一直是 True、不再自动退出

    def _on_learned(self, binding: dict | None) -> None:
        # 在监听线程里被调用：保存配置等耗时操作挪到别的线程
        threading.Thread(target=self._finish_learning, args=(binding,), daemon=True).start()

    def _finish_learning(self, binding: dict | None) -> None:
        with self._learn_lock:   # 按键和超时同时到时只算一次：以前既存了新键又提示「已取消」（02-findings L2）
            if not self.learning:
                return
            # 学键花的时间不算进“没进游戏”的等待里。先设再清标志：反过来的话，GameWatcher 恰好在两行之间轮询，
            # 会用旧的 _idle_since 判断，刚结束就自动退出（02-findings L16）
            self._idle_since = time.monotonic()
            self.learning = False
        if self._learn_timer is not None:
            self._learn_timer.cancel()
        if binding:
            self.cfg.set("hotkey", binding)
            if self.listener is not None:
                self.listener.set_binding(binding)
            log.info("截图键改为 %s", key_name(binding))
            self.toast.show(f"截图键已设为 {key_name(binding)}", True, primary_rect(), 2000)
            winsound.MessageBeep(winsound.MB_OK)
        else:
            self.toast.show("已取消更换截图键", False, primary_rect(), 1500)
        self._sync_listener()   # 没游戏、也没在添加游戏就摘掉
        self.refresh_tray()

    # ---------- 添加 / 移除游戏 ----------
    def start_adding(self, icon=None, item=None) -> None:
        """托盘「添加游戏…」：等用户切到游戏里按一下截图键，把那个窗口所属的程序加进名单。"""
        if self.adding or self.learning:
            return
        self._add_deadline = time.monotonic() + ADD_TIMEOUT_SEC
        self._add_timer = threading.Timer(ADD_TIMEOUT_SEC, self._finish_adding, args=(0, 0, True))
        self._add_timer.daemon = True
        self.adding = True   # 计时器先建好：游戏开着时监听已在运行，置位后按键随时可能到
        if self._sync_listener() is None:   # 监听没启动起来（已提示），不进入等待
            self.adding = False
            self._add_timer.cancel()
            self._sync_listener()
            return
        self._add_timer.start()
        self._add_hint(f"切到要添加的游戏里，按一下截图键 {key_name(self.cfg['hotkey'])}", True)

    def _add_hint(self, text: str, ok: bool) -> None:
        """提示一直显示到等待结束。"""
        left_ms = int((self._add_deadline - time.monotonic()) * 1000)
        self.toast.show(text, ok, primary_rect(), max(left_ms, 1000))

    def _on_key(self, t_key: int, hwnd: int, pid: int) -> None:
        """监听线程回调，要尽快返回：平时截图；添加游戏时把这个窗口交给 _finish_adding。"""
        if self.adding:
            threading.Thread(target=self._finish_adding, args=(hwnd, pid), daemon=True).start()
        elif pid in self.games:
            self.worker.post("shot", t_key, hwnd, pid)

    def _finish_adding(self, hwnd: int, pid: int, timed_out: bool = False) -> None:
        exe = None
        with self._add_lock:   # 按键和超时可能同时到
            if not self.adding:
                return
            if not timed_out:
                exe = process_name(pid)
                lower = (exe or "").lower()
                if not exe or lower in NOT_GAMES or lower in self.cfg.launchers_lower():
                    self._add_hint(f"这不是游戏窗口（{exe or '未知程序'}），请在游戏画面里按截图键", False)
                    return   # 接着等，直到超时
            self._idle_since = time.monotonic()   # 等按键的时间不算进「没进游戏」的等待里；先设再清标志（L16）
            self.adding = False
            self._add_timer.cancel()
        known = self.cfg.games_lower().get(exe.lower()) if exe else None
        if exe is None:
            self.toast.show("没收到截图键，没有添加游戏", False, primary_rect(), 2000)
            self._sync_listener()   # 没游戏、也没在更换截图键就摘掉
        elif known:
            self.toast.show(f"已经在名单里了 · {known}", True, primary_rect(), 2500)
        else:
            name = default_game_name(hwnd, exe)
            self.cfg.update("games", lambda games: {**games, exe: name})   # 和「移除游戏」同时改也不丢（L17）
            log.info("添加游戏：%s → %s", exe, name)
            self.toast.show(f"已添加 · {name}（{exe}）", True, primary_rect(), 3000)
        self.refresh_tray()

    def _games_menu(self) -> pystray.Menu:
        """托盘「游戏名单」子菜单，每次刷新菜单时按当前名单生成。"""
        def items():
            games = self.cfg["games"]
            if not games:
                yield pystray.MenuItem("名单是空的，用「添加游戏…」添加", None, enabled=False)
                return
            yield pystray.MenuItem("点一项即可移除（会先确认）", None, enabled=False)
            yield pystray.Menu.SEPARATOR
            for exe, name in games.items():
                # Windows 菜单把 & 当快捷键标记，要写成 && 才显示出来（如 Ratchet & Clank）
                yield pystray.MenuItem(f"{name}（{exe}）".replace("&", "&&"), self._remove_game(exe))
        return pystray.Menu(items)

    def _remove_game(self, exe: str):
        def action(icon, item):
            name = self.cfg["games"].get(exe)
            if name is None or not confirm(f"把「{name}」（{exe}）从游戏名单里移除？\n\n"
                                           "移除后在它里面按截图键不再截图。要加回来，用「添加游戏…」。"):
                return
            # 换成新字典，不原地改：进程检测线程可能正在读旧的那个
            self.cfg.update("games", lambda games: {k: v for k, v in games.items() if k != exe})   # L17
            log.info("移除游戏：%s（%s）", exe, name)
            self.toast.show(f"已移除 · {name}（{exe}）", True, primary_rect(), 2500)
            self.refresh_tray()
        return action

    # ---------- DualSense 声音设置（DualSense 线程回调） ----------
    def _on_dualsense(self, status: str) -> None:
        """设置正常时不会被调用；改过、没改成、没法改时才提示。"""
        if status == FIXED:
            text = "DualSense 已改为四声道" + ("，没有震动的话重启游戏" if self.games else "")
        elif status == NO_TOOL:
            text = "DualSense 不是四声道，请在声音设置里改"
        else:
            text = "DualSense 没能改成四声道，详见日志"
        self.toast.show(text, status == FIXED, primary_rect(), 4000)

    # ---------- 托盘 ----------
    def status_text(self) -> str:
        if self.paused:
            return "已暂停"
        if self.games:
            return "工作中：" + "、".join(sorted(set(self.games.values())))
        if self._seen_game and not self.launcher_running:
            return "游戏已退出，即将关闭"
        return "等待游戏启动…"

    def refresh_tray(self) -> None:
        """GameWatcher、Saver、Timer、学键 / 添加线程、托盘线程都会调。pystray 换图标（DestroyIcon / LoadImage /
        Shell_NotifyIcon）、重建菜单都在调用线程里直接做、不加锁，所以整个刷新放进一把锁，状态在锁里算，
        晚到的线程不会用旧状态盖掉新状态；图标状态没变就不重设（02-findings M6）。"""
        with self._tray_lock:
            state = "paused" if self.paused else ("active" if self.games else "idle")
            if state != self._tray_state:
                self.icon.icon = make_icon(state)
                self._tray_state = state
            self.icon.title = (f"GameSnap · {self.status_text()}\n"
                               f"截图键 {key_name(self.cfg['hotkey'])} · 本次已截 {self.shot_count} 张")
            self.icon.update_menu()

    def _toggle(self, key: str):
        def action(icon, item):
            self.cfg.set(key, not self.cfg[key])
            self.refresh_tray()
        return action

    def _toggle_dualsense(self, icon, item) -> None:
        on = not self.cfg["dualsense_quad"]
        self.cfg.set("dualsense_quad", on)
        if on:
            self.dualsense.recheck()   # 刚打开：马上查一遍插着的手柄
        self.refresh_tray()

    def _toggle_pause(self, icon, item) -> None:
        self.paused = not self.paused
        log.info("暂停" if self.paused else "恢复")
        self.refresh_tray()

    def _open_folder(self, icon=None, item=None) -> None:
        root = shots_root(self.cfg["save_dir"])
        root.mkdir(parents=True, exist_ok=True)
        os.startfile(root)

    def _quit(self, icon, item) -> None:
        if self._quitting:   # 托盘「退出」和自动退出可能同时触发
            return
        self._quitting = True
        log.info("退出")
        try:
            self.watcher.stop()
            self._stop_listener()
            self.worker.post("quit")
            if self.worker.ident is not None:   # 还没启动的线程 join 会抛 RuntimeError
                self.worker.join(timeout=5)
            self.toast.stop()
        except Exception:
            log.exception("退出时出错")
        finally:
            # 前面哪一步出错都要让托盘退出：_quitting 已置位，否则托盘留着、「退出」也点不动（M8）
            try:
                if self.on_quitting:   # 在 icon.stop() 之前：它可能阻塞几秒，也可能抛异常
                    self.on_quitting()
            except Exception:
                log.exception("退出时出错")
            icon.stop()

    def _menu(self) -> pystray.Menu:
        I = pystray.MenuItem
        return pystray.Menu(
            I(lambda item: self.status_text(), None, enabled=False),
            I(lambda item: f"截图键：{key_name(self.cfg['hotkey'])}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            I("打开截图文件夹", self._open_folder, default=True),
            I("更换截图键…", self.start_learning),
            I("添加游戏…", self.start_adding),
            I("游戏名单", self._games_menu()),
            pystray.Menu.SEPARATOR,
            I("截图提示浮层", self._toggle("toast"), checked=lambda item: self.cfg["toast"]),
            I("截图声音", self._toggle("sound"), checked=lambda item: self.cfg["sound"]),
            I("同时复制到剪贴板", self._toggle("copy_to_clipboard"),
              checked=lambda item: self.cfg["copy_to_clipboard"]),
            I("DualSense 自动四声道", self._toggle_dualsense,
              checked=lambda item: self.cfg["dualsense_quad"]),
            I("暂停", self._toggle_pause, checked=lambda item: self.paused),
            pystray.Menu.SEPARATOR,
            I("退出", self._quit),
        )


def make_icon(state: str) -> Image.Image:
    """托盘图标：圆角方块 + 相机。灰=等待游戏，绿=工作中，橙=暂停。
    每种状态只画一次（每张截图、每次状态变化都要刷新托盘），每次返回一份拷贝，调用方改了也不影响缓存。"""
    return _draw_icon(state).copy()


@functools.lru_cache(maxsize=None)
def _draw_icon(state: str) -> Image.Image:
    bg = {"idle": (142, 142, 147), "active": (52, 199, 89), "paused": (255, 159, 10)}[state]
    s = 256
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 8, s - 8, s - 8], radius=56, fill=bg)
    d.rounded_rectangle([44, 84, 212, 196], radius=22, fill="white")
    d.rounded_rectangle([92, 60, 164, 96], radius=12, fill="white")
    d.ellipse([90, 102, 166, 178], fill=bg)
    d.ellipse([108, 120, 148, 160], fill="white")
    return img.resize((64, 64), Image.Resampling.LANCZOS)


# ---------------------------------------------------------------- 启动
def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, subprocess.list2cmdline(sys.argv[1:])
    else:
        exe = sys.executable
        params = subprocess.list2cmdline([os.path.abspath(sys.argv[0])] + sys.argv[1:])
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    return rc > 32


class AppendingLogHandler(RotatingFileHandler):
    """轮转失败时接着往原文件追加（docs/review/05-windows-verification.md P4）。另一个 GameSnap 开着日志时 Windows 不让改名，
    RotatingFileHandler 这时已经先删了旧的 .1，这一条日志也丢了，之后每一条都这样，直到对方退出。"""

    def doRollover(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None
        try:
            os.replace(self.baseFilename, f"{self.baseFilename}.1")   # 改名成功才换掉旧的 .1
        except OSError:
            pass   # 这里写不了日志；下一条再试
        self.stream = self._open()


def setup_logging(console: bool) -> None:
    """日志打不开（被别的程序禁写）时这次不写文件：不能因为日志让程序起不来，--launch 和单实例检查都在后面（05 P3）。"""
    handlers: list[logging.Handler] = []
    error = None
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        handlers.append(AppendingLogHandler(LOG_PATH, maxBytes=1_000_000, backupCount=1, encoding="utf-8"))
    except OSError as e:
        error = e
    if console:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers or [logging.NullHandler()],
                        format="%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s")
    logging.getLogger("comtypes").setLevel(logging.WARNING)
    if error is not None:
        log.warning("日志文件打不开，这次不写日志：%s（%s）", LOG_PATH, error)


def enable_crash_log():
    """原生代码崩溃（访问违例等）时，把各线程的 Python 调用栈追加写进 crash.log。
    注意：驱动里被自己处理掉的访问违例也会记一笔，看到记录要对照 gamesnap.log 里进程是否真的退出了。
    删不掉、打不开时不崩溃（第一个实例开着它时第二个实例删不掉，05 P3）：删不掉就接着写，打不开就这次不记，返回 None。"""
    try:
        if CRASH_LOG.exists() and CRASH_LOG.stat().st_size > 1_000_000:
            CRASH_LOG.unlink()
    except OSError as e:
        log.warning("crash.log 太大但删不掉，接着往里写：%s", e)
    try:
        f = open(CRASH_LOG, "a", encoding="utf-8")
        f.write(f"== {datetime.now():%Y-%m-%d %H:%M:%S} GameSnap 启动 pid {os.getpid()}\n")
        f.flush()
    except OSError as e:
        log.warning("crash.log 打不开，这次不记录崩溃调用栈：%s", e)
        return None
    faulthandler.enable(f, all_threads=True)
    return f


def message_box(text: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, text, "GameSnap", 0x40)


def confirm(text: str) -> bool:
    """「是 / 否」对话框，点「是」返回 True。"""
    MB_YESNO, MB_ICONQUESTION, MB_SETFOREGROUND, MB_TOPMOST, IDYES = 0x4, 0x20, 0x10000, 0x40000, 6
    return ctypes.windll.user32.MessageBoxW(
        None, text, "GameSnap", MB_YESNO | MB_ICONQUESTION | MB_SETFOREGROUND | MB_TOPMOST) == IDYES


def launch(path: str, params: str) -> None:
    """启动游戏启动器。在已提权的 GameSnap 里启动，启动器和它拉起的游戏就不会再弹 UAC。
    也可以是 steam://rungameid/… 这类链接：链接没有所在文件夹，不指定工作目录。"""
    workdir = os.path.dirname(path) if os.path.isfile(path) else None
    rc = ctypes.windll.shell32.ShellExecuteW(None, "open", path, params or None, workdir, 1)
    if rc <= 32:
        log.error("启动 %s 失败（ShellExecute 返回 %s）", path, rc)
        message_box(f"没能启动：\n{path}")
    else:
        log.info("已启动：%s %s", path, params)


def start_exit_watchdog(icon) -> None:
    """退出时托盘菜单开着的话，pystray 让消息循环退出的 WM_QUIT 会被菜单的模态循环吃掉，主线程在菜单关掉后一直等在
    GetMessage，走不到 main() 最后的 os._exit，进程就留下了（05 文档 P7）。到这一步该停的都停了：
    到时间消息循环还没退出，就在这里结束进程。只在 main() 里用，测试里建的 App 不会把测试进程结束掉。"""

    def force() -> None:
        log.warning("消息循环 %d 秒内没有退出（多半是退出时托盘菜单开着），直接结束进程", EXIT_WATCHDOG_SEC)
        try:
            icon.visible = False   # 否则托盘上留个空图标，鼠标移过去才消失
        except Exception:
            log.exception("去掉托盘图标时出错")
        logging.shutdown()
        os._exit(0)

    timer = threading.Timer(EXIT_WATCHDOG_SEC, force)
    timer.daemon = True
    timer.start()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--launch", help="同时启动这个程序或链接（如米哈游启动器、steam://rungameid/…）")
    ap.add_argument("--launch-args", default="", help="传给 --launch 程序的参数")
    ap.add_argument("--no-elevate", action="store_true", help="不请求管理员权限（调试用）")
    ap.add_argument("--console", action="store_true", help="日志同时输出到控制台")
    ap.add_argument("--config", help="使用指定的配置文件（测试用）")
    args = ap.parse_args()

    if not is_admin() and not args.no_elevate:
        if relaunch_as_admin():
            return
        message_box("没有获得管理员权限。\n原神等以管理员身份运行的游戏里，按键将不会触发截图。")

    setup_logging(args.console)
    crash_file = enable_crash_log()  # noqa: F841  文件要一直开着
    if args.launch:
        launch(args.launch, args.launch_args)

    inst = Instance(is_admin())
    if inst.should_take_over():
        log.info("正在运行的 GameSnap 没有管理员权限（在原神里收不到按键）：让它退出，由本实例接管")
        if not inst.take_over():
            return
    elif inst.already_running:
        # 正在运行的那个已经够用（启动器开着时它会一直等），本实例只负责拉起程序
        log.info("GameSnap 已在运行，本实例退出")
        if not args.launch:
            message_box("GameSnap 已经在运行了（看看任务栏右下角的托盘图标）。")
        return

    log.info("管理员权限：%s", inst.elevated)
    try:
        app = App(Config(Path(args.config)) if args.config else Config())
        # 退出信号在 Instance() 里就建好了；托盘进入消息循环、能正常退出之后才开始等它（02-findings M8）
        app.on_tray_ready = lambda: inst.serve(
            on_quit=lambda: app._auto_quit("由新启动的 GameSnap（管理员权限）接管"))
        app.on_quitting = lambda: start_exit_watchdog(app.icon)
        app.run()
    except Exception:
        log.exception("GameSnap 异常退出")
        raise
    # 直接结束进程，跳过解释器收尾：收尾会释放所有对象，WGC 会话一释放就等于关闭（见 capture.Capturer）
    logging.shutdown()
    os._exit(0)


if __name__ == "__main__":
    main()
