"""D3D 初始化的异常路径上不漏 COM 对象（02-findings L6）。

find_adapter 枚举显卡时 GetDesc1 抛错，当前这块显卡的 IDXGIAdapter1 不释放；Device.__init__ 里取 ID3D11Multithread 或
SetMultithreadProtected 抛错时，刚建好的 device / context 不释放。这里把 DXGI / D3D11 的入口和 COM 方法换成假的（不碰显卡），
检查异常照常抛出，并且该释放的都释放了；正常路径不多释放。
纯 Python，Windows 和 Linux（tests/winstubs.py 桩）都能跑。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_d3d_release.py
"""
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import winstubs  # noqa: E402

winstubs.install()
import d3d  # noqa: E402

failures: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {got!r}" + ("" if ok else f"  (want {want!r})"))
    if not ok:
        failures.append(label)


FACTORY, ADAPTER, DEV, CTX, MT = 0xF0, 0xA0, 0xD0, 0xC0, 0xE0
released: list[int] = []
fail = {"desc": False, "qi": False, "set_mt": False}
d3d.release = lambda p: released.append(p) if p else None


def create_factory(iid, out):
    out._obj.value = FACTORY
    return 0


def fake_method(ptr, index, *types_):
    if ptr == FACTORY and index == 12:   # EnumAdapters1
        def enum(i, out):
            if i:
                return 1   # DXGI_ERROR_NOT_FOUND
            out._obj.value = ADAPTER
            return 0
        return enum
    if ptr == ADAPTER and index == 10:   # GetDesc1
        def get_desc(desc):
            if fail["desc"]:
                raise OSError("GetDesc1 失败（假）")
            return 0
        return get_desc
    if ptr == MT and index == 5:   # SetMultithreadProtected
        def set_mt(on):
            if fail["set_mt"]:
                raise OSError("SetMultithreadProtected 失败（假）")
            return 1
        return set_mt
    return lambda *a: 0


def create_device(*a):
    a[7]._obj.value, a[9]._obj.value = DEV, CTX
    return 0


def query_interface(obj, iid):
    if fail["qi"]:
        raise OSError("QueryInterface 失败（假）")
    return MT


d3d._dxgi = types.SimpleNamespace(CreateDXGIFactory1=create_factory)
d3d._d3d11 = types.SimpleNamespace(D3D11CreateDevice=create_device)
d3d._method = fake_method
d3d.query_interface = query_interface


def attempt(fn):
    try:
        fn()
        return None
    except Exception as e:   # noqa: BLE001
        return type(e).__name__


print("== find_adapter：GetDesc1 抛错")
fail["desc"] = True
check("异常照常抛出去", attempt(lambda: d3d.find_adapter((1, 2))), "OSError")
check("显卡和 factory 都释放了", sorted(released), sorted([ADAPTER, FACTORY]))
released.clear()
fail["desc"] = False
check("正常时：找不到这块显卡，显卡和 factory 各释放一次", (attempt(lambda: d3d.find_adapter((1, 2))),
                                                   sorted(released)), (None, sorted([ADAPTER, FACTORY])))

for case in ("qi", "set_mt"):
    print(f"== Device：{case} 抛错")
    released.clear()
    fail[case] = True
    check(f"{case}：异常照常抛出去", attempt(lambda: d3d.Device(None)), "OSError")
    want = [CTX, DEV] + ([MT] if case == "set_mt" else [])
    check(f"{case}：device、context（和 Multithread 接口）都释放了", sorted(released), sorted(want))
    fail[case] = False
released.clear()
check("正常时：只释放 Multithread 接口", (attempt(lambda: d3d.Device(None)), released), (None, [MT]))

print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
