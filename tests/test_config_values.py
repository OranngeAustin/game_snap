"""config.json 里的值类型不对、超出范围时的处理（02-findings M5）。

以前 JSON 能解析就照单全收：poll_interval_sec 写成 0 会忙等占满一个核；写成 null 或 "2s"，进程检测线程第一次轮询后
就死掉，再也不会自动退出；games 写成 null，一启动就崩。现在：
1. 每个不合法的值都回退成默认值，并记一条日志写明是哪个键；其他合法的键原样保留；
2. games / launchers 只是个别项不对时，只去掉那几项，其余保留；
3. 有值被改掉时，先把原文件另存一份（之后 set() 会用改过的配置覆盖 config.json），和读不出来时的做法一样；
4. 全部合法（含边界值）的文件不产生备份、一个值都不改；int 0 / 1 当成 false / true，和以前的行为一样。
只在 <run dir> 里读写。纯 Python，Windows 和 Linux 都能跑。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_config_values.py <run dir>
"""
import json
import logging
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT, RUN = HERE.parent, Path(sys.argv[1])
RUN.mkdir(parents=True, exist_ok=False)
sys.path.insert(0, str(PROJECT))
import config  # noqa: E402

failures: list[str] = []
logs: list[str] = []
D = config.DEFAULTS


class ListHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        logs.append(record.getMessage())


logging.getLogger().addHandler(ListHandler())
logging.getLogger().setLevel(logging.INFO)


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {got!r}" + ("" if ok else f"  (want {want!r})"))
    if not ok:
        failures.append(label)


def backups(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.name != "config.json" and p.name.startswith("config"))


def load(name: str, text: str) -> config.Config:
    folder = RUN / name
    folder.mkdir()
    (folder / "config.json").write_text(text, encoding="utf-8")
    logs.clear()
    return config.Config(folder / "config.json")


print("== 1. 不合法的值回退默认值，其他键保留")
# (键, 写进文件的 JSON 片段, 读出来应该是什么)
BAD = [
    ("poll_interval_sec", "0", D["poll_interval_sec"]),
    ("poll_interval_sec", "-1", D["poll_interval_sec"]),
    ("poll_interval_sec", "0.01", D["poll_interval_sec"]),
    ("poll_interval_sec", "null", D["poll_interval_sec"]),
    ("poll_interval_sec", '"2s"', D["poll_interval_sec"]),
    ("poll_interval_sec", "true", D["poll_interval_sec"]),
    ("poll_interval_sec", "NaN", D["poll_interval_sec"]),
    ("poll_interval_sec", "Infinity", D["poll_interval_sec"]),
    ("exit_grace_sec", "null", D["exit_grace_sec"]),
    ("exit_grace_sec", "-5", D["exit_grace_sec"]),
    ("exit_grace_sec", '"10"', D["exit_grace_sec"]),
    ("wait_no_launcher_sec", "[]", D["wait_no_launcher_sec"]),
    ("games", "null", D["games"]),
    ("games", '["MyGame.exe"]', D["games"]),
    ("games", '"MyGame.exe"', D["games"]),
    ("launchers", '"HYP.exe"', D["launchers"]),
    ("launchers", "null", D["launchers"]),
    ("hotkey", "null", D["hotkey"]),
    ("hotkey", '{"type": "key", "vk": "C0"}', D["hotkey"]),
    ("hotkey", '{"type": "key", "vk": 0}', D["hotkey"]),
    ("hotkey", '{"type": "key", "vk": 300}', D["hotkey"]),
    ("hotkey", '{"type": "mouse", "button": 3}', D["hotkey"]),
    ("hotkey", '{"type": "pad", "vk": 192}', D["hotkey"]),
    ("hotkey", '"`"', D["hotkey"]),
    ("save_dir", "null", D["save_dir"]),
    ("save_dir", "5", D["save_dir"]),
    ("toast", '"yes"', D["toast"]),
    ("sound", "null", D["sound"]),
    ("copy_to_clipboard", "2", D["copy_to_clipboard"]),
    ("dualsense_quad", '"false"', D["dualsense_quad"]),
]
for i, (key, raw, want) in enumerate(BAD):
    other = "sound" if key != "sound" else "toast"   # 另一个合法的、非默认的键：应原样保留
    other_value = not D[other]
    text = f'{{"{key}": {raw}, "{other}": {json.dumps(other_value)}, "games_extra": 1}}'
    c = load(f"bad_{i:02d}_{key}", text)
    check(f"{key}={raw} → 默认值", c[key], want)
    check(f"{key}={raw}：别的键保留", c[other], other_value)
    check(f"{key}={raw}：日志写明了键名", any(key in s for s in logs), True)
    saved = backups(RUN / f"bad_{i:02d}_{key}")
    check(f"{key}={raw}：原文件另存了一份", [p.read_text(encoding="utf-8") for p in saved], [text])

