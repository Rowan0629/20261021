"""純程式的比對：疑似重複、同位置清單、總筆數、@bot 查詢。AI 只負責把問題解析成條件，不會看到整份資料。"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .store import AssetRow
from .tasks import NON_ASSET, UNSPECIFIED_LOCATION, QuerySpec

SAME_PLACE_SIMILARITY = 0.6
UNSPECIFIED_SIMILARITY = 0.85
MAX_DUPLICATES = 3


def normalize_location(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).upper()


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower()


def _is_asset(row: AssetRow) -> bool:
    return row.active and row.category != NON_ASSET


def total_count(rows: list[AssetRow]) -> int:
    """倉庫總筆數：狀態正常、而且不是「非劇團資產」。"""
    return sum(1 for r in rows if _is_asset(r))


def _similar(a: str, b: str, *, allow_containment: bool, threshold: float) -> bool:
    a, b = _fold(a), _fold(b)
    if SequenceMatcher(None, a, b).ratio() >= threshold:
        return True
    shorter, longer = sorted((a, b), key=len)
    return allow_containment and len(shorter) >= 2 and shorter in longer


def find_duplicates(rows: list[AssetRow], new: AssetRow) -> list[AssetRow]:
    """只提醒、不阻擋。同一個明確位置 + 名稱相似；雙方位置都未指定時，名稱要非常像才算。"""
    if new.category == NON_ASSET:
        return []
    unspecified = normalize_location(UNSPECIFIED_LOCATION)
    new_loc = normalize_location(new.location)
    hits = []
    for r in rows:
        if r.id == new.id or not r.active or r.category != new.category:
            continue
        loc = normalize_location(r.location)
        if loc != new_loc:
            continue
        if loc == unspecified:
            similar = _similar(r.name, new.name, allow_containment=False, threshold=UNSPECIFIED_SIMILARITY)
        else:
            similar = _similar(r.name, new.name, allow_containment=True, threshold=SAME_PLACE_SIMILARITY)
        if similar:
            hits.append(r)
    hits.sort(key=lambda r: r.id, reverse=True)
    return hits[:MAX_DUPLICATES]


def same_location(rows: list[AssetRow], new: AssetRow, limit: int = 5) -> tuple[int, list[AssetRow]]:
    """(同一位置目前的件數（含這一筆）, 其他物品最多 limit 筆，新的在前)。非劇團資產不列。"""
    if not _is_asset(new):
        return 0, []
    place = normalize_location(new.location)
    others = [r for r in rows if r.id != new.id and _is_asset(r) and normalize_location(r.location) == place]
    others.sort(key=lambda r: r.id, reverse=True)
    return len(others) + 1, others[:limit]


def _plain_play(text: str) -> str:
    return re.sub(r"[《》\s]", "", _fold(text))


def run_query(rows: list[AssetRow], spec: QuerySpec, limit: int = 10) -> tuple[int, list[AssetRow]]:
    """(符合的總筆數, 最多 limit 筆，新的在前)。預設不含已刪除與非劇團資產。"""
    matches = []
    for r in rows:
        if not r.active:
            continue
        if spec.category:
            if r.category != spec.category:
                continue
        elif r.category == NON_ASSET:
            continue
        if spec.condition and r.condition != spec.condition:
            continue
        if spec.loaned and not r.loaned:
            continue
        if spec.play and _plain_play(spec.play) not in _plain_play(r.play):
            continue
        if spec.location and normalize_location(spec.location) not in normalize_location(r.location):
            continue
        haystack = _fold(" ".join([r.name, r.features, r.scene, r.remarks]))
        if not all(_fold(k) in haystack for k in spec.keywords):
            continue
        matches.append(r)
    matches.sort(key=lambda r: r.id, reverse=True)
    return len(matches), matches[:limit]
