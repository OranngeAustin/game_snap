"""config.Config 的读写：
1. 文件不存在：用默认配置，并写出一份；
2. 正常文件：覆盖到默认值上（浅合并），set() 写回后再读一样；带 BOM 的 UTF-8 也能读；
3. 读不出来的文件（JSON 写坏了、顶层不是对象）：用默认配置启动，但先把原文件另存一份，
   之后 set() 覆盖 config.json 时用户的游戏名单还在那份备份里；
4. 正常文件不产生备份。
只在 <run dir> 里读写。纯 Python，Windows 和 Linux 都能跑。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_config.py <run dir>
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT, RUN = HERE.parent, Path(sys.argv[1])
RUN.mkdir(parents=True, exist_ok=False)
sys.path.insert(0, str(PROJECT))
import config  # noqa: E402

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(label)


def backups(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.name != "config.json" and p.name.startswith("config"))


print("== 1. no file")
d1 = RUN / "missing"
c = config.Config(d1 / "config.json")
check("defaults used", c.data == config.DEFAULTS)
check("file written", (d1 / "config.json").is_file())
check("written file is the defaults",
      json.loads((d1 / "config.json").read_text(encoding="utf-8")) == config.DEFAULTS)
check("no backup", backups(d1) == [], str(backups(d1)))

print("== 2. valid file")
d2 = RUN / "valid"
d2.mkdir()
p2 = d2 / "config.json"
p2.write_text(json.dumps({"games": {"MyGame.exe": "我的游戏"}, "sound": True}, ensure_ascii=False),
              encoding="utf-8")
c = config.Config(p2)
check("games replaced (shallow merge)", c["games"] == {"MyGame.exe": "我的游戏"}, repr(c["games"]))
check("other keys keep defaults", c["hotkey"] == config.DEFAULTS["hotkey"] and c["sound"] is True)
c.set("toast", False)
again = config.Config(p2)
check("set() round-trips", again["toast"] is False and again["games"] == {"MyGame.exe": "我的游戏"})
check("games_lower / launchers_lower", again.games_lower() == {"mygame.exe": "我的游戏"}
      and again.launchers_lower() == {"hyp.exe"})
check("no backup", backups(d2) == [], str(backups(d2)))

print("== 2b. valid file saved as UTF-8 with BOM")
d2b = RUN / "bom"
d2b.mkdir()
p2b = d2b / "config.json"
p2b.write_text(json.dumps({"games": {"MyGame.exe": "我的游戏"}}, ensure_ascii=False), encoding="utf-8-sig")
c = config.Config(p2b)
check("BOM file read", c["games"] == {"MyGame.exe": "我的游戏"}, repr(c["games"]))
check("no backup", backups(d2b) == [], str(backups(d2b)))

print("== 3. unreadable file")
BROKEN = {
    "trailing_comma": '{"games": {"MyGame.exe": "我的游戏",}, "sound": true}',
    "not_an_object": '[["games", {"MyGame.exe": "我的游戏"}]]',
    "not_json": "games = MyGame.exe",
}
for name, text in BROKEN.items():
    d3 = RUN / name
    d3.mkdir()
    p3 = d3 / "config.json"
    p3.write_text(text, encoding="utf-8")
    c = config.Config(p3)
    check(f"{name}: defaults used", c.data == config.DEFAULTS)
    saved = backups(d3)
    check(f"{name}: one backup", len(saved) == 1, str([p.name for p in saved]))
    if saved:
        check(f"{name}: backup is the original bytes", saved[0].read_text(encoding="utf-8") == text)
    c.set("toast", False)   # 托盘里切一下开关：config.json 被默认配置覆盖
    check(f"{name}: config.json readable again", config.Config(p3)["toast"] is False)
    check(f"{name}: user's games still in the backup",
          bool(saved) and "MyGame.exe" in saved[0].read_text(encoding="utf-8"))

print("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
