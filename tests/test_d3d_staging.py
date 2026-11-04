"""换暂存纹理时新建失败，不留悬空指针（02-findings L5）。

Device.read_texture 在画面尺寸变化时先 release 旧的暂存纹理、再建新的。以前 CreateTexture2D 抛错后，self._staging 还是
那个已释放的指针、尺寸也还是旧的：下次再用同一个 Device（以后如果改成出错后重试），就是释放后使用、重复释放。
这里把 d3d._method / release 换成假的（不碰 D3D），检查：
1. 新建失败：旧纹理释放了一次，_staging 清零，记下的尺寸不再是旧尺寸；
2. 再来一次（又失败）：不会再释放那个旧指针；
3. 之后新建成功：用的是新纹理，尺寸记对。
纯 Python，Windows 和 Linux（tests/winstubs.py 桩）都能跑。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_d3d_staging.py
"""
import sys
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


OLD, NEW = 0x1111, 0x2222
released: list[int] = []
create_ok = {"value": False}


def fake_method(ptr, index, *types):
    if ptr == "device" and index == 5:   # CreateTexture2D
        def create(desc, init, out):
            if not create_ok["value"]:
                raise OSError("CreateTexture2D 失败（假）")
            out._obj.value = NEW
            return 0
        return create
    return lambda *a: 0   # 立即上下文的 CopyResource / Map / Unmap


d3d._method = fake_method
d3d.release = lambda p: released.append(p) if p else None
dev = object.__new__(d3d.Device)
dev.device, dev.context = "device", "context"
dev._staging, dev._staging_size = OLD, (1920, 1080)


def read(w, h):
    try:
        dev.read_texture(0x3333, w, h, lambda addr, pitch: None)
        return None
    except Exception as e:   # noqa: BLE001
        return type(e).__name__


print("== 1. 新建失败")
check("异常照常抛出去", read(2560, 1440), "OSError")
check("旧纹理释放了一次", released, [OLD])
check("_staging 清零了", dev._staging, 0)
check("记下的尺寸不再是旧的", dev._staging_size != (1920, 1080), True)
print("== 2. 再失败一次")
read(2560, 1440)
check("不会再释放旧指针", released.count(OLD), 1)
print("== 3. 之后新建成功")
create_ok["value"] = True
check("不抛异常", read(2560, 1440), None)
check("用的是新纹理、尺寸记对", (dev._staging, dev._staging_size), (NEW, (2560, 1440)))

print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
