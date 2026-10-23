"""產品行為的核心：歸檔、回覆更新/刪除/借出/歸還、查詢。不依賴 Discord，輸入輸出都是純資料，所以能用假的 claude 完整測試。

兩種「先收下、晚點處理」的情況，資料都放在 DATA_DIR 底下的資料夾（bot 重開也在，見 pending.py）：
- awaiting/：一張照片有好幾種東西，等上傳者回覆「分開」或「合併」（逾時就分開）。
- pending/：Excel 被占用寫不進去，等能寫了再補登。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Callable

from . import replies
from .claude_client import Runner, run_task
from .config import AWAITING_TIMEOUT_SECONDS, Config
from .pending import Spool
from .photos import ImageRejected, UnsafePath, make_thumbnail, normalize_image, photo_paths
from .search import find_duplicates, run_query, same_location, total_count
from .store import AlreadyLoaned, AssetRow, ExcelBusy, NotLoaned, Store
from .tasks import (
    INGEST_INSTRUCTION, INGEST_SCHEMA, NON_ASSET, NOT_APPLICABLE_PLAY, QUERY_INSTRUCTION, QUERY_SCHEMA,
    UPDATE_INSTRUCTION, UPDATE_SCHEMA, AnalysisFailed, IngestResult, parse_ingest, parse_query, parse_update,
)

log = logging.getLogger(__name__)

DELETE_WORD = "刪除"
LEND_WORD = "借出"
RETURN_WORD = "歸還"
MAX_BORROWER_LEN = 20
QUERY_LIMIT = 10

DECISION_SPLIT = "分開"
DECISION_MERGE = "合併"
DECISION_TIMEOUT = "timeout"  # 沒人回覆：由程式自動分開

MODE_PLAIN = "一般"
MODE_MERGED = "合併（上傳者確認）"
MODE_SPLIT = "分開（上傳者確認）"
MODE_SPLIT_AI = "分開（AI 判定）"

STAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass
class Services:
    cfg: Config
    store: Store
    runner: Runner | None = None
    now: Callable[[], datetime] = datetime.now
    awaiting_timeout: float = AWAITING_TIMEOUT_SECONDS
    pending: Spool | None = None
    awaiting: Spool | None = None

    def __post_init__(self) -> None:
        if self.pending is None:
            self.pending = Spool(self.cfg.pending_dir)
        if self.awaiting is None:
            self.awaiting = Spool(self.cfg.awaiting_dir)


@dataclass
class IngestRequest:
    author_name: str
    author_id: int
    text: str
    photos: list[bytes]
    message_id: int = 0


@dataclass
class ReplyRequest:
    author_name: str
    text: str


@dataclass
class QueryRequest:
    text: str


@dataclass
class Outcome:
    text: str
    asset_id: int | None = None
    more: list["Outcome"] = field(default_factory=list)  # 分開入庫時，第二則以後的歸檔結果
    awaiting_id: str | None = None  # 需要上傳者確認「分開／合併」：Dispatcher 要記下確認訊息
    pending_id: str | None = None  # Excel 被占用，已暫存到 pending/


def _stamp(moment: datetime) -> str:
    return moment.strftime(STAMP_FORMAT)


async def _ask(svc: Services, *, instruction, schema, text, text_name, photos, parse):
    return await run_task(
        claude_path=svc.cfg.claude_path, model=svc.cfg.claude_model, data_dir=svc.cfg.data_dir,
        instruction=instruction, schema=schema, user_text=text, text_name=text_name,
        photos=photos, parse=parse, runner=svc.runner,
    )


def _remove(paths) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            log.warning("無法刪除 %s", path)


# ------------------------------------------------------------ 歸檔


async def handle_ingest(svc: Services, req: IngestRequest) -> Outcome:
    try:
        photos = [normalize_image(p) for p in req.photos]
    except ImageRejected:
        return Outcome(replies.UNSUPPORTED_IMAGE)

    try:
        batch = await _ask(
            svc, instruction=INGEST_INSTRUCTION, schema=INGEST_SCHEMA, text=req.text,
            text_name="caption.txt", photos=photos, parse=parse_ingest,
        )
    except AnalysisFailed:
        return Outcome(replies.FAIL_ANALYSIS)

    now = svc.now()
    meta = {
        "uploader_id": req.author_id, "uploader_name": req.author_name, "message_id": req.message_id,
        "registered": _stamp(now),
    }
    if len(batch.items) > 1:  # 照片裡有好幾種東西：先問上傳者，等待期間不佔用 worker
        record = svc.awaiting.create(
            {
                **meta, "deadline": time.time() + svc.awaiting_timeout,
                "items": [asdict(i) for i in batch.items], "combined": asdict(batch.combined),
            },
            photos,
        )
        minutes = max(1, round(svc.awaiting_timeout / 60))
        return Outcome(replies.confirm_items([i.name for i in batch.items], minutes=minutes), awaiting_id=record.id)

    return await _commit_or_pend(svc, meta=meta, items=batch.items, photos=photos, mode=MODE_PLAIN)


async def _commit_or_pend(svc: Services, *, meta: dict, items: list[IngestResult], photos: list[bytes], mode: str) -> Outcome:
    """寫進 Excel；Excel 一直被占用就把結果與照片暫存到 pending/，之後自動補登。"""
    try:
        if svc.pending.all():  # 前面還有暫存的資料沒補登：排在它們後面，編號才會照先後順序
            raise ExcelBusy("排在較早的暫存資料後面")
        return await _commit(svc, meta=meta, items=items, photos=photos, mode=mode)
    except ExcelBusy:
        record = svc.pending.create({**meta, "mode": mode, "items": [asdict(i) for i in items]}, photos)
        log.warning("Excel 被占用（或前面還有暫存資料），已暫存到 %s，稍後自動補登", record.dir)
        return Outcome(replies.PENDING_NOTICE, pending_id=record.id)


async def _commit(
    svc: Services, *, meta: dict, items: list[IngestResult], photos: list[bytes], mode: str, prefix: str = "",
) -> Outcome:
    """存照片、寫 Excel（一次存檔寫入所有列）。Excel 寫不進去時丟 ExcelBusy，並把剛存的照片刪掉。"""
    registered = datetime.strptime(meta["registered"], STAMP_FORMAT)
    stamp = meta["registered"]
    uploader = meta["uploader_name"]
    written = []
    try:
        svc.cfg.photos_dir.mkdir(parents=True, exist_ok=True)
        thumb = make_thumbnail(photos[0])
        pairs = []
        for item in items:
            paths = photo_paths(svc.cfg.photos_dir, registered, item.category, item.short_name, len(photos))
            for path, data in zip(paths, photos):
                path.write_bytes(data)
                written.append(path)
            row = AssetRow(
                registered_at=stamp, uploader=uploader, name=item.name, category=item.category,
                features=item.features, scene=item.scene, play=item.play, quantity=item.quantity,
                quantity_ai=item.quantity_ai, condition=item.condition, condition_ai=(item.condition_source == "ai"),
                location=item.location, remarks=item.remarks, photo_paths=[str(p) for p in paths],
                updated_by=uploader, updated_at=stamp, intake_mode=mode,
            )
            pairs.append((row, thumb))
        rows = await asyncio.to_thread(svc.store.add_many, pairs)
    except ExcelBusy:
        _remove(written)
        raise
    except (OSError, UnsafePath):
        log.exception("寫入照片或記錄時失敗")
        _remove(written)
        return Outcome(replies.FAIL_ANALYSIS)
    return await _archive_outcome(svc, rows, prefix)


async def _archive_outcome(svc: Services, rows: list[AssetRow], prefix: str = "") -> Outcome:
    """入庫成功後的回覆：每一列各一則；總筆數與同位置清單只附在最後一則。"""
    try:
        all_rows = await asyncio.to_thread(svc.store.all_rows)
    except ExcelBusy:  # 已經入庫了，只是讀不到統計；照樣回覆成功
        all_rows = list(rows)
    total = total_count(all_rows)
    batch_ids = {r.id for r in rows}
    elsewhere = [r for r in all_rows if r.id not in batch_ids]  # 同一張照片拆出來的東西，不互相算重複

    outcomes = []
    for i, row in enumerate(rows):
        if row.category == NON_ASSET:
            text = replies.non_asset(row, total=total)
        else:
            count, others = same_location(all_rows, row)
            text = replies.archive(
                row, total=total, same_count=count, same_others=others,
                duplicates=find_duplicates([*elsewhere, row], row), with_totals=(i == len(rows) - 1),
            )
        outcomes.append(Outcome(text, asset_id=row.id))
    head, *rest = outcomes
    if prefix:
        head.text = f"{prefix}\n{head.text}"
    head.more = rest
    return head


async def resolve_awaiting(svc: Services, record_id: str, decision: str) -> Outcome | None:
    """上傳者回覆「分開／合併」，或逾時（DECISION_TIMEOUT）。已處理過或找不到就回 None（不會重複入庫）。"""
    record = svc.awaiting.get(record_id)
    if record is None:
        return None
    items = [IngestResult(**d) for d in record.meta["items"]]
    if decision == DECISION_MERGE:
        items, mode = [IngestResult(**record.meta["combined"])], MODE_MERGED
    elif decision == DECISION_SPLIT:
        mode = MODE_SPLIT
    else:
        mode = MODE_SPLIT_AI
    try:
        return await _commit_or_pend(svc, meta=record.meta, items=items, photos=record.photos(), mode=mode)
    finally:
        svc.awaiting.remove(record_id)  # 不論成功、暫存或失敗，這筆「等確認」都結束了


async def flush_pending_record(svc: Services, record_id: str) -> Outcome | None:
    """把 pending/ 裡最舊的一筆補寫進 Excel。還沒輪到（前面還有更舊的）或 Excel 仍被占用就回 None。"""
    records = svc.pending.all()
    if not records or records[0].id != record_id:
        return None
    record = records[0]
    items = [IngestResult(**d) for d in record.meta["items"]]
    try:
        outcome = await _commit(
            svc, meta=record.meta, items=items, photos=record.photos(), mode=record.meta["mode"],
            prefix=replies.backfilled(),
        )
    except ExcelBusy:
        return None
    svc.pending.remove(record_id)
    return outcome


# ------------------------------------------------------------ 回覆歸檔訊息：更新 / 刪除 / 借出 / 歸還


def parse_loan(text: str) -> tuple[str, str | None] | None:
    """「借出 王小明」→ ("lend", "王小明")；「借出」→ ("lend", None)；「歸還」→ ("return", None)；其他 → None。

    用關鍵字精確比對，不經 AI（和刪除一樣，避免被文字誘導）。名字最多 20 字、不可換行；
    太長或多行的文字不是借還指令，照一般更新交給 AI。
    """
    stripped = text.strip()
    if stripped == RETURN_WORD:
        return ("return", None)
    if not stripped.startswith(LEND_WORD) or "\n" in stripped:
        return None
    name = stripped[len(LEND_WORD):].strip(" 　:：")
    if not name:
        return ("lend", None)
    if len(name) > MAX_BORROWER_LEN:
        return None
    return ("lend", name)


async def handle_reply(svc: Services, row: AssetRow, req: ReplyRequest) -> Outcome:
    if not row.active:
        return Outcome(replies.ALREADY_DELETED)
    stamp = _stamp(svc.now())

    if req.text.strip() == DELETE_WORD:  # 精確比對關鍵字，不經過 AI，避免被文字誘導誤刪
        try:
            deleted = await asyncio.to_thread(svc.store.mark_deleted, row.id, by=req.author_name, at=stamp)
        except KeyError:
            return Outcome(replies.NOT_FOUND)
        return Outcome(replies.deleted(deleted), asset_id=row.id)

    loan = parse_loan(req.text)
    if loan is not None:
        return await _handle_loan(svc, row, req.author_name, stamp, loan)

    try:
        patch = await _ask(
            svc, instruction=UPDATE_INSTRUCTION, schema=UPDATE_SCHEMA, text=req.text,
            text_name="message.txt", photos=[], parse=parse_update,
        )
    except AnalysisFailed:
        return Outcome(replies.FAIL_ANALYSIS)
    if patch.is_empty():
        return Outcome(replies.NOTHING_TO_UPDATE)

    changes = dict(patch.fields)
    if changes.get("category") == NON_ASSET:
        changes["play"] = NOT_APPLICABLE_PLAY
    if "condition" in changes:
        changes["condition_ai"] = False  # 人工更正，不再標示為 AI 判斷
    if "quantity" in changes:
        changes["quantity_ai"] = False
    try:
        updated = await asyncio.to_thread(
            svc.store.update, row.id, changes, by=req.author_name, at=stamp, remarks_append=patch.remarks_append,
        )
    except ValueError:
        return Outcome(replies.ALREADY_DELETED)
    except KeyError:
        return Outcome(replies.NOT_FOUND)
    return Outcome(replies.updated(updated), asset_id=row.id)


async def _handle_loan(svc: Services, row: AssetRow, by: str, stamp: str, loan: tuple[str, str | None]) -> Outcome:
    kind, borrower = loan
    if kind == "lend" and borrower is None:
        return Outcome(replies.LOAN_NEED_NAME)
    try:
        if kind == "return":
            done = await asyncio.to_thread(svc.store.give_back, row.id, by=by, at=stamp)
            return Outcome(replies.returned(done), asset_id=row.id)
        done = await asyncio.to_thread(svc.store.lend, row.id, borrower, by=by, at=stamp)
        return Outcome(replies.lent(done), asset_id=row.id)
    except AlreadyLoaned as exc:
        return Outcome(replies.already_lent(exc.row))
    except NotLoaned:
        return Outcome(replies.NOT_LENT)
    except ValueError:
        return Outcome(replies.ALREADY_DELETED)
    except KeyError:
        return Outcome(replies.NOT_FOUND)


# ------------------------------------------------------------ 查詢


async def handle_query(svc: Services, req: QueryRequest) -> Outcome:
    try:
        spec = await _ask(
            svc, instruction=QUERY_INSTRUCTION, schema=QUERY_SCHEMA, text=req.text,
            text_name="message.txt", photos=[], parse=parse_query,
        )
    except AnalysisFailed:
        return Outcome(replies.FAIL_ANALYSIS)
    if spec.is_empty():
        return Outcome(replies.NO_QUERY)
    rows = await asyncio.to_thread(svc.store.all_rows)
    total, hits = run_query(rows, spec, limit=QUERY_LIMIT)
    return Outcome(replies.query_result(total, hits, limit=QUERY_LIMIT))
