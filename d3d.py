"""截图用到的最小一组 D3D11 / DXGI 调用（纯 ctypes，按虚表序号调用 COM 方法）。

只做四件事：找出驱动某块显示器的显卡、在它上面建 D3D11 设备、建 CPU 可读的暂存纹理、
把 GPU 纹理拷进暂存纹理再映射出来读。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import uuid

_dxgi = ctypes.WinDLL("dxgi")
_d3d11 = ctypes.WinDLL("d3d11")
_user32 = ctypes.WinDLL("user32")

_dxgi.CreateDXGIFactory1.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
_d3d11.D3D11CreateDevice.argtypes = [
    ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint,
    ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
_d3d11.D3D11CreateDevice.restype = ctypes.HRESULT

IID_IDXGIFactory1 = "{770aae78-f26f-4dba-a829-253c83d1b387}"
IID_IDXGIDevice = "{54ec77fa-1377-44e6-8c32-88fd5f44c84c}"
IID_ID3D11Texture2D = "{6f15aaf2-d208-4e89-9ab4-489535d34f9c}"
IID_ID3D11Multithread = "{9b7e4e00-342c-4106-a19f-4f2704f689f0}"

DXGI_ERROR_NOT_FOUND = 0x887A0002
D3D11_CREATE_DEVICE_BGRA_SUPPORT = 0x20
D3D11_SDK_VERSION = 7
D3D_FEATURE_LEVELS = (0xB000, 0xA100, 0xA000)   # 11_0, 10_1, 10_0
DXGI_FORMAT_B8G8R8A8_UNORM = 87
D3D11_USAGE_STAGING = 3
D3D11_CPU_ACCESS_READ = 0x20000
D3D11_MAP_READ = 1


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wt.DWORD), ("HighPart", wt.LONG)]

    def key(self) -> tuple[int, int]:
        return self.HighPart, self.LowPart


class DXGI_ADAPTER_DESC1(ctypes.Structure):
    _fields_ = [("Description", wt.WCHAR * 128), ("VendorId", wt.UINT), ("DeviceId", wt.UINT),
                ("SubSysId", wt.UINT), ("Revision", wt.UINT),
                ("DedicatedVideoMemory", ctypes.c_size_t), ("DedicatedSystemMemory", ctypes.c_size_t),
                ("SharedSystemMemory", ctypes.c_size_t), ("AdapterLuid", LUID), ("Flags", wt.UINT)]


class D3D11_TEXTURE2D_DESC(ctypes.Structure):
    _fields_ = [("Width", wt.UINT), ("Height", wt.UINT), ("MipLevels", wt.UINT),
                ("ArraySize", wt.UINT), ("Format", wt.UINT), ("SampleCount", wt.UINT),
                ("SampleQuality", wt.UINT), ("Usage", wt.UINT), ("BindFlags", wt.UINT),
                ("CPUAccessFlags", wt.UINT), ("MiscFlags", wt.UINT)]


class D3D11_MAPPED_SUBRESOURCE(ctypes.Structure):
    _fields_ = [("pData", ctypes.c_void_p), ("RowPitch", wt.UINT), ("DepthPitch", wt.UINT)]


# ---------------------------------------------------------------- COM 小工具
def _guid(text: str):
    return (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID(text).bytes_le)


def _method(obj: int, index: int, restype, *argtypes):
    """取 COM 对象虚表里第 index 个方法（0/1/2 是 QueryInterface/AddRef/Release）。"""
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    fn = proto(vtbl[index])
    return lambda *args: fn(obj, *args)


def release(obj: int | None) -> None:
    if obj:
        _method(obj, 2, wt.ULONG)()


def query_interface(obj: int, iid: str) -> int:
    out = ctypes.c_void_p()
    _method(obj, 0, ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(
        ctypes.byref(_guid(iid)), ctypes.byref(out))
    return out.value


# ---------------------------------------------------------------- 选显卡
class _PATH_INFO(ctypes.Structure):   # DISPLAYCONFIG_PATH_INFO（72 字节），只用 source 部分
    _fields_ = [("srcAdapter", LUID), ("srcId", wt.UINT), ("_rest", ctypes.c_byte * 60)]


class _SOURCE_NAME(ctypes.Structure):   # DISPLAYCONFIG_SOURCE_DEVICE_NAME
    _fields_ = [("type", ctypes.c_int), ("size", wt.UINT), ("adapter", LUID), ("id", wt.UINT),
                ("gdiName", wt.WCHAR * 32)]


def display_adapter_luid(device_name: str) -> tuple[int, int] | None:
    """驱动这块显示器（如 \\\\.\\DISPLAY1）的显卡 LUID。双显卡笔记本上通常是核显。"""
    n_path, n_mode = wt.UINT(), wt.UINT()
    if _user32.GetDisplayConfigBufferSizes(2, ctypes.byref(n_path), ctypes.byref(n_mode)):  # QDC_ONLY_ACTIVE_PATHS
        return None
    paths = (_PATH_INFO * n_path.value)()
    modes = (ctypes.c_byte * (64 * n_mode.value))()   # DISPLAYCONFIG_MODE_INFO 64 字节
    if _user32.QueryDisplayConfig(2, ctypes.byref(n_path), paths, ctypes.byref(n_mode), modes, None):
        return None
    for p in paths[: n_path.value]:
        name = _SOURCE_NAME(type=1, size=ctypes.sizeof(_SOURCE_NAME), adapter=p.srcAdapter, id=p.srcId)
        if _user32.DisplayConfigGetDeviceInfo(ctypes.byref(name)) == 0 and name.gdiName == device_name:
            return p.srcAdapter.key()
    return None


def find_adapter(luid: tuple[int, int] | None) -> tuple[int | None, str]:
    """按 LUID 找 DXGI 显卡，返回 (IDXGIAdapter1 指针, 名称)；找不到返回 (None, "")，用系统默认显卡。"""
    if luid is None:
        return None, ""
    factory = ctypes.c_void_p()
    if _dxgi.CreateDXGIFactory1(ctypes.byref(_guid(IID_IDXGIFactory1)), ctypes.byref(factory)) != 0:
        return None, ""
    try:
        enum = _method(factory.value, 12, ctypes.c_long, wt.UINT, ctypes.POINTER(ctypes.c_void_p))
        i = 0
        while True:
            adapter = ctypes.c_void_p()
            if enum(i, ctypes.byref(adapter)) != 0:   # DXGI_ERROR_NOT_FOUND：枚举完了
                return None, ""
            desc = DXGI_ADAPTER_DESC1()
            _method(adapter.value, 10, ctypes.HRESULT, ctypes.POINTER(DXGI_ADAPTER_DESC1))(
                ctypes.byref(desc))
            if desc.AdapterLuid.key() == luid:
                return adapter.value, desc.Description
            release(adapter.value)
            i += 1
    finally:
        release(factory.value)


# ---------------------------------------------------------------- 设备与读回
class Device:
    """一块显卡上的 D3D11 设备 + 立即上下文 + 一张按需建的暂存纹理。"""

    def __init__(self, adapter: int | None) -> None:
        levels = (wt.UINT * len(D3D_FEATURE_LEVELS))(*D3D_FEATURE_LEVELS)
        dev, ctx = ctypes.c_void_p(), ctypes.c_void_p()
        # 指定显卡时驱动类型必须是 UNKNOWN(0)；用默认显卡时是 HARDWARE(1)
        _d3d11.D3D11CreateDevice(adapter, 0 if adapter else 1, None, D3D11_CREATE_DEVICE_BGRA_SUPPORT,
                                 levels, len(levels), D3D11_SDK_VERSION,
                                 ctypes.byref(dev), None, ctypes.byref(ctx))
        self.device, self.context = dev.value, ctx.value
        # WGC 的帧池会在它自己的线程里用这个设备，打开多线程保护
        mt = query_interface(self.context, IID_ID3D11Multithread)
        _method(mt, 5, wt.BOOL, wt.BOOL)(True)   # SetMultithreadProtected
        release(mt)
        self._staging = 0
        self._staging_size = (0, 0)

    def dxgi_device(self) -> int:
        """IDXGIDevice 指针（调用方负责 release）。"""
        return query_interface(self.device, IID_IDXGIDevice)

    def read_texture(self, texture: int, width: int, height: int, consume) -> None:
        """把 GPU 纹理拷进暂存纹理并映射，调用 consume(数据地址, 每行字节数)；返回前解除映射。"""
        if self._staging_size != (width, height):
            release(self._staging)
            desc = D3D11_TEXTURE2D_DESC(Width=width, Height=height, MipLevels=1, ArraySize=1,
                                        Format=DXGI_FORMAT_B8G8R8A8_UNORM, SampleCount=1,
                                        Usage=D3D11_USAGE_STAGING, CPUAccessFlags=D3D11_CPU_ACCESS_READ)
            out = ctypes.c_void_p()
            _method(self.device, 5, ctypes.HRESULT, ctypes.POINTER(D3D11_TEXTURE2D_DESC),
                    ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(
                ctypes.byref(desc), None, ctypes.byref(out))
            self._staging, self._staging_size = out.value, (width, height)
        _method(self.context, 47, None, ctypes.c_void_p, ctypes.c_void_p)(self._staging, texture)
        mapped = D3D11_MAPPED_SUBRESOURCE()
        _method(self.context, 14, ctypes.HRESULT, ctypes.c_void_p, wt.UINT, wt.UINT, wt.UINT,
                ctypes.POINTER(D3D11_MAPPED_SUBRESOURCE))(
            self._staging, 0, D3D11_MAP_READ, 0, ctypes.byref(mapped))
        try:
            consume(mapped.pData, mapped.RowPitch)
        finally:
            _method(self.context, 15, None, ctypes.c_void_p, wt.UINT)(self._staging, 0)

    def release(self) -> None:
        release(self._staging)
        release(self.context)
        release(self.device)
        self._staging = self.context = self.device = 0
        self._staging_size = (0, 0)
