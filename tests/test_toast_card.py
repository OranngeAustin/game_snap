"""toast.render_card（提示卡片）的特征测试：固定它画出来的图。
1. 多组文字（中文、英文、带 &、长句）× 成功 / 失败 × 缩放 1.0 / 1.25 / 1.5 / 2.0，图逐字节等于参照实现：
   下面 reference_card 是 render_card 原来的代码，每次都新建字体对象；
2. 同样的参数连画两次结果一样（有字体缓存时第二次走缓存）；
3. _premultiplied_bgra 逐字节等于参照实现。
字体按 toast._font 的顺序找（Windows 上是 msyh.ttc；Linux 上找不到时用 Pillow 自带字体），参照实现找法相同。
Windows 和 Linux（winstubs 桩）都能跑。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_toast_card.py <run dir>
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT, RUN = HERE.parent, Path(sys.argv[1])
RUN.mkdir(parents=True, exist_ok=False)
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PROJECT))
import winstubs  # noqa: E402

winstubs.install()
from PIL import Image, ImageChops, ImageDraw, ImageFont  # noqa: E402

import toast  # noqa: E402

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(label)


def reference_font(size: int):
    for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def reference_card(text: str, ok: bool, scale: float) -> Image.Image:
    ss = 3
    k = scale * ss
    font = reference_font(round(15 * k))
    pad_x, pad_y, icon, gap = round(14 * k), round(10 * k), round(22 * k), round(9 * k)
    l, t, r, b = font.getbbox(text)
    text_w, text_h = r - l, b - t
    h = max(icon, text_h) + 2 * pad_y
    w = pad_x + icon + gap + text_w + pad_x
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=round(10 * k), fill=(28, 28, 30, 225))
    cx, cy = pad_x + icon / 2, h / 2
    d.ellipse([pad_x, cy - icon / 2, pad_x + icon, cy + icon / 2], fill=toast.GREEN if ok else toast.RED)
    lw = max(2, round(2.4 * k))
    if ok:
        u = icon / 22
        d.line([(cx - 5.5 * u, cy + 0.3 * u), (cx - 1.6 * u, cy + 4.2 * u),
                (cx + 5.8 * u, cy - 4.2 * u)], fill="white", width=lw, joint="curve")
    else:
        u = icon / 22
        d.line([(cx, cy - 6 * u), (cx, cy + 1.5 * u)], fill="white", width=lw)
        d.ellipse([cx - lw / 1.6, cy + 4.2 * u - lw / 1.6, cx + lw / 1.6, cy + 4.2 * u + lw / 1.6],
                  fill="white")
    d.text((pad_x + icon + gap - l, (h - text_h) / 2 - t), text, font=font, fill="white")
    return img.resize((round(w / ss), round(h / ss)), Image.Resampling.LANCZOS)


def reference_premultiplied(img: Image.Image) -> bytes:
    r, g, b, a = img.split()
    r, g, b = (ImageChops.multiply(c, a) for c in (r, g, b))
    return Image.merge("RGBA", (b, g, r, a)).tobytes()


TEXTS = ["已截图 · 原神", "截图失败", "已添加 · Ratchet & Clank（RiftApart.exe）",
         "请按下新的截图键或鼠标侧键（Esc 取消）", "DualSense 已改为四声道，没有震动的话重启游戏"]
print("== 1. cards")
for text in TEXTS:
    for ok in (True, False):
        for scale in (1.0, 1.25, 1.5, 2.0):
            got, want = toast.render_card(text, ok, scale), reference_card(text, ok, scale)
            same = got.size == want.size and got.mode == want.mode and got.tobytes() == want.tobytes()
            check(f"{text[:12]!r} ok={ok} scale={scale}", same, "" if same else f"{got.size} vs {want.size}")

print("== 2. same arguments twice")
for scale in (1.0, 1.5):
    a, b = toast.render_card("已截图 · 原神", True, scale), toast.render_card("已截图 · 原神", True, scale)
    check(f"scale={scale}: identical", a.tobytes() == b.tobytes() and a is not b)

print("== 3. premultiplied BGRA")
for ok in (True, False):
    card = toast.render_card("已截图 · 原神", ok, 1.5)
    check(f"ok={ok}: same bytes", toast._premultiplied_bgra(card) == reference_premultiplied(card))

print("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
