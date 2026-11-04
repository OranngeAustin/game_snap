"""截图键的显示名：Insert / Delete / Home / End / PgUp / PgDn / 方向键不再显示成小键盘键（02-findings L4）。

key_name 以前用 MapVirtualKeyW(vk, MAPVK_VK_TO_VSC) 拿扫描码，丢了「扩展键」标志，GetKeyNameTextW 就把 Insert 说成
「Num 0」、↑ 说成「Num 8」（只影响托盘和提示里显示的名字）。这里把 user32 换成按 Windows 的规则回答的假实现
（MAPVK_VK_TO_VSC_EX 对扩展键返回 0xE0xx；GetKeyNameTextW 看 lParam 第 24 位区分扩展键），检查：
1. 那 10 个扩展键显示成自己的名字；2. 小键盘数字、F24、可打印字符、鼠标侧键的显示不变。
纯 Python，Windows 和 Linux（tests/winstubs.py 桩）都能跑。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_key_name.py
"""
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


# vk → (扫描码, 是否扩展键, 扩展时的名字, 不带扩展标志时的名字)
KEYS = {
    0x2D: (0x52, True, "Insert", "Num 0"), 0x2E: (0x53, True, "Delete", "Num Del"),
    0x24: (0x47, True, "Home", "Num 7"), 0x23: (0x4F, True, "End", "Num 1"),
    0x21: (0x49, True, "Page Up", "Num 9"), 0x22: (0x51, True, "Page Down", "Num 3"),
    0x25: (0x4B, True, "Left", "Num 4"), 0x26: (0x48, True, "Up", "Num 8"),
    0x27: (0x4D, True, "Right", "Num 6"), 0x28: (0x50, True, "Down", "Num 2"),
    0x60: (0x52, False, "", "Num 0"), 0x68: (0x48, False, "", "Num 8"), 0x87: (0x76, False, "", "F24"),
}


class FakeUser32:
    def MapVirtualKeyW(self, vk, kind):
        if kind == 2:   # MAPVK_VK_TO_CHAR
            return ord("`") if vk == 0xC0 else 0
        scan, ext = KEYS.get(vk, (0, False))[:2]
        return (0xE000 | scan) if kind == 4 and ext else scan   # 4 = MAPVK_VK_TO_VSC_EX

    def GetKeyNameTextW(self, lparam, buf, size):
        scan, ext = (lparam >> 16) & 0xFF, bool(lparam & (1 << 24))
        for _vk, (s, is_ext, ext_name, plain_name) in KEYS.items():
            if s == scan and (is_ext or not ext):
                name = ext_name if ext else plain_name
                if name:
                    buf.value = name
                    return len(name)
        return 0


hotkey.user32 = FakeUser32()
print("== 1. 扩展键")
for vk, (_, ext, name, _plain) in KEYS.items():
    if ext:
        check(f"vk {vk:#04x}", hotkey.key_name({"type": "key", "vk": vk}), name)
print("== 2. 其他的不变")
check("小键盘 0", hotkey.key_name({"type": "key", "vk": 0x60}), "Num 0")
check("小键盘 8", hotkey.key_name({"type": "key", "vk": 0x68}), "Num 8")
check("F24", hotkey.key_name({"type": "key", "vk": 0x87}), "F24")
check("可打印字符", hotkey.key_name({"type": "key", "vk": 0xC0}), "`")
check("鼠标侧键", hotkey.key_name({"type": "mouse", "button": 4}), "鼠标侧键（后退）")

print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
