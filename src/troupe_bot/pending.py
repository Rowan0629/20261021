"""放在硬碟上的暫存資料夾：bot 關掉再開，內容還在。

用在兩個地方（各一個 Spool）：
- `DATA_DIR/pending/`：Excel 被占用、寫不進去時，先把辨識結果和照片收下，等 Excel 能寫了再補登。
- `DATA_DIR/awaiting/`：一張照片有好幾種東西，等上傳者回覆「分開」或「合併」。

每一筆是一個資料夾：`<隨機編號>/meta.json` 加上 `photo1.jpg`…。資料夾名稱一律是隨機編號，
不使用任何 AI 產生的文字或使用者打的字，所以不會有檔名/路徑問題（和防護 3 的精神一致）。
`meta.json` 最後才寫入，所以當機時留下的半成品（沒有 meta.json）會被忽略。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

META = "meta.json"
_last_ns = 0


def _next_ns() -> int:
    """遞增的時間戳。Windows 的時鐘精度只有約 15 毫秒，同時建立的兩筆會一樣，排序（先到先補登）就亂了。"""
    global _last_ns
    _last_ns = max(time.time_ns(), _last_ns + 1)
    return _last_ns


@dataclass
class Record:
    id: str
    meta: dict[str, Any]
    dir: Path = field(repr=False, default=Path("."))

    def photos(self) -> list[bytes]:
        files = sorted(self.dir.glob("photo*.jpg"), key=lambda p: int(p.stem[5:] or 0))
        return [p.read_bytes() for p in files]


class Spool:
    def __init__(self, root: Path):
        self.root = Path(root)

    def create(self, meta: dict[str, Any], photos: list[bytes]) -> Record:
        rid = uuid.uuid4().hex
        folder = self.root / rid
        folder.mkdir(parents=True, exist_ok=True)
        for i, data in enumerate(photos, start=1):
            (folder / f"photo{i}.jpg").write_bytes(data)
        meta = {**meta, "created_ns": _next_ns()}
        self._write_meta(folder, meta)
        return Record(rid, meta, folder)

    def get(self, rid: str) -> Record | None:
        folder = self.root / rid
        try:
            meta = json.loads((folder / META).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return Record(rid, meta, folder)

    def all(self) -> list[Record]:
        if not self.root.is_dir():
            return []
        records = []
        for folder in self.root.iterdir():
            if not folder.is_dir():
                continue
            rec = self.get(folder.name)
            if rec is None:
                if (folder / META).exists():
                    log.warning("暫存資料夾 %s 的 meta.json 讀不出來，已略過", folder)
                continue
            records.append(rec)
        records.sort(key=lambda r: (r.meta.get("created_ns", 0), r.id))
        return records

    def find(self, **match: Any) -> Record | None:
        for rec in self.all():
            if all(rec.meta.get(k) == v for k, v in match.items()):
                return rec
        return None

    def update(self, rid: str, **changes: Any) -> None:
        rec = self.get(rid)
        if rec is None:
            return
        self._write_meta(rec.dir, {**rec.meta, **changes})

    def remove(self, rid: str) -> None:
        shutil.rmtree(self.root / rid, ignore_errors=True)

    @staticmethod
    def _write_meta(folder: Path, meta: dict[str, Any]) -> None:
        tmp = folder / (META + ".tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, folder / META)
