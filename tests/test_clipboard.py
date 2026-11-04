"""output.copy_to_clipboard 的特征测试：固定它交给剪贴板的数据和重试行为。
win32clipboard 换成只记录调用的假模块（Windows 上也是），不碰真剪贴板。

1. 写进剪贴板的是 CF_DIB：等于「图转成 RGB 后存成 BMP，去掉 14 字节文件头」，逐字节比较；
   几种尺寸（含奇数宽度，行要补齐到 4 字节）和几种模式（RGB / RGBA / L）；
2. 不改动传进来的图；
3. 剪贴板被占用：OpenClipboard 失败几次后成功也能写进去；一直失败时试 10 次后返回 False；
   每次打开成功都会关闭。
Windows 和 Linux（winstubs 桩）都能跑。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_clipboard.py <run dir>
"""
import io
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT, RUN = HERE.parent, Path(sys.argv[1])
RUN.mkdir(parents=True, exist_ok=False)
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PROJECT))
import winstubs  # noqa: E402

winstubs.install()
from PIL import Image  # noqa: E402

import output  # noqa: E402

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(label)


class FakeClipboard(types.ModuleType):
    CF_DIB = 8

    def __init__(self, busy: int = 0) -> None:
        super().__init__("win32clipboard")
        self.busy = busy          # 前几次 OpenClipboard 失败
        self.calls: list[str] = []
        self.data = None
        self.fmt = None

    def OpenClipboard(self, *a) -> None:
        self.calls.append("open")
        if self.busy:
            self.busy -= 1
            raise OSError("剪贴板被占用（假）")

    def CloseClipboard(self) -> None:
        self.calls.append("close")

    def EmptyClipboard(self) -> None:
        self.calls.append("empty")

    def SetClipboardData(self, fmt, data) -> None:
        self.calls.append("set")
        self.fmt, self.data = fmt, data


def expected_dib(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "BMP")
    return buf.getvalue()[14:]


def run_with(fake: FakeClipboard, img: Image.Image) -> bool:
    sys.modules["win32clipboard"] = fake
    return output.copy_to_clipboard(img)


output.time.sleep = lambda s: None   # 重试间隔不真的等

print("== 1. DIB bytes")
SAMPLES = {
    "rgb_1920x1080": Image.effect_noise((1920, 1080), 60).convert("RGB"),
    "rgb_odd_1921x7": Image.effect_noise((1921, 7), 60).convert("RGB"),
    "rgb_3x3": Image.new("RGB", (3, 3), (10, 200, 30)),
    "rgba_33x17": Image.effect_noise((33, 17), 60).convert("RGBA"),
    "l_10x5": Image.effect_noise((10, 5), 60),
}
for name, img in SAMPLES.items():
    before = img.tobytes()
    fake = FakeClipboard()
    ok = run_with(fake, img)
    want = expected_dib(img)
    check(f"{name}: returns True", ok is True)
    check(f"{name}: CF_DIB", fake.fmt == FakeClipboard.CF_DIB, repr(fake.fmt))
    check(f"{name}: data is bytes", isinstance(fake.data, bytes), type(fake.data).__name__)
    check(f"{name}: same bytes as BMP minus file header", fake.data == want,
          f"len {len(fake.data or b'')} vs {len(want)}")
    check(f"{name}: calls", fake.calls == ["open", "empty", "set", "close"], str(fake.calls))
    check(f"{name}: input image untouched", img.tobytes() == before and img.mode == SAMPLES[name].mode)

print("== 2. clipboard busy")
img = SAMPLES["rgb_3x3"]
fake = FakeClipboard(busy=3)
check("busy 3 times: still copied", run_with(fake, img) is True and fake.data == expected_dib(img))
check("busy 3 times: 4 opens, 1 close", fake.calls.count("open") == 4 and fake.calls.count("close") == 1,
      str(fake.calls))
fake = FakeClipboard(busy=100)
check("always busy: returns False", run_with(fake, img) is False)
check("always busy: tried 10 times, nothing written", fake.calls == ["open"] * 10 and fake.data is None,
      str(fake.calls))

print("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
