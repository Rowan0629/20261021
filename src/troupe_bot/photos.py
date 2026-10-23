"""照片：驗證並轉成 JPEG、縮圖、決定存檔檔名。

防護 3（檔名清洗）的套用點在 photo_paths()；清洗函式 sanitize_name_part() 放在區塊外，方便單獨測試。
"""

from __future__ import annotations

import io
import unicodedata
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_PIXELS = 50_000_000
MAX_LONG_EDGE = 2048
THUMB_LONG_EDGE = 150
MAX_NAME_LEN = 20
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
UNNAMED = "未命名"

Image.MAX_IMAGE_PIXELS = MAX_PIXELS

_BAD_CHARS = set('\\/:*?"<>|')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


class ImageRejected(Exception):
    """上傳的東西不是可以處理的圖片。"""


class UnsafePath(Exception):
    """算出來的存檔路徑跑到照片資料夾外面了。"""


def normalize_image(data: bytes) -> bytes:
    """確認真的是圖片（不看副檔名），轉成 RGB JPEG、長邊 <= 2048、去除 EXIF（含 GPS）。"""
    try:
        img = Image.open(io.BytesIO(data))
        if img.format not in ALLOWED_FORMATS:
            raise ImageRejected(f"不支援的圖片格式：{img.format}")
        width, height = img.size
        if width * height > MAX_PIXELS:
            raise ImageRejected("圖片的長寬像素太大")
        img.load()
    except ImageRejected:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ImageRejected("不是有效的圖片") from exc

    img = ImageOps.exif_transpose(img)  # 先依 EXIF 轉正，之後 EXIF 就丟掉
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.split()[-1])
        img = flat
    else:
        img = img.convert("RGB")
    img.thumbnail((MAX_LONG_EDGE, MAX_LONG_EDGE), Image.LANCZOS)

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90, optimize=True)  # 沒有傳 exif= 參數 → 不會寫入 EXIF
    return out.getvalue()


def make_thumbnail(jpeg: bytes) -> bytes:
    img = Image.open(io.BytesIO(jpeg)).convert("RGB")
    img.thumbnail((THUMB_LONG_EDGE, THUMB_LONG_EDGE), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=70, optimize=True)
    return out.getvalue()


def sanitize_name_part(raw: str) -> str:
    """把任意文字變成可以安全放進 Windows 檔名的一小段。"""
    text = unicodedata.normalize("NFKC", raw)
    text = "".join(ch for ch in text if ch not in _BAD_CHARS and ch.isprintable())
    while ".." in text:
        text = text.replace("..", "")
    text = text.strip(" .")
    if text.split(".")[0].upper() in _RESERVED:
        text = "_" + text
    text = text[:MAX_NAME_LEN].strip(" .")
    return text or UNNAMED


def _ensure_inside(photos_dir: Path, path: Path) -> None:
    if path.resolve().parent != photos_dir.resolve():
        raise UnsafePath(f"路徑跑到照片資料夾外面了：{path}")


def photo_paths(photos_dir: Path, when: datetime, category: str, short_name: str, count: int) -> list[Path]:
    """回傳 count 個還沒被用掉的檔案路徑：`YYYY-MM-DD hh-mm-ss 類別 簡稱.jpg`，撞名依序加 -2、-3。"""
    prefix = f"{when:%Y-%m-%d %H-%M-%S} {category} "

    name_part = short_name  # 不防護的原始值：直接使用模型給的名稱

    # ==== 防護 3：檔名清洗　開始 ====
    name_part = sanitize_name_part(short_name)
    _ensure_inside(photos_dir, photos_dir / f"{prefix}{name_part}.jpg")
    # ==== 防護 3 結束 ====

    chosen: list[Path] = []
    for _ in range(count):
        n = 1
        while True:
            suffix = "" if n == 1 else f"-{n}"
            candidate = photos_dir / f"{prefix}{name_part}{suffix}.jpg"
            if not candidate.exists() and candidate not in chosen:
                chosen.append(candidate)
                break
            n += 1
    return chosen
