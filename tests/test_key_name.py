"""截图键的显示名：Insert / Delete / Home / End / PgUp / PgDn / 方向键不再显示成小键盘键（02-findings L4、05-windows-verification P6）。

GetKeyNameTextW 靠 lParam 第 24 位（扩展键）区分 Home 和「Num 7」。L4 以为 MapVirtualKeyW(vk, MAPVK_VK_TO_VSC_EX) 会对这些键
返回 0xE0xx，但真机（键盘布局 0x8040804）返回的是不带前缀的 0x47，所以 L4 的修复没生效，而当时的假 user32 也这样假设，测试照样通过。
现在假 user32 的回答抄自真机（2026-11-04 直接调 API 查的），检查：
1. 那 10 个键显示成自己的名字；Pause、Num Lock、Print Screen 不再张冠李戴；
2. 靠 0xE0 前缀的键（Left Windows、Right Ctrl）照样对；
3. F1–F12、主键盘数字、可打印字符、鼠标侧键的显示不变；
4. 系统给不出能用的名字的键用自己写的名字：F13–F24（以前 VK 0x7c 这样）、小键盘数字和运算符（以前和主键盘同名）、
   媒体键和浏览器键（以前静音显示成 D）；
5. 只在 Windows 上：调真实的 API 再查一遍，不显示成错的名字。名字随系统语言变，英文名字的系统才比对全名。
纯 Python，Windows 和 Linux（tests/winstubs.py 桩）都能跑，第 5 项只在 Windows 上跑。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_key_name.py
"""
import ctypes
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import winstubs  # noqa: E402

winstubs.install()
import hotkey  # noqa: E402

failures: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {got!r}" + ("" if ok else f"  (want {want!r})"))
    if not ok:
        failures.append(label)


# MAPVK_VK_TO_VSC_EX 的真实返回值
VSC_EX = {
    0x21: 0x49, 0x22: 0x51, 0x23: 0x4F, 0x24: 0x47, 0x25: 0x4B, 0x26: 0x48, 0x27: 0x4D, 0x28: 0x50, 0x2D: 0x52, 0x2E: 0x53,
    0x13: 0xE11D, 0x2C: 0x54, 0x90: 0x45, 0x5B: 0xE05B, 0xA2: 0x1D, 0xA3: 0xE01D, 0x60: 0x52, 0x68: 0x48, 0x70: 0x3B,
    0x87: 0x76, 0xC0: 0x29, 0x30: 0x0B, 0x7C: 0x64, 0xAD: 0xE020, 0xB3: 0xE022,
}
# MAPVK_VK_TO_CHAR 的真实返回值：小键盘数字也有字符；没列出的是 0
CHARS = {0xC0: ord("`"), 0x60: ord("0"), 0x68: ord("8"), 0x30: ord("0"), 0x6A: ord("*"), 0x6F: ord("/")}
# GetKeyNameTextW：(扫描码, 第 24 位) → 名字；没列出的返回 0（如 F24 的 0x76）
NAMES = {
    (0x49, True): "Page Up", (0x49, False): "Num 9", (0x51, True): "Page Down", (0x51, False): "Num 3",
    (0x4F, True): "End", (0x4F, False): "Num 1", (0x47, True): "Home", (0x47, False): "Num 7",
    (0x4B, True): "Left", (0x4B, False): "Num 4", (0x48, True): "Up", (0x48, False): "Num 8",
    (0x4D, True): "Right", (0x4D, False): "Num 6", (0x50, True): "Down", (0x50, False): "Num 2",
    (0x52, True): "Insert", (0x52, False): "Num 0", (0x53, True): "Delete", (0x53, False): "Num Del",
    (0x45, False): "Pause", (0x45, True): "Num Lock", (0x37, True): "Prnt Scrn", (0x37, False): "Num *",
    (0x54, False): "Sys Req", (0x1D, False): "Ctrl", (0x1D, True): "Right Ctrl", (0x5B, True): "Left Windows",
    (0x3B, False): "F1", (0x29, False): "`", (0x20, True): "D", (0x22, True): "G",   # 静音、播放暂停的扫描码是字母键的
}
# vk → (应该显示的名字, 修之前错显示成的那个键的（扫描码, 第 24 位）)
FIXED = {
    0x21: ("Page Up", (0x49, False)), 0x22: ("Page Down", (0x51, False)), 0x23: ("End", (0x4F, False)),
    0x24: ("Home", (0x47, False)), 0x25: ("Left", (0x4B, False)), 0x26: ("Up", (0x48, False)),
    0x27: ("Right", (0x4D, False)), 0x28: ("Down", (0x50, False)), 0x2D: ("Insert", (0x52, False)),
    0x2E: ("Delete", (0x53, False)), 0x13: ("Pause", (0x1D, True)), 0x90: ("Num Lock", (0x45, False)),
    0x2C: ("Prnt Scrn", (0x54, False)),
}
EXTENDED_BY_PREFIX = {0x5B: "Left Windows", 0xA3: "Right Ctrl"}
OWN_NAMES = {
    **{0x7C + i: f"F{13 + i}" for i in range(12)},
    **{0x60 + i: f"Num {i}" for i in range(10)},
    0x6A: "Num *", 0x6B: "Num +", 0x6D: "Num -", 0x6E: "Num .", 0x6F: "Num /",
    0xA6: "浏览器后退", 0xA7: "浏览器前进", 0xA8: "浏览器刷新", 0xA9: "浏览器停止", 0xAA: "浏览器搜索", 0xAB: "浏览器收藏",
    0xAC: "浏览器主页", 0xAD: "静音键", 0xAE: "音量减", 0xAF: "音量加", 0xB0: "下一首", 0xB1: "上一首", 0xB2: "停止播放",
    0xB3: "播放 / 暂停", 0xB4: "邮件键", 0xB5: "媒体选择键", 0xB6: "应用键 1", 0xB7: "应用键 2",
}


