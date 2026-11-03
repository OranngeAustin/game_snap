"""Hold a hidden top-level window with the given title for a while, never pumping messages, and print
its handle. test_yuzu_naming.py and test_add_game.py read that title from another process.

usage: python fake_window.py <title> <seconds>
"""
import ctypes
import ctypes.wintypes as wt
import sys
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.CreateWindowExW.restype = wt.HWND
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
WS_OVERLAPPEDWINDOW = 0x00CF0000   # has a caption; without WS_VISIBLE it is never shown
hwnd = user32.CreateWindowExW(0, "STATIC", sys.argv[1], WS_OVERLAPPEDWINDOW, 0, 0, 200, 100,
                              None, None, None, None)
print(hwnd or 0, flush=True)
time.sleep(float(sys.argv[2]))
