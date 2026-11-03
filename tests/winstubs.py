"""在非 Windows（claude.ai 云端会话的 Linux 容器）上把 Windows 专属的东西换成桩，让项目模块能 import，
好测其中只用 PIL / 纯 Python 的逻辑。在 Windows 上什么也不做，测的就是真模块。

用法：在 import 任何项目模块之前

    import winstubs; winstubs.install()

桩只保证「import 不报错」：DLL 是 MagicMock，调用什么都返回 MagicMock，不会真的做任何事。
所以用了桩的测试只能测纯逻辑；碰到 Win32 / WinRT / D3D 的部分要回 Windows 跑。
"""
from __future__ import annotations

import os
import sys
import types

ON_WINDOWS = sys.platform == "win32"


def install() -> bool:
    """装上桩；返回是否真的装了（Windows 上返回 False）。重复调用无妨。"""
    if ON_WINDOWS:
        return False
    import ctypes
    from unittest import mock

    os.environ.setdefault("PYSTRAY_BACKEND", "dummy")   # 否则 import pystray 会去连 X 显示器
    if not hasattr(ctypes, "WinDLL"):
        ctypes.WinDLL = lambda *a, **k: mock.MagicMock(name=f"WinDLL({a[0] if a else ''})")
        ctypes.windll = mock.MagicMock(name="windll")
        ctypes.WINFUNCTYPE = ctypes.CFUNCTYPE
        ctypes.HRESULT = ctypes.c_long
        ctypes.WinError = lambda code=None, descr=None: OSError(code, descr or "WinError（桩）")
        ctypes.get_last_error = lambda: 0
        ctypes.set_last_error = lambda value: 0
        ctypes.FormatError = lambda code=None: "（桩）"

    if "winsound" not in sys.modules:
        ws = types.ModuleType("winsound")
        ws.MB_OK, ws.MB_ICONHAND = 0, 0x10
        ws.MessageBeep = lambda kind=0: None
        sys.modules["winsound"] = ws

    if "winreg" not in sys.modules:
        wr = types.ModuleType("winreg")
        wr.HKEY_LOCAL_MACHINE = 0x80000002

        def _no_registry(*a, **k):
            raise OSError("没有注册表（桩）")

        wr.OpenKey = wr.QueryValueEx = wr.EnumKey = _no_registry
        sys.modules["winreg"] = wr
    return True
