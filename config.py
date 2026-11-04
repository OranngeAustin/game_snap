"""配置读写：%APPDATA%\\GameSnap\\config.json"""
from __future__ import annotations

import copy
import json
import logging
import math
import os
import shutil
import threading
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

APP_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "GameSnap"
CONFIG_PATH = APP_DIR / "config.json"
LOG_PATH = APP_DIR / "gamesnap.log"

VK_OEM_3 = 0xC0  # 美式键盘上的 ` ~ 键

DEFAULTS: dict = {
    # type: "key"（键盘，vk=虚拟键码）或 "mouse"（button=4 后退侧键 / 5 前进侧键）
    "hotkey": {"type": "key", "vk": VK_OEM_3},
    # 留空 = 「图片\GameShots」
    "save_dir": "",
    "copy_to_clipboard": True,
    "toast": True,
    "sound": False,
    # 插着 DualSense（USB）时把它的扬声器设为四声道、前后全音域，原神的手柄震动才有效（见 dualsense.py）
    "dualsense_quad": True,
    "poll_interval_sec": 2,
    # 生命周期：GameSnap 随游戏退出，不常驻
    "exit_grace_sec": 10,          # 玩过游戏后，游戏和启动器都关掉再等几秒才退出（防游戏自重启时误退）
    "wait_no_launcher_sec": 60,    # 启动后既没游戏也没启动器，等这么久就退出
    # 启动器进程名：它开着就一直等（可能在下载大版本更新，或者待会儿还要从它进游戏）
    "launchers": ["HYP.exe"],
    # 进程名（不区分大小写）→ 显示名 / 文件夹名
    "games": {
        "YuanShen.exe": "原神",
        "GenshinImpact.exe": "原神",
        "Genshin Impact Cloud Game.exe": "云原神",
        "StarRail.exe": "崩坏星穹铁道",
        "ZenlessZoneZero.exe": "绝区零",
        "BH3.exe": "崩坏3",
        # Switch 模拟器：玩游戏时截图按窗口标题里的游戏名分文件夹，停在游戏列表时用这个名字（见 main.emulator_game）
        "yuzu.exe": "yuzu",
    },
}


_BOOL_KEYS = ("copy_to_clipboard", "toast", "sound", "dualsense_quad")
_MIN_SEC = {"poll_interval_sec": 0.1, "exit_grace_sec": 0, "wait_no_launcher_sec": 0}   # 秒数的下限


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _valid_hotkey(v) -> bool:
    if not isinstance(v, dict):
        return False
    if v.get("type") == "key":
        return _is_int(v.get("vk")) and 1 <= v["vk"] <= 254
    if v.get("type") == "mouse":
        return _is_int(v.get("button")) and v["button"] in (4, 5)
    return False


def _checked(key: str, value):
    """返回 (要用的值, 问题)；值合法时问题为 None。不合法就用默认值；games / launchers 只去掉不对的那几项。"""
    default = DEFAULTS[key]
    if key in _BOOL_KEYS:
        if isinstance(value, bool):
            return value, None
        if _is_int(value) and value in (0, 1):   # 以前按真假值用，0 / 1 照旧
            return bool(value), None
        return default, "应为 true 或 false"
    if key in _MIN_SEC:
        low = _MIN_SEC[key]
        if (_is_int(value) or isinstance(value, float)) and math.isfinite(value) and value >= low:
            return value, None
        return default, f"应为不小于 {low} 的秒数"
    if key == "save_dir":
        return (value, None) if isinstance(value, str) else (default, "应为文件夹路径字符串，留空 = 图片\\GameShots")
    if key == "hotkey":
        return (value, None) if _valid_hotkey(value) else (default, "建议用托盘菜单「更换截图键…」改")
    if key == "launchers":
        if not isinstance(value, list):
            return default, "应为进程名列表"
        kept = [n for n in value if isinstance(n, str) and n]
        return kept, None if len(kept) == len(value) else "去掉了不是进程名的项"
    if key == "games":
        if not isinstance(value, dict):
            return default, '应为 {"进程名.exe": "文件夹名"}'
        kept = {k: v for k, v in value.items() if k and isinstance(v, str)}
        return kept, None if len(kept) == len(value) else "去掉了进程名为空或文件夹名不是字符串的项"
    return value, None


class Config:
    def __init__(self, path: Path = CONFIG_PATH) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.data = copy.deepcopy(DEFAULTS)
        if path.exists():
            try:
                # utf-8-sig：带 BOM 的也能读（PowerShell 5.1 的 Set-Content -Encoding UTF8、记事本「UTF-8 带 BOM」）
                loaded = json.loads(path.read_text(encoding="utf-8-sig"))
                if not isinstance(loaded, dict):
                    raise ValueError(f"顶层应该是 {{...}}，实际是 {type(loaded).__name__}")
                self.data.update(loaded)
            except Exception:
                log.exception("配置文件读取失败，使用默认配置：%s", path)
                self._keep_unreadable()
            else:
                self._check_values()
        else:
            self.save()

    def _keep_unreadable(self, kind: str = "unreadable", what: str = "读不出来的配置文件") -> None:
        """读不出来的配置文件先另存一份：之后任何 set() 都会用默认配置覆盖它，
        用户手改时多了个逗号，游戏名单、截图键就全没了（docs/review/02-findings.md H2）。"""
        backup = self.path.with_name(f"{self.path.stem}.{kind}_{datetime.now():%Y%m%d_%H%M%S}{self.path.suffix}")
        try:
            shutil.copy2(self.path, backup)
            log.warning("%s另存为 %s，改好后改回 %s 即可", what, backup, self.path.name)
        except OSError:
            log.exception("另存%s失败", what)

    def _check_values(self) -> None:
        """逐键检查类型和范围（docs/review/02-findings.md M5）。以前照单全收：轮询间隔写成 0 会忙等，
        写成 null 进程检测线程就死掉、不再自动退出，games 写成 null 一启动就崩。不合法的回退默认值并记日志；
        有改动时先把原文件另存一份，理由同 _keep_unreadable。"""
        changed = False
        for key in DEFAULTS:
            value, problem = _checked(key, self.data[key])
            if problem:
                log.warning("配置项 %s 的值 %r 不合法（%s），改用 %r", key, self.data[key], problem, value)
                changed = True
            self.data[key] = value
        if changed:
            self._keep_unreadable("invalid", "有不合法值的配置文件")

    def __getitem__(self, key: str):
        return self.data[key]

    def set(self, key: str, value) -> None:
        with self._lock:
            self.data[key] = value
        self.save()

    def update(self, key: str, change) -> None:
        """在锁里读出旧值、算出新值、写回，再保存。游戏名单要用它改：「添加游戏」和「移除游戏」以前各自
        读 → 改 → set()，同时发生时后写的会盖掉先写的（docs/review/02-findings.md L17）。change 要返回新对象，不要原地改。"""
        with self._lock:
            self.data[key] = change(self.data[key])
        self.save()

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            os.replace(tmp, self.path)

    def games_lower(self) -> dict[str, str]:
        return {k.lower(): v for k, v in self.data["games"].items()}

    def launchers_lower(self) -> set[str]:
        return {n.lower() for n in self.data["launchers"]}
