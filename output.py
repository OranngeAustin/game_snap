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


# Windows 保留的设备名：不能用作文件夹名（不分大小写，带扩展名也不行）
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
MAX_NAME = 80   # 文件夹名、文件名里的游戏名最多这么多字符：截图根目录不超过约 60 个字符时，整条路径不超过 260


def _safe_name(name: str) -> str:
    """游戏名 → 文件夹名 / 文件名开头。游戏名来自 config.json 或 yuzu 的窗口标题（ROM 元数据），什么都可能有。
    只处理以前会出错的情况（02-findings M2）：只有点和空格（".." 会写到截图根目录外面）、控制字符、Windows 保留名、
    太长、结尾连续多个点和空格。80 个字符以内、以前就能用的名字一个字不改；超过 80 个字符的会截断（以前约 96 个字符以上就存不下）。"""
    name = re.sub(r'[\\/:*?"<>|]', "_", name).strip()
    name = re.sub(r"[\x00-\x1f]", "_", name)
    if len(name) > MAX_NAME:
        name = name[:MAX_NAME].rstrip(" .")
    # 结尾连续多个点和空格（Loading...）：建文件夹时 Windows 全部去掉，存文件时这一段在路径中间，最多去掉一个点，
    # 两边对不上，这个游戏每张都存不下（05-windows-verification P1）。结尾单个点两边一样，不用动（Game.、.hack__G.U.）
    name = re.sub(r"[ .]{2,}$", "", name)
    if not name.strip(" ."):
        return "未知游戏"
    if name.split(".")[0].rstrip(" ").upper() in _RESERVED:
        name = "_" + name
    return name


def _rename_part(tmp: Path, path: Path, retries: int = 5) -> None:
    """杀毒软件、同步盘刚好在读 .png.part 时改名会抛 PermissionError：隔 0.2 秒重试几次，和 Config.save 一样
    （docs/review/05-windows-verification.md P5）。仍失败就抛出去。"""
    for _ in range(retries - 1):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            time.sleep(0.2)
    tmp.replace(path)


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
    try:
        img.save(tmp, "PNG", pnginfo=info, compress_level=6)
        _rename_part(tmp, path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)   # 磁盘满、被占用时不留半截文件（02-findings L11）
        except OSError as e:
            log.warning("临时文件删不掉，留在了 %s：%s", tmp, e)   # 往外抛的还是上面那个异常（05 P5）
        raise
    return path


def copy_to_clipboard(img: Image.Image) -> bool:
    import win32clipboard

    buf = io.BytesIO()
    # 截图本来就是 RGB：不再 convert，省一次整帧拷贝（4K 一帧约 24MB）
    (img if img.mode == "RGB" else img.convert("RGB")).save(buf, "BMP")
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
        except Exception:
            # 以前冒到 finish_shot：PNG 已经存好，却提示「截图失败」、计数不加（02-findings L10）
            log.exception("写剪贴板失败（截图已保存）")
            return False
        finally:
            win32clipboard.CloseClipboard()
    log.warning("剪贴板一直被占用，未能复制截图")
    return False
