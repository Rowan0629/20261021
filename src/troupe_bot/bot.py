"""Discord 串接：分流（歸檔 / 確認 / 回覆更新刪除借還 / 查詢）、單一 worker 佇列、⏳ 與 ❓ 反應、回覆。

Dispatcher 只認「像訊息的物件」（id、author、channel、content、attachments、mentions、reference、
reply、add_reaction、remove_reaction），所以測試可以用假物件；TroupeBot 只是把 discord.Client 的事件轉過來。

兩件「晚點才做」的事（資料放在硬碟上，bot 重開也不會掉，見 pending.py）：
- 照片裡有好幾種東西：發確認訊息、換成 ❓，上傳者回覆「分開／合併」，或時間到就自動分開。等待期間不佔用 worker。
- Excel 被占用：先回「已收到」，之後每隔一段時間（以及處理下一件工作之前）自動補登，補完通知上傳者。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

import discord

from . import replies
from .config import IMAGE_EXTENSIONS, MAX_IMAGE_BYTES, MAX_PHOTOS_PER_MESSAGE, PENDING_RETRY_SECONDS, QUEUE_MAX
from .handlers import (
    DECISION_MERGE, DECISION_SPLIT, DECISION_TIMEOUT, IngestRequest, Outcome, QueryRequest, ReplyRequest, Services,
    flush_pending_record, handle_ingest, handle_query, handle_reply, resolve_awaiting,
)
from .store import AssetRow, ExcelBusy

log = logging.getLogger(__name__)

HOURGLASS = "⏳"
QUESTION = "❓"
_MENTION = re.compile(r"<@[!&]?\d+>")

# bot 的三種狀態：開機一律從待命開始，管理員 !上線 才運作；!下線 會先做完手上的工作（下線中）再回到待命
STANDBY = "standby"
ACTIVE = "active"
STOPPING = "stopping"
_COMMANDS = {"!上線": "online", "!下線": "offline"}


def parse_command(content: str) -> str | None:
    """內容（去掉 @ 之後）完全等於 !上線 或 !下線 才算指令；全形「！」視為半形。"""
    return _COMMANDS.get(unicodedata.normalize("NFKC", clean_text(content)))


def presence_for(mode: str) -> tuple[discord.Status, discord.CustomActivity | None]:
    """Discord 上的狀態燈：待命＝黃色閒置並寫明怎麼叫醒，運作與下線中＝綠色線上。"""
    if mode == STANDBY:
        return discord.Status.idle, discord.CustomActivity(name="待命中，管理員輸入 !上線")
    return discord.Status.online, None


def is_admin(author) -> bool:
    return bool(getattr(getattr(author, "guild_permissions", None), "manage_guild", False))


def is_image(attachment) -> bool:
    return (attachment.content_type or "").startswith("image/") or Path(attachment.filename).suffix.lower() in IMAGE_EXTENSIONS


def clean_text(content: str) -> str:
    return _MENTION.sub("", content or "").strip()


@dataclass
class Job:
    message: object | None  # 結果要回覆在哪一則訊息底下；None = 找不到（照樣做事，只是不回覆）
    uploader_id: int
    work: Callable[[], Awaitable[Outcome | None]] | None
    silent: bool = False  # True：不是剛收到的訊息（沒加過 ⏳、沒回過「處理中」），例如逾時自動分開
    kind: str = "work"  # "work" 或 "flush"（只補登 pending/）


class Dispatcher:
    def __init__(
        self,
        svc: Services,
        *,
        bot_user,
        queue_max: int = QUEUE_MAX,
        lookup: Callable[[int], object | None] | None = None,
        pending_interval: float = PENDING_RETRY_SECONDS,
        start_active: bool = True,
        on_mode_change: Callable[[str], Awaitable[None]] | None = None,
    ):
        self.svc = svc
        self.mode = ACTIVE if start_active else STANDBY
        self._on_mode_change = on_mode_change
        self.bot_user = bot_user
        self.queue: asyncio.Queue[Job] = asyncio.Queue(maxsize=queue_max)
        self.busy = False
        self.pending_interval = pending_interval
        self._lookup = lookup  # bot 重開後，用訊息編號找回那則訊息（TroupeBot 提供）
        self._remembered: dict[int, object] = {}
        self._timers: dict[str, asyncio.Task] = {}
        self._flush_queued = False
        self._flush_blocked_until = 0.0

    # ------------------------------------------------------------ 分流

    async def on_message(self, message) -> None:
        if message.author.bot or message.channel.id != self.svc.cfg.channel_id:
            return  # 只聽指定頻道、不理會 bot（包含自己）

        command = parse_command(message.content)
        if command is not None:
            await self._command(message, command)
            return
        if self.mode != ACTIVE:
            return  # 待命或下線中：其餘一律靜默忽略（包含照片）

        text = clean_text(message.content)
        images = [a for a in message.attachments if is_image(a)]
        if images:
            await self._ingest(message, images, text)
            return

        ref = message.reference
        if ref is not None and ref.message_id is not None:
            waiting = self.svc.awaiting.find(confirm_message_id=ref.message_id)
            if waiting is not None:  # 回覆的是「請選分開或合併」的確認訊息
                await self._answer(message, waiting, text)
                return
            row = await self._find_row(ref.message_id)
            if row is not None:
                req = ReplyRequest(author_name=message.author.display_name, text=text)
                await self._enqueue(message, lambda: handle_reply(self.svc, row, req))
                return
            resolved = getattr(ref, "resolved", None)
            if getattr(getattr(resolved, "author", None), "id", None) == self.bot_user.id:
                return  # 回覆 bot 自己的「處理中」或失敗訊息：不是查詢

        if any(u.id == self.bot_user.id for u in message.mentions):
            if not text:
                await message.reply(replies.NO_QUERY, mention_author=False)
                return
            await self._enqueue(message, lambda: handle_query(self.svc, QueryRequest(text=text)))

    # ------------------------------------------------------------ 上線／下線

    async def _command(self, message, command: str) -> None:
        """!上線／!下線：只認管理員，精確比對，不經 AI。"""
        async def say(text: str) -> None:
            await message.reply(text, mention_author=False)

        if not is_admin(message.author):
            await say(replies.ADMIN_ONLY)
        elif command == "online":
            if self.mode == ACTIVE:
                await say(replies.ALREADY_ONLINE)
                return
            cancelled = self.mode == STOPPING
            await self._set_mode(ACTIVE)
            await self.recover()  # 接續 awaiting/ 的計時與 pending/ 的補登
            await say(replies.CANCELLED_OFFLINE if cancelled else replies.ONLINE)
        elif self.mode == STANDBY:
            await say(replies.ALREADY_STANDBY)
        elif self.mode == STOPPING:
            await say(replies.STOPPING_NOW)
        else:
            await self._set_mode(STOPPING)
            self._cancel_all_timers()
            await self.queue.join()
            if self.mode != STOPPING:
                return  # 等待期間被 !上線 取消了
            await self._set_mode(STANDBY)
            await say(replies.OFFLINE)

    async def _set_mode(self, mode: str) -> None:
        self.mode = mode
        if self._on_mode_change is not None:
            try:
                await self._on_mode_change(mode)
            except Exception:
                log.exception("更新 Discord 狀態失敗")

    async def _ingest(self, message, images, text: str) -> None:
        if len(images) > MAX_PHOTOS_PER_MESSAGE:
            await message.reply(replies.TOO_MANY_PHOTOS, mention_author=False)
            return
        if any((a.size or 0) > MAX_IMAGE_BYTES for a in images):
            await message.reply(replies.TOO_BIG, mention_author=False)
            return

        async def work() -> Outcome:
            photos = [await a.read() for a in images]
            req = IngestRequest(
                author_name=message.author.display_name, author_id=message.author.id, text=text, photos=photos,
                message_id=message.id,
            )
            return await handle_ingest(self.svc, req)

        await self._enqueue(message, work)

    async def _find_row(self, message_id: int) -> AssetRow | None:
        try:
            return await asyncio.to_thread(self.svc.store.find_by_message, message_id)
        except Exception:
            log.exception("查詢被回覆的訊息時失敗")
            return None

    # ------------------------------------------------------------ 多種東西：確認、逾時

    async def _answer(self, message, waiting, text: str) -> None:
        """只有上傳者本人、而且只認「分開」「合併」兩個字；其他一律忽略（也不會被當成查詢）。"""
        if message.author.id != waiting.meta["uploader_id"] or text not in (DECISION_SPLIT, DECISION_MERGE):
            return
        try:
            self._queue_resolution(waiting.id, text)
        except asyncio.QueueFull:
            await message.reply(replies.QUEUE_FULL, mention_author=False)

    def _queue_resolution(self, record_id: str, decision: str) -> None:
        record = self.svc.awaiting.get(record_id)
        if record is None:
            return
        original = self.get_message(record.meta["message_id"])

        async def work() -> Outcome | None:
            try:
                return await resolve_awaiting(self.svc, record_id, decision)
            finally:
                self._cancel_timer(record_id)
                await self._clear_question(original)

        self.queue.put_nowait(Job(original, record.meta["uploader_id"], work, silent=True))

    def _start_timer(self, record_id: str) -> None:
        record = self.svc.awaiting.get(record_id)
        if record is None:
            return
        delay = max(0.0, record.meta["deadline"] - time.time())
        self._cancel_timer(record_id)  # recover() 會在每次上線時再呼叫，不能留下重複的計時器
        self._timers[record_id] = asyncio.create_task(self._expire(record_id, delay))

    async def _expire(self, record_id: str, delay: float) -> None:
        await asyncio.sleep(delay)
        while True:
            try:
                self._queue_resolution(record_id, DECISION_TIMEOUT)
                return
            except asyncio.QueueFull:
                await asyncio.sleep(1)

    def _cancel_timer(self, record_id: str) -> None:
        timer = self._timers.pop(record_id, None)
        if timer is not None and timer is not asyncio.current_task():
            timer.cancel()

    async def _clear_question(self, message) -> None:
        if message is None:
            return
        try:
            await message.remove_reaction(QUESTION, self.bot_user)
        except Exception:
            log.debug("移除 ❓ 失敗", exc_info=True)

    # ------------------------------------------------------------ 啟動時接續、背景補登

    async def recover(self) -> None:
        """bot 剛啟動：接續關機前還在等確認的（計時重新開始，已過期的馬上處理），並補登暫存的資料。"""
        for record in self.svc.awaiting.all():
            self._start_timer(record.id)
        if self.svc.pending.all():
            self._queue_flush()

    async def pending_loop(self) -> None:
        while True:
            await asyncio.sleep(self.pending_interval)
            if self.mode == ACTIVE and self.svc.pending.all():
                self._queue_flush()

    def _queue_flush(self) -> None:
        if self._flush_queued:
            return
        try:
            self.queue.put_nowait(Job(None, 0, None, silent=True, kind="flush"))
            self._flush_queued = True
        except asyncio.QueueFull:
            pass  # 下一輪再試

    async def _flush_pending(self, *, force: bool = False) -> None:
        """把 pending/ 裡的資料由舊到新補寫進 Excel，每補完一筆就通知上傳者。Excel 仍被占用就先停。"""
        if not force and time.monotonic() < self._flush_blocked_until:
            return
        while True:
            try:
                records = self.svc.pending.all()
                if not records:
                    return
                record = records[0]
                outcome = await flush_pending_record(self.svc, record.id)
            except Exception:
                log.exception("補登暫存資料時發生未預期的錯誤")
                outcome, record = None, None
            if outcome is None:
                self._flush_blocked_until = time.monotonic() + self.pending_interval
                return
            await self._notify(record.meta, outcome)

    async def _notify(self, meta: dict, outcome: Outcome) -> None:
        target = self.get_message(meta["message_id"])
        if target is None:
            log.warning("已補登，但找不到原本那則訊息，無法通知上傳者")
            return
        try:
            await self._send_result(target, meta["uploader_id"], outcome)
        except Exception:
            log.exception("通知補登結果失敗")

    # ------------------------------------------------------------ 佇列

    async def _enqueue(self, message, work: Callable[[], Awaitable[Outcome]]) -> None:
        if self.queue.full():
            await message.reply(replies.QUEUE_FULL, mention_author=False)
            return
        ahead = self.queue.qsize() + (1 if self.busy else 0)
        try:
            await message.add_reaction(HOURGLASS)
        except Exception:
            log.warning("加 ⏳ 反應失敗（bot 可能缺少「新增反應」權限）")
        await message.reply(replies.queued(ahead) if ahead else replies.processing(), mention_author=False)
        try:
            self.queue.put_nowait(Job(message, message.author.id, work))
        except asyncio.QueueFull:
            await self._drop_hourglass(message)
            await message.reply(replies.QUEUE_FULL, mention_author=False)

    async def worker(self) -> None:
        """一次只處理一件，所以同一時間最多只有一個 claude -p 在跑。"""
        while True:
            job = await self.queue.get()
            self.busy = True
            try:
                if job.kind == "flush":
                    self._flush_queued = False
                    await self._flush_pending(force=True)
                    continue
                await self._flush_pending()  # 先補登之前暫存的，編號才會照先後順序
                try:
                    outcome = await job.work()
                except ExcelBusy:
                    outcome = Outcome(replies.FAIL_EXCEL)
                except Exception:
                    log.exception("處理工作時發生未預期的錯誤")
                    outcome = Outcome(replies.FAIL_ANALYSIS)
                if outcome is not None and job.message is not None:
                    try:
                        await self._send_result(job.message, job.uploader_id, outcome)
                    except Exception:
                        log.exception("回覆失敗")
            finally:
                if job.message is not None and not job.silent:
                    await self._drop_hourglass(job.message)
                self.busy = False
                self.queue.task_done()

    def _cancel_all_timers(self) -> None:
        for timer in self._timers.values():
            timer.cancel()
        self._timers.clear()

    def close(self) -> None:
        self._cancel_all_timers()

    # ------------------------------------------------------------ 回覆

    def get_message(self, message_id: int):
        return self._remembered.get(message_id) or (self._lookup(message_id) if self._lookup else None)

    async def _send_result(self, message, uploader_id: int, outcome: Outcome) -> None:
        # AI 產生的文字裡就算有 @everyone 或角色，也不會真的通知；只會提到上傳者
        allowed = discord.AllowedMentions(
            everyone=False, roles=False, users=[discord.Object(id=uploader_id)], replied_user=True,
        )
        first_sent = None
        for part in [outcome, *outcome.more]:
            text = f"<@{uploader_id}> {part.text}" if first_sent is None else part.text
            for chunk in replies.chunks(text):  # 太長就切成好幾則
                sent = await message.reply(chunk, mention_author=(first_sent is None), allowed_mentions=allowed)
                if first_sent is None:
                    first_sent = sent
                if part.asset_id is not None:
                    await self._remember_asset_message(part.asset_id, sent.id)

        if outcome.awaiting_id and first_sent is not None:
            self.svc.awaiting.update(outcome.awaiting_id, confirm_message_id=first_sent.id)
            self._remembered[message.id] = message
            try:
                await message.add_reaction(QUESTION)
            except Exception:
                log.warning("加 ❓ 反應失敗（bot 可能缺少「新增反應」權限）")
            self._start_timer(outcome.awaiting_id)
        if outcome.pending_id:
            self._remembered[message.id] = message

    async def _remember_asset_message(self, asset_id: int, message_id: int) -> None:
        try:  # 記下這則訊息屬於哪一筆，之後才能「回覆它」來補充、刪除、借出
            await asyncio.to_thread(self.svc.store.add_message_id, asset_id, message_id)
        except Exception:
            log.exception("無法記錄歸檔訊息 ID（之後回覆這則訊息可能找不到這一筆）")

    async def _drop_hourglass(self, message) -> None:
        try:
            await message.remove_reaction(HOURGLASS, self.bot_user)
        except Exception:
            log.debug("移除 ⏳ 失敗", exc_info=True)


class TroupeBot(discord.Client):
    def __init__(self, svc: Services):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True  # 要在 Developer Portal 另外打開，否則讀不到文字說明與附件
        super().__init__(intents=intents)
        self.svc = svc
        self.dispatcher: Dispatcher | None = None
        self._background: list[asyncio.Task] = []

    def _find_message(self, message_id: int):
        channel = self.get_channel(self.svc.cfg.channel_id)
        return channel.get_partial_message(message_id) if channel is not None else None

    async def on_ready(self) -> None:
        if self.dispatcher is None:
            # 一律從待命開始；awaiting/、pending/ 的接續留到管理員 !上線 時才做（Dispatcher.recover）
            self.dispatcher = Dispatcher(
                self.svc, bot_user=self.user, lookup=self._find_message,
                start_active=False, on_mode_change=self._apply_presence,
            )
            self._background = [
                asyncio.create_task(self.dispatcher.worker()),
                asyncio.create_task(self.dispatcher.pending_loop()),
            ]
        await self._apply_presence(self.dispatcher.mode)  # 重新連線後狀態燈才會跟著目前狀態
        channel = self.get_channel(self.svc.cfg.channel_id)
        if channel is None:
            log.warning("看不到 CHANNEL_ID 指定的頻道：請確認 ID 正確，且 bot 已加入那個 Server 並有「檢視頻道」權限")
        else:
            log.info("已連線（%s）：%s，監聽頻道 #%s。管理員在頻道輸入 !上線 才會開始處理",
                     "運作中" if self.dispatcher.mode == ACTIVE else "待命中", self.user, getattr(channel, "name", "?"))

    async def _apply_presence(self, mode: str) -> None:
        status, activity = presence_for(mode)
        await self.change_presence(status=status, activity=activity)

    async def on_message(self, message) -> None:
        if not message.author.bot:  # 診斷用：不管是不是監聽頻道都留一筆，才知道 bot 到底有沒有收到
            log.info(
                "收到訊息：頻道 #%s（%s）%s，附件 %d 個",
                getattr(message.channel, "name", "?"),
                message.channel.id,
                "＝監聽頻道" if message.channel.id == self.svc.cfg.channel_id else "≠監聽頻道，會略過",
                len(message.attachments),
            )
        if self.dispatcher is not None:
            try:
                await self.dispatcher.on_message(message)
            except Exception:
                log.exception("分流訊息時發生未預期的錯誤")
