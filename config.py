"""配置读写：%APPDATA%\\GameSnap\\config.json"""
from __future__ import annotations

import copy
import json
import logging
import os
import threading
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


class Config:
    def __init__(self, path: Path = CONFIG_PATH) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.data = copy.deepcopy(DEFAULTS)
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                self.data.update(loaded)
            except Exception:
                log.exception("配置文件读取失败，使用默认配置：%s", path)
        else:
            self.save()

    def __getitem__(self, key: str):
        return self.data[key]

    def set(self, key: str, value) -> None:
        with self._lock:
            self.data[key] = value
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