class FakeUser32:
    def MapVirtualKeyW(self, vk, kind):
        return CHARS.get(vk, 0) if kind == 2 else VSC_EX.get(vk, 0)   # 2 = MAPVK_VK_TO_CHAR

    def GetKeyNameTextW(self, lparam, buf, size):
        name = NAMES.get(((lparam >> 16) & 0xFF, bool(lparam & (1 << 24))), "")
        buf.value = name
        return len(name)


real_user32 = hotkey.user32
hotkey.user32 = FakeUser32()
print("== 1. 那 10 个键和 Pause、Num Lock、Print Screen")
for vk, (name, _wrong) in FIXED.items():
    check(f"vk {vk:#04x}", hotkey.key_name({"type": "key", "vk": vk}), name)
print("== 2. 靠 0xE0 前缀的键")
for vk, name in EXTENDED_BY_PREFIX.items():
    check(f"vk {vk:#04x}", hotkey.key_name({"type": "key", "vk": vk}), name)
check("Left Ctrl 不是 Right Ctrl", hotkey.key_name({"type": "key", "vk": 0xA2}), "Ctrl")
print("== 3. 其他的不变")
check("主键盘 0", hotkey.key_name({"type": "key", "vk": 0x30}), "0")
check("F1", hotkey.key_name({"type": "key", "vk": 0x70}), "F1")
check("可打印字符", hotkey.key_name({"type": "key", "vk": 0xC0}), "`")
check("鼠标侧键", hotkey.key_name({"type": "mouse", "button": 4}), "鼠标侧键（后退）")
check("不认识的键", hotkey.key_name({"type": "key", "vk": 0xE9}), "VK 0xe9")
print("== 4. 系统给不出能用的名字的键")
for vk, name in OWN_NAMES.items():
    check(f"vk {vk:#04x}", hotkey.key_name({"type": "key", "vk": vk}), name)

if sys.platform == "win32":
    print("== 5. 真实的 API")
    hotkey.user32 = real_user32

    def api_name(scan: int, ext: bool) -> str:
        buf = ctypes.create_unicode_buffer(64)
        real_user32.GetKeyNameTextW(scan << 16 | (1 << 24 if ext else 0), buf, 64)
        return buf.value

    english = api_name(0x47, True) == "Home"
    print(f"      Home 的扩展键名字是 {api_name(0x47, True)!r}：" + ("比对全名" if english else "不是英文，不比对全名"))
    for vk, (name, wrong) in FIXED.items():
        got = hotkey.key_name({"type": "key", "vk": vk})
        check(f"真机 vk {vk:#04x} 不是「{api_name(*wrong)}」", got != api_name(*wrong) and not got.startswith("VK "), True)
        if english:
            check(f"真机 vk {vk:#04x}", got, name)
    for vk, name in EXTENDED_BY_PREFIX.items():
        if english:
            check(f"真机 vk {vk:#04x}", hotkey.key_name({"type": "key", "vk": vk}), name)
    for vk, name in OWN_NAMES.items():
        check(f"真机 vk {vk:#04x}", hotkey.key_name({"type": "key", "vk": vk}), name)
    check("真机 小键盘 0 和主键盘 0 不同名", hotkey.key_name({"type": "key", "vk": 0x60}) !=
          hotkey.key_name({"type": "key", "vk": 0x30}), True)
    check("真机 主键盘 0 还是 0", hotkey.key_name({"type": "key", "vk": 0x30}), "0")
    check("真机 F12 系统给的名字", hotkey.key_name({"type": "key", "vk": 0x7B}), "F12")
else:
    print("SKIP  真实的 API：只在 Windows 上跑")

print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
