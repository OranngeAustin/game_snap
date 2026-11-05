"""config.Config 的读写：
1. 文件不存在：用默认配置，并写出一份；
2. 正常文件：覆盖到默认值上（浅合并），set() 写回后再读一样；带 BOM 的 UTF-8 也能读；
3. 读不出来的文件（JSON 写坏了、顶层不是对象）：用默认配置启动，但先把原文件另存一份，
   之后 set() 覆盖 config.json 时用户的游戏名单还在那份备份里；
4. 正常文件不产生备份；
5. 读取时文件被占用（05-windows-verification P2）：放开了就读到真的名单；一直读不了但另存上了，和第 3 项一样；
   读不了也另存不了（文件被独占），这次运行不写回：set() 返回 False、提示、内存里是新值、原文件一个字节不变。
   JSON 写坏了又另存不了时同样不写回。Windows 上再用真的独占（CreateFileW 共享模式 0）跑一遍。
只在 <run dir> 里读写。纯 Python，Windows 和 Linux 都能跑（真的独占只在 Windows 上）。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_config.py <run dir>
"""
import json
import shutil
import sys
import threading
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

print("== 4. file busy while reading")
REAL_TEXT = json.dumps({"games": {"Real.exe": "真名单"}, "sound": True}, ensure_ascii=False)
real_read_text, real_copy2 = Path.read_text, shutil.copy2


def real_file(name: str, text: str = REAL_TEXT) -> Path:
    d = RUN / name
    d.mkdir()
    p = d / "config.json"
    p.write_bytes(text.encode("utf-8"))
    return p


def busy_read(target: Path, times: int):
    """target 前 times 次读取抛 PermissionError，和被独占时一样；返回读取次数的计数。"""
    calls = [0]

    def fake(self, *a, **k):
        if self == target:
            calls[0] += 1
            if calls[0] <= times:
                raise PermissionError(13, "另一个程序正在使用此文件（假）")
        return real_read_text(self, *a, **k)
    Path.read_text = fake
    return calls


def no_copy(*a, **k):
    raise PermissionError(13, "另一个程序正在使用此文件（假）")


def check_read_only(name: str, c: config.Config) -> None:
    check(f"{name}: read_only", c.read_only is True)
    check(f"{name}: defaults used", c.data == config.DEFAULTS)
    errors: list[int] = []
    c.on_save_error = lambda: errors.append(1)
    saved_ok = c.set("toast", False)
    check(f"{name}: set() says not saved", saved_ok is False)
    check(f"{name}: new value in memory", c["toast"] is False)
    check(f"{name}: told the user once", errors == [1], str(errors))


p = real_file("read_busy_then_free")
calls = busy_read(p, 2)
c = config.Config(p)
Path.read_text = real_read_text
check("busy twice: real games loaded", c["games"] == {"Real.exe": "真名单"}, repr(c["games"]))
check("busy twice: read 3 times", calls[0] == 3, str(calls[0]))
check("busy twice: not read_only", c.read_only is False)
check("busy twice: no backup", backups(p.parent) == [], str(backups(p.parent)))
check("busy twice: set() saves", c.set("toast", False) is True and config.Config(p)["toast"] is False)

p = real_file("read_busy_backup_ok")
calls = busy_read(p, 10_000)
c = config.Config(p)
Path.read_text = real_read_text
check("busy, backup ok: gave up after 5 reads", calls[0] == 5, str(calls[0]))
check("busy, backup ok: defaults used", c.data == config.DEFAULTS)
check("busy, backup ok: not read_only", c.read_only is False)
saved = backups(p.parent)
check("busy, backup ok: one backup", len(saved) == 1 and saved[0].read_bytes() == REAL_TEXT.encode("utf-8"))

p = real_file("read_busy_no_backup")
busy_read(p, 10_000)
shutil.copy2 = no_copy
c = config.Config(p)
Path.read_text, shutil.copy2 = real_read_text, real_copy2
check_read_only("busy, no backup", c)
check("busy, no backup: file untouched", p.read_bytes() == REAL_TEXT.encode("utf-8"))
check("busy, no backup: no temp file left", backups(p.parent) == [], str(backups(p.parent)))

BROKEN_TEXT = '{"games": {"MyGame.exe": "我的游戏",}}'
p = real_file("bad_json_no_backup", BROKEN_TEXT)
shutil.copy2 = no_copy
c = config.Config(p)
shutil.copy2 = real_copy2
check_read_only("bad JSON, no backup", c)
check("bad JSON, no backup: file untouched", p.read_bytes() == BROKEN_TEXT.encode("utf-8"))

if sys.platform == "win32":
    print("== 5. really locked with share mode 0")
    import ctypes
    import ctypes.wintypes as wt
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wt.HANDLE
    k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE]
    k32.CloseHandle.argtypes = [wt.HANDLE]
    GENERIC_READ, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL = 0x80000000, 3, 0x80

    def lock(path: Path) -> wt.HANDLE:
        h = k32.CreateFileW(str(path), GENERIC_READ, 0, None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
        assert h not in (None, wt.HANDLE(-1).value), ctypes.get_last_error()
        return h

    p = real_file("locked_then_free")
    h = lock(p)
    t = threading.Timer(0.3, k32.CloseHandle, [h])
    t.start()
    c = config.Config(p)
    t.join()
    check("locked 0.3 s: real games loaded", c["games"] == {"Real.exe": "真名单"}, repr(c["games"]))
    check("locked 0.3 s: not read_only", c.read_only is False)
    check("locked 0.3 s: no backup", backups(p.parent) == [], str(backups(p.parent)))

    p = real_file("locked_all_along")
    h = lock(p)
    c = config.Config(p)
    check_read_only("locked", c)
    k32.CloseHandle(h)
    check("locked: file untouched after release", p.read_bytes() == REAL_TEXT.encode("utf-8"))
    check("locked: next start reads the real games", config.Config(p)["games"] == {"Real.exe": "真名单"})
else:
    print("SKIP  real lock: Windows only")

print("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