print("== 2. games / launchers 只去掉不对的那几项")
c = load("partial", json.dumps({
    "games": {"MyGame.exe": "我的游戏", "Bad.exe": 3, "": "空进程名", "Null.exe": None, "Other.exe": "别的"},
    "launchers": ["HYP.exe", 5, "", None, "Steam.exe"],
}, ensure_ascii=False))
check("games 保留合法项", c["games"], {"MyGame.exe": "我的游戏", "Other.exe": "别的"})
check("launchers 保留合法项", c["launchers"], ["HYP.exe", "Steam.exe"])
check("games_lower 能用", c.games_lower(), {"mygame.exe": "我的游戏", "other.exe": "别的"})
check("launchers_lower 能用", c.launchers_lower(), {"hyp.exe", "steam.exe"})
check("原文件另存了一份", len(backups(RUN / "partial")), 1)

print("== 3. 改掉的值之后被 set() 写回，原来的还在备份里")
c = load("then_set", '{"games": {"MyGame.exe": "我的游戏"}, "poll_interval_sec": 0}')
c.set("toast", False)
on_disk = json.loads((RUN / "then_set" / "config.json").read_text(encoding="utf-8"))
check("config.json 写回的是合法值", on_disk["poll_interval_sec"], D["poll_interval_sec"])
check("用户的游戏名单还在 config.json 里", on_disk["games"], {"MyGame.exe": "我的游戏"})
saved = backups(RUN / "then_set")
check("备份是原文件", [json.loads(p.read_text(encoding="utf-8"))["poll_interval_sec"] for p in saved], [0])

print("== 4. 全部合法（含边界值）：一个值都不改、不产生备份")
GOOD = {
    "hotkey": {"type": "mouse", "button": 4}, "save_dir": r"D:\Shots", "copy_to_clipboard": False,
    "toast": False, "sound": True, "dualsense_quad": False, "poll_interval_sec": 0.5,
    "exit_grace_sec": 0, "wait_no_launcher_sec": 1.5, "launchers": [], "games": {},
}
c = load("good", json.dumps(GOOD))
check("全部原样", {k: c[k] for k in GOOD}, GOOD)
check("没有备份", backups(RUN / "good"), [])
check("没有警告", [s for s in logs if "不合法" in s], [])
c = load("good_key", json.dumps({"hotkey": {"type": "key", "vk": 0x87}, "poll_interval_sec": 3}))
check("键盘截图键原样", c["hotkey"], {"type": "key", "vk": 0x87})
check("整数轮询间隔原样", c["poll_interval_sec"], 3)
check("没有备份（key）", backups(RUN / "good_key"), [])
c = load("int_bool", json.dumps({"toast": 0, "sound": 1}))
check("toast: 0 当成 false", c["toast"] is False, True)
check("sound: 1 当成 true", c["sound"] is True, True)
check("没有备份（0 / 1）", backups(RUN / "int_bool"), [])
c = load("defaults", json.dumps(D, ensure_ascii=False))
check("默认配置本身合法", c.data, D)
check("没有备份（默认配置）", backups(RUN / "defaults"), [])

print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
