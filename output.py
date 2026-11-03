"""保存截图（按游戏分文件夹）与写剪贴板。"""
from __future__ import annotations

import ctypes
import io
import logging
import re
import time
import uuid
from datetime import datetime
from pathlib import Path

from PIL import Image
from PIL.PngImagePlugin import PngInfo

log = logging.getLogger(__name__)

FOLDERID_Pictures = uuid.UUID("{33E28130-4E1E-4676-835A-98395C3BC3BB}")


def pictures_dir() -> Path:
    """「图片」文件夹的真实位置（被 OneDrive 或手动迁移过也能找到）。"""
    guid = (ctypes.c_byte * 16).from_buffer_copy(FOLDERID_Pictures.bytes_le)
    out = ctypes.c_wchar_p()
    if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None,
                                                  ctypes.byref(out)) == 0:
        path = Path(out.value)
        ctypes.windll.ole32.CoTaskMemFree(out)
        return path
    return Path.home() / "Pictures"


def shots_root(save_dir: str) -> Path:
    return Path(save_dir) if save_dir else pictures_dir() / "GameShots"


def _safe_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "未知游戏"


def save_png(img: Image.Image, root: Path, game: str, when: datetime,
             meta: dict[str, str]) -> Path:
    folder = root / _safe_name(game)
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{_safe_name(game)}_{when:%Y-%m-%d_%H-%M-%S}"
    path = folder / f"{stem}.png"
    n = 2
    while path.exists():
        path = folder / f"{stem}_{n}.png"
        n += 1
    info = PngInfo()
    for k, v in meta.items():
        info.add_text(k, v)
    # 先写临时文件再改名，避免半截文件
    tmp = path.with_suffix(".png.part")
    img.save(tmp, "PNG", pnginfo=info, compress_level=6)
    tmp.replace(path)
    return path


def copy_to_clipboard(img: Image.Image) -> bool:
    import win32clipboard

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "BMP")
    dib = buf.getvalue()[14:]  # 去掉 14 字节 BITMAPFILEHEADER 就是 CF_DIB
    for _ in range(10):
        try:
            win32clipboard.OpenClipboard()
        except Exception:
            time.sleep(0.05)  # 剪贴板被别的程序占着
            continue
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib)
            return True
        finally:
            win32clipboard.CloseClipboard()
    log.warning("剪贴板一直被占用，未能复制截图")
    return False
