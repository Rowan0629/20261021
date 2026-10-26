import asyncio
import io
import json
from dataclasses import dataclass, field
from datetime import datetime

import discord
import pytest
from PIL import Image

from troupe_bot import replies
from troupe_bot.bot import ACTIVE, STANDBY, STOPPING, Dispatcher, presence_for
from troupe_bot.claude_client import RunResult
from troupe_bot.config import Config
from troupe_bot.handlers import Services
from troupe_bot.store import Store

CHANNEL = 555
BOT_ID = 999
VASE = {
    "category": "小道具", "name": "青花瓷花瓶", "short_name": "青花瓷瓶", "features": "青花瓷", "scene": "古典室內景",
    "play": "《白蛇傳》", "quantity": 1, "quantity_source": "uploader", "condition": "良好", "condition_source": "ai",
    "location": "B區03箱", "remarks": "",
}


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (50, 40), (9, 9, 200)).save(buf, format="PNG")
    return buf.getvalue()


def envelope(payload) -> RunResult:
    return RunResult(0, json.dumps({"is_error": False, "structured_output": payload}, ensure_ascii=False).encode(), b"")


def one(item):
    """辨識結果：照片裡只有一種東西。"""
    return envelope({"items": [item]})


# ---------------------------------------------------------------- 假的 Discord 物件


@dataclass
class FakeUser:
    id: int
    display_name: str = "小明"
    bot: bool = False
    guild_permissions: object = None

    @property
    def mention(self):
        return f"<@{self.id}>"


class FakeAttachment:
    def __init__(self, filename="a.png", content_type="image/png", data=None, size=None):
        self.filename, self.content_type = filename, content_type
        self.data = png() if data is None else data
        self.size = len(self.data) if size is None else size

    async def read(self):
        return self.data


@dataclass
class FakeRef:
    message_id: int
    resolved: object = None


class FakeChannel:
    def __init__(self, id=CHANNEL):
        self.id = id


_ids = iter(range(1000, 10**6))


class FakeMessage:
    def __init__(self, content="", *, author=None, channel_id=CHANNEL, attachments=(), mentions=(), reference=None):
        self.id = next(_ids)
        self.content = content
        self.author = author or FakeUser(7)
        self.channel = FakeChannel(channel_id)
        self.attachments = list(attachments)
        self.mentions = list(mentions)
        self.reference = reference
        self.sent: list[FakeMessage] = []
        self.reply_calls: list[dict] = []
        self.reactions: set[str] = set()
        self.reaction_log: list[tuple[str, str]] = []

    async def reply(self, content, **kwargs):
        self.reply_calls.append({"content": content, **kwargs})
        sent = FakeMessage(content, author=FakeUser(BOT_ID, "bot", True))
        self.sent.append(sent)
        return sent

    async def add_reaction(self, emoji):
        self.reactions.add(emoji)
        self.reaction_log.append(("add", emoji))

    async def remove_reaction(self, emoji, member):
        self.reactions.discard(emoji)
        self.reaction_log.append(("remove", emoji))


class FakeRunner:
    def __init__(self, *responses, default=None, gate=None):
        self.responses = list(responses)
        self.default = default
        self.gate = gate
        self.running = self.max_running = 0
        self.texts: list[str] = []

    async def __call__(self, args, stdin, cwd, timeout):
        self.running += 1
        self.max_running = max(self.max_running, self.running)
        try:
            for p in cwd.iterdir():
                if p.suffix == ".txt":
                    self.texts.append(p.read_text(encoding="utf-8"))
            if self.gate is not None:
                await self.gate.wait()
            await asyncio.sleep(0)
            response = self.responses.pop(0) if self.responses else self.default
            if isinstance(response, Exception):
                raise response
            return response
        finally:
            self.running -= 1


@pytest.fixture
def svc(tmp_path):
    cfg = Config(discord_token="x", channel_id=CHANNEL, claude_model="haiku", data_dir=tmp_path / "data", claude_path="claude.exe")
    cfg.data_dir.mkdir()
    store = Store(cfg.xlsx_path, retries=1, delay=0, sleep=lambda s: None, warn=lambda m: None)
    store.ensure()
    return Services(cfg=cfg, store=store, now=lambda: datetime(2026, 10, 22, 14, 5, 9))


BOT = FakeUser(BOT_ID, "bot", True)


def drive(svc, runner, scenario, *, queue_max=50, with_loop=False, recover=False, **dispatcher_kwargs):
    """啟動 worker，跑 scenario(dispatcher)，等佇列清空再收掉 worker。

    with_loop：同時跑「每隔一段時間補登 pending/」的背景工作；recover：像 bot 剛啟動那樣接續 awaiting/ 與 pending/。
    """
    svc.runner = runner

    async def main():
        d = Dispatcher(svc, bot_user=BOT, queue_max=queue_max, **dispatcher_kwargs)
        tasks = [asyncio.create_task(d.worker())]
        if with_loop:
            tasks.append(asyncio.create_task(d.pending_loop()))
        try:
            if recover:
                await d.recover()
            await scenario(d)
            await d.queue.join()
        finally:
            for task in tasks:
                task.cancel()
            d.close()
        return d

    return asyncio.run(main())


def photo_msg(text="", **kw):
    return FakeMessage(text, attachments=[FakeAttachment()], **kw)


# ---------------------------------------------------------------- 來源檢查與分流


def test_messages_from_bots_other_channels_or_plain_chat_are_ignored(svc):
    msgs = [
        FakeMessage("", author=FakeUser(1, bot=True), attachments=[FakeAttachment()]),
        FakeMessage("", channel_id=1, attachments=[FakeAttachment()]),
        FakeMessage("大家午餐吃什麼"),
        FakeMessage("看這個", attachments=[FakeAttachment("notes.txt", "text/plain", b"hi")]),
    ]

    async def scenario(d):
        for m in msgs:
            await d.on_message(m)

    runner = FakeRunner(default=one(VASE))
    drive(svc, runner, scenario)
    assert all(m.reply_calls == [] and m.reactions == set() for m in msgs)
    assert svc.store.all_rows() == []


def test_photo_gets_hourglass_then_processing_then_result_and_hourglass_is_removed(svc):
    msg = photo_msg("放 B區03箱")

    async def scenario(d):
        await d.on_message(msg)
        assert "⏳" in msg.reactions and msg.reply_calls[0]["content"] == replies.processing()

    drive(svc, FakeRunner(one(VASE)), scenario)
    assert "⏳" not in msg.reactions
    assert msg.reaction_log == [("add", "⏳"), ("remove", "⏳")]
    result = msg.reply_calls[1]
    assert result["content"].startswith("<@7> ") and "已成功入庫" in result["content"]
    assert len(svc.store.all_rows()) == 1


def test_result_may_only_ping_the_uploader(svc):
    msg = photo_msg()
    drive(svc, FakeRunner(one(VASE)), lambda d: d.on_message(msg))
    allowed = msg.reply_calls[1]["allowed_mentions"]
    assert allowed.everyone is False and allowed.roles is False
    assert [u.id for u in allowed.users] == [7]


def test_result_message_id_is_remembered_so_replies_can_find_the_row(svc):
    msg = photo_msg()
    drive(svc, FakeRunner(one(VASE)), lambda d: d.on_message(msg))
    assert svc.store.find_by_message(msg.sent[1].id).name == "青花瓷花瓶"


def test_too_many_or_too_big_photos_are_refused_before_queueing(svc):
    many = FakeMessage("", attachments=[FakeAttachment() for _ in range(6)])
    big = FakeMessage("", attachments=[FakeAttachment(size=11 * 1024 * 1024)])

    async def scenario(d):
        await d.on_message(many)
        await d.on_message(big)

    drive(svc, FakeRunner(default=one(VASE)), scenario)
    assert many.reply_calls[0]["content"] == replies.TOO_MANY_PHOTOS and many.reactions == set()
    assert big.reply_calls[0]["content"] == replies.TOO_BIG
    assert svc.store.all_rows() == []


def test_unsupported_image_type_gets_an_explanation(svc):
    msg = FakeMessage("", attachments=[FakeAttachment("x.heic", "image/heic", b"not really")])
    drive(svc, FakeRunner(default=one(VASE)), lambda d: d.on_message(msg))
    assert msg.reply_calls[-1]["content"].endswith(replies.UNSUPPORTED_IMAGE)
    assert svc.store.all_rows() == []


# ---------------------------------------------------------------- 佇列


def test_only_one_claude_runs_at_a_time(svc):
    msgs = [photo_msg() for _ in range(4)]

    async def scenario(d):
        for m in msgs:
            await d.on_message(m)

    runner = FakeRunner(default=one(VASE))
    drive(svc, runner, scenario)
    assert runner.max_running == 1
    assert len(svc.store.all_rows()) == 4


def test_second_uploader_is_told_how_many_are_ahead(svc):
    first, second, third = photo_msg(), photo_msg(), photo_msg()

    async def scenario(d):
        gate = svc.runner.gate
        await d.on_message(first)
        await asyncio.sleep(0.05)  # 讓 worker 開始處理第一件
        await d.on_message(second)
        await d.on_message(third)
        gate.set()

    gate = asyncio.Event()
    drive(svc, FakeRunner(default=one(VASE), gate=gate), scenario)
    assert first.reply_calls[0]["content"] == replies.processing()
    assert second.reply_calls[0]["content"] == replies.queued(1)
    assert third.reply_calls[0]["content"] == replies.queued(2)


def test_full_queue_refuses_new_work_without_a_hourglass(svc):
    msgs = [photo_msg() for _ in range(4)]

    async def scenario(d):
        for m in msgs:
            await d.on_message(m)
        svc.runner.gate.set()

    gate = asyncio.Event()
    drive(svc, FakeRunner(default=one(VASE), gate=gate), scenario, queue_max=1)
    refused = [m for m in msgs if m.reply_calls and m.reply_calls[0]["content"] == replies.QUEUE_FULL]
    assert refused and all("⏳" not in m.reactions and m.reaction_log == [] for m in refused)


def test_a_crashing_job_does_not_kill_the_worker(svc):
    first, second = photo_msg(), photo_msg()

    async def scenario(d):
        await d.on_message(first)
        await d.on_message(second)

    drive(svc, FakeRunner(RuntimeError("boom"), one(VASE)), scenario)
    assert replies.FAIL_ANALYSIS in first.reply_calls[-1]["content"]
    assert "已成功入庫" in second.reply_calls[-1]["content"]
    assert first.reactions == set() and second.reactions == set()


# ---------------------------------------------------------------- 回覆與查詢


def archived(svc):
    msg = photo_msg()
    drive(svc, FakeRunner(one(VASE)), lambda d: d.on_message(msg))
    return msg.sent[1]


def test_replying_to_an_archive_message_updates_that_row(svc):
    archive_msg = archived(svc)
    reply = FakeMessage("其實放在後台A衣箱", author=FakeUser(8, "阿華"), reference=FakeRef(archive_msg.id), mentions=[BOT])
    drive(svc, FakeRunner(envelope({"location": "後台A衣箱"})), lambda d: d.on_message(reply))
    row = svc.store.all_rows()[0]
    assert (row.location, row.updated_by) == ("後台A衣箱", "阿華")
    assert svc.store.find_by_message(reply.sent[1].id).id == row.id  # 也能回覆「已更新」那則


def test_replying_with_the_word_delete_marks_the_row_deleted(svc):
    archive_msg = archived(svc)
    reply = FakeMessage("刪除", reference=FakeRef(archive_msg.id), mentions=[BOT])
    runner = FakeRunner()
    drive(svc, runner, lambda d: d.on_message(reply))
    assert svc.store.all_rows()[0].status == "已刪除" and runner.texts == []


def test_replying_to_some_other_bot_message_is_ignored_even_though_it_pings_the_bot(svc):
    placeholder = FakeMessage("處理中…", author=BOT)
    reply = FakeMessage("好慢喔", reference=FakeRef(placeholder.id, resolved=placeholder), mentions=[BOT])
    runner = FakeRunner(default=envelope({}))
    drive(svc, runner, lambda d: d.on_message(reply))
    assert reply.reply_calls == [] and runner.texts == []


def test_mentioning_the_bot_runs_a_query_with_the_mention_removed(svc):
    archived(svc)
    ask = FakeMessage(f"<@{BOT_ID}> 找青花瓷", mentions=[BOT])
    runner = FakeRunner(envelope({"keywords": ["青花瓷"]}))
    drive(svc, runner, lambda d: d.on_message(ask))
    assert runner.texts == ["找青花瓷"]
    assert "青花瓷花瓶" in ask.reply_calls[-1]["content"]


def test_mention_with_no_question_gets_the_hint_without_calling_claude(svc):
    ask = FakeMessage(f"<@{BOT_ID}>", mentions=[BOT])
    runner = FakeRunner(default=envelope({}))
    drive(svc, runner, lambda d: d.on_message(ask))
    assert ask.reply_calls[0]["content"] == replies.NO_QUERY and runner.texts == [] and ask.reactions == set()


# ============================================================ 🆕 一張照片有多種東西：確認、逾時、重啟接續

TEAPOT = {**VASE, "name": "青花瓷茶壺", "short_name": "茶壺"}
FAN = {**VASE, "name": "摺扇", "short_name": "摺扇"}
LANTERN = {**VASE, "name": "紅燈籠", "short_name": "燈籠"}
COMBINED = {**VASE, "name": "桌上陳設一組", "short_name": "桌上陳設"}


def several(*items):
    return envelope({"items": list(items), "combined": COMBINED})


def uploader_reply(text, confirm, *, author_id=7, mention_bot=False):
    return FakeMessage(
        text, author=FakeUser(author_id, "小明" if author_id == 7 else "路人"), reference=FakeRef(confirm.id, resolved=confirm),
        mentions=[BOT] if mention_bot else [],
    )


def test_several_things_get_a_question_a_question_mark_reaction_and_no_row_yet(svc):
    msg = photo_msg("放 B區03箱")
    drive(svc, FakeRunner(several(TEAPOT, FAN)), lambda d: d.on_message(msg))
    confirm = msg.sent[1]
    assert "2 種東西" in confirm.content and "分開" in confirm.content and "合併" in confirm.content
    assert msg.reactions == {"❓"} and msg.reaction_log == [("add", "⏳"), ("add", "❓"), ("remove", "⏳")]
    assert svc.store.all_rows() == []
    [rec] = svc.awaiting.all()
    assert rec.meta["confirm_message_id"] == confirm.id and rec.meta["message_id"] == msg.id


def test_the_uploader_answering_split_stores_every_thing_and_replies_once_each(svc):
    msg = photo_msg("放 B區03箱")

    async def scenario(d):
        await d.on_message(msg)
        await d.queue.join()
        await d.on_message(uploader_reply("分開", msg.sent[1]))

    drive(svc, FakeRunner(several(TEAPOT, FAN, LANTERN)), scenario)
    assert [r.name for r in svc.store.all_rows()] == ["青花瓷茶壺", "摺扇", "紅燈籠"]
    results = msg.sent[2:]
    assert len(results) == 3 and all("已成功入庫" in m.content for m in results)
    assert "倉庫目前共" not in results[0].content and "倉庫目前共 3 筆" in results[2].content
    for row, sent in zip(svc.store.all_rows(), results):
        assert svc.store.find_by_message(sent.id).id == row.id  # 之後回覆哪一則，就是更正哪一件
    assert msg.reactions == set() and svc.awaiting.all() == []


def test_answering_merge_stores_one_combined_row(svc):
    msg = photo_msg()

    async def scenario(d):
        await d.on_message(msg)
        await d.queue.join()
        await d.on_message(uploader_reply("合併", msg.sent[1]))

    drive(svc, FakeRunner(several(TEAPOT, FAN)), scenario)
    [row] = svc.store.all_rows()
    assert (row.name, row.intake_mode) == ("桌上陳設一組", "合併（上傳者確認）")


def test_only_the_uploader_can_answer_and_other_text_is_not_an_answer_or_a_query(svc):
    msg = photo_msg()
    outsider = {}

    async def scenario(d):
        await d.on_message(msg)
        await d.queue.join()
        confirm = msg.sent[1]
        outsider["a"] = uploader_reply("分開", confirm, author_id=8, mention_bot=True)
        outsider["b"] = uploader_reply("先等等", confirm, mention_bot=True)
        await d.on_message(outsider["a"])
        await d.on_message(outsider["b"])

    runner = FakeRunner(several(TEAPOT, FAN), default=envelope({"keywords": ["x"]}))
    drive(svc, runner, scenario)
    assert svc.store.all_rows() == [] and len(svc.awaiting.all()) == 1
    assert outsider["a"].reply_calls == [] and outsider["b"].reply_calls == []
    assert runner.texts == []  # 沒有人的話被當成查詢送給 claude


def test_no_answer_within_the_time_splits_automatically_and_labels_it(svc):
    svc.awaiting_timeout = 0.1
    msg = photo_msg()

    async def scenario(d):
        await d.on_message(msg)
        await asyncio.sleep(0.4)

    drive(svc, FakeRunner(several(TEAPOT, FAN)), scenario)
    rows = svc.store.all_rows()
    assert len(rows) == 2 and {r.intake_mode for r in rows} == {"分開（AI 判定）"}
    assert len(msg.sent) == 2 + 2 and msg.reactions == set()


def test_an_early_answer_cancels_the_timer_so_nothing_is_stored_twice(svc):
    svc.awaiting_timeout = 0.2
    msg = photo_msg()

    async def scenario(d):
        await d.on_message(msg)
        await d.queue.join()
        await d.on_message(uploader_reply("合併", msg.sent[1]))
        await asyncio.sleep(0.5)

    drive(svc, FakeRunner(several(TEAPOT, FAN)), scenario)
    assert len(svc.store.all_rows()) == 1


def test_a_question_that_was_waiting_when_the_bot_restarted_is_picked_up_again(svc):
    msg = photo_msg()
    drive(svc, FakeRunner(several(TEAPOT, FAN)), lambda d: d.on_message(msg))
    [rec] = svc.awaiting.all()
    assert svc.store.all_rows() == []

    svc.awaiting.update(rec.id, deadline=0)  # 關機期間已經過了截止時間
    messages = {msg.id: msg}

    async def scenario(d):
        await asyncio.sleep(0.3)

    drive(svc, FakeRunner(), scenario, recover=True, lookup=messages.get)
    assert {r.intake_mode for r in svc.store.all_rows()} == {"分開（AI 判定）"} and len(svc.store.all_rows()) == 2
    assert len(msg.sent) > 2  # 結果回覆在原來那則照片底下


def test_a_question_still_inside_its_time_after_a_restart_keeps_waiting(svc):
    msg = photo_msg()
    drive(svc, FakeRunner(several(TEAPOT, FAN)), lambda d: d.on_message(msg))
    messages = {msg.id: msg}

    async def scenario(d):
        await asyncio.sleep(0.2)

    drive(svc, FakeRunner(), scenario, recover=True, lookup=messages.get)
    assert svc.store.all_rows() == [] and len(svc.awaiting.all()) == 1


# ============================================================ 🆕 Excel 被占用：先收下，晚點自動補登

def lock_excel(monkeypatch):
    """只有 inventory.xlsx 被鎖住（像 Excel 開著它）；其他檔案照常可以寫。"""
    import os

    import troupe_bot.store as store_mod

    real_replace = os.replace

    def replace(src, dst):
        if str(dst).endswith("inventory.xlsx"):
            raise PermissionError("locked")
        return real_replace(src, dst)

    monkeypatch.setattr(store_mod.os, "replace", replace)


def test_a_locked_excel_answers_got_it_instead_of_failing(svc, monkeypatch):
    lock_excel(monkeypatch)
    msg = photo_msg()
    drive(svc, FakeRunner(one(VASE)), lambda d: d.on_message(msg))
    assert replies.PENDING_NOTICE in msg.sent[1].content and replies.FAIL_EXCEL not in msg.sent[1].content
    assert msg.reactions == set() and len(svc.pending.all()) == 1


def test_pending_data_is_filled_in_and_the_uploader_is_told_once_excel_is_free(svc, monkeypatch):
    lock_excel(monkeypatch)
    msg = photo_msg("放 B區03箱")
    messages = {msg.id: msg}

    async def scenario(d):
        await d.on_message(msg)
        await d.queue.join()
        monkeypatch.undo()  # 把 Excel 關掉了
        await asyncio.sleep(0.3)

    drive(svc, FakeRunner(one(VASE)), scenario, with_loop=True, pending_interval=0.05, lookup=messages.get)
    [row] = svc.store.all_rows()
    assert row.name == "青花瓷花瓶" and svc.pending.all() == []
    done = msg.sent[-1]
    assert "補登" in done.content and "已成功入庫" in done.content and done.content.startswith("<@7> ")
    assert svc.store.find_by_message(done.id).id == row.id


def test_pending_data_is_written_before_the_next_new_upload_so_ids_follow_arrival_order(svc, monkeypatch):
    lock_excel(monkeypatch)
    first, second = photo_msg(), photo_msg()
    messages = {first.id: first, second.id: second}

    async def scenario(d):
        await d.on_message(first)
        await d.queue.join()
        monkeypatch.undo()
        await d.on_message(second)

    runner = FakeRunner(one({**VASE, "name": "先到的"}), one({**VASE, "name": "後到的", "short_name": "後到"}))
    drive(svc, runner, scenario, lookup=messages.get)
    assert [(r.id, r.name) for r in svc.store.all_rows()] == [(1, "先到的"), (2, "後到的")]


def test_pending_data_found_at_startup_is_filled_in_right_away(svc, monkeypatch):
    lock_excel(monkeypatch)
    msg = photo_msg()
    drive(svc, FakeRunner(one(VASE)), lambda d: d.on_message(msg))
    monkeypatch.undo()
    messages = {msg.id: msg}

    async def scenario(d):
        await asyncio.sleep(0.2)

    drive(svc, FakeRunner(), scenario, recover=True, lookup=messages.get)
    assert len(svc.store.all_rows()) == 1 and svc.pending.all() == []


# ============================================================ 🆕 長回覆分段、借出

def test_a_very_long_reply_is_split_into_several_messages_and_each_can_be_replied_to(svc):
    msg = photo_msg()
    long_item = {**VASE, "features": "長" * 1000, "remarks": "備" * 1000}
    drive(svc, FakeRunner(one(long_item)), lambda d: d.on_message(msg))
    parts = msg.sent[1:]
    assert len(parts) >= 2 and all(len(p.content) <= 2000 for p in parts)
    assert all(svc.store.find_by_message(p.id) is not None for p in parts)
    assert parts[0].content.startswith("<@7> ") and not parts[1].content.startswith("<@7> ")


def test_replying_lend_and_return_through_the_dispatcher(svc):
    archive_msg = archived(svc)
    lend = FakeMessage("借出 王小明", author=FakeUser(8, "阿華"), reference=FakeRef(archive_msg.id), mentions=[BOT])
    back = FakeMessage("歸還", author=FakeUser(8, "阿華"), reference=FakeRef(archive_msg.id), mentions=[BOT])
    runner = FakeRunner()

    async def scenario(d):
        await d.on_message(lend)
        await d.queue.join()
        assert svc.store.all_rows()[0].borrower == "王小明"
        await d.on_message(back)

    drive(svc, runner, scenario)
    assert "王小明" in lend.sent[1].content and "已歸還" in back.sent[1].content
    assert svc.store.all_rows()[0].borrower == "" and runner.texts == []
    assert svc.store.find_by_message(lend.sent[1].id).id == 1


# ============================================================ 🆕 聊天室指令上線／下線


@dataclass
class FakePerms:
    manage_guild: bool


def admin(id=1) -> FakeUser:
    return FakeUser(id, "管理員", guild_permissions=FakePerms(True))


def cmd(text, *, author=None, channel_id=CHANNEL) -> FakeMessage:
    return FakeMessage(text, author=author or admin(), channel_id=channel_id)


def test_standby_ignores_photos_mentions_and_replies_silently(svc):
    archive_msg = archived(svc)
    photo = photo_msg()
    ask = FakeMessage("找青花瓷", mentions=[BOT])
    edit = FakeMessage("放在後台A衣箱", author=FakeUser(8, "阿華"), reference=FakeRef(archive_msg.id), mentions=[BOT])
    runner = FakeRunner(default=one(VASE))

    async def scenario(d):
        for m in (photo, ask, edit):
            await d.on_message(m)

    drive(svc, runner, scenario, start_active=False)
    assert all(m.reply_calls == [] and m.reactions == set() for m in (photo, ask, edit))
    assert len(svc.store.all_rows()) == 1 and runner.texts == []  # 只有 archived() 事先建的那一筆


def test_admin_online_switches_to_active_and_photos_are_processed(svc):
    up, photo = cmd("!上線"), photo_msg("放 B區03箱")

    async def scenario(d):
        await d.on_message(up)
        assert d.mode == ACTIVE
        await d.on_message(photo)

    drive(svc, FakeRunner(one(VASE)), scenario, start_active=False)
    assert up.reply_calls[0]["content"] == replies.ONLINE
    assert len(svc.store.all_rows()) == 1


def test_full_width_exclamation_is_accepted(svc):
    d = drive(svc, FakeRunner(), lambda d: d.on_message(cmd("！上線")), start_active=False)
    assert d.mode == ACTIVE


def test_command_with_extra_text_is_not_a_command(svc):
    msg = cmd("!上線 好嗎")
    d = drive(svc, FakeRunner(), lambda d: d.on_message(msg), start_active=False)
    assert d.mode == STANDBY and msg.reply_calls == []


def test_non_admin_command_is_refused_and_state_unchanged(svc):
    stranger = FakeUser(7)
    up, down = cmd("!上線", author=stranger), cmd("!下線", author=stranger)
    d = drive(svc, FakeRunner(), lambda d: d.on_message(up), start_active=False)
    assert up.reply_calls[0]["content"] == replies.ADMIN_ONLY and d.mode == STANDBY
    d = drive(svc, FakeRunner(), lambda d: d.on_message(down))
    assert down.reply_calls[0]["content"] == replies.ADMIN_ONLY and d.mode == ACTIVE


def test_command_from_other_channel_or_a_bot_is_ignored(svc):
    elsewhere, robot = cmd("!上線", channel_id=1), cmd("!上線", author=FakeUser(1, bot=True))

    async def scenario(d):
        await d.on_message(elsewhere)
        await d.on_message(robot)

    d = drive(svc, FakeRunner(), scenario, start_active=False)
    assert d.mode == STANDBY and elsewhere.reply_calls == [] and robot.reply_calls == []


def test_repeated_commands_get_a_plain_answer(svc):
    again, already = cmd("!上線"), cmd("!下線")
    d = drive(svc, FakeRunner(), lambda d: d.on_message(again))
    assert again.reply_calls[0]["content"] == replies.ALREADY_ONLINE and d.mode == ACTIVE
    d = drive(svc, FakeRunner(), lambda d: d.on_message(already), start_active=False)
    assert already.reply_calls[0]["content"] == replies.ALREADY_STANDBY and d.mode == STANDBY


def test_going_offline_waits_for_running_work_then_replies_offline(svc):
    gate = asyncio.Event()
    first, second, down = photo_msg(), photo_msg(), cmd("!下線")

    async def scenario(d):
        await d.on_message(first)
        await asyncio.sleep(0.05)  # worker 卡在 gate 裡，第一張還在處理
        task = asyncio.create_task(d.on_message(down))
        await asyncio.sleep(0.05)
        assert d.mode == STOPPING and down.reply_calls == []
        await d.on_message(second)
        assert second.reply_calls == [] and second.reactions == set()
        gate.set()
        await task

    d = drive(svc, FakeRunner(one(VASE), gate=gate), scenario)
    assert down.reply_calls[0]["content"] == replies.OFFLINE and d.mode == STANDBY
    assert len(svc.store.all_rows()) == 1


def test_online_during_stopping_cancels_the_shutdown(svc):
    gate = asyncio.Event()
    first, down, back = photo_msg(), cmd("!下線"), cmd("!上線", author=admin(2))

    async def scenario(d):
        await d.on_message(first)
        await asyncio.sleep(0.05)
        task = asyncio.create_task(d.on_message(down))
        await asyncio.sleep(0.05)
        await d.on_message(back)
        gate.set()
        await task

    d = drive(svc, FakeRunner(one(VASE), gate=gate), scenario)
    assert back.reply_calls[0]["content"] == replies.CANCELLED_OFFLINE
    assert down.reply_calls == [] and d.mode == ACTIVE


def test_offline_again_while_stopping_says_so(svc):
    gate = asyncio.Event()
    first, down, again = photo_msg(), cmd("!下線"), cmd("!下線", author=admin(2))

    async def scenario(d):
        await d.on_message(first)
        await asyncio.sleep(0.05)
        task = asyncio.create_task(d.on_message(down))
        await asyncio.sleep(0.05)
        await d.on_message(again)
        gate.set()
        await task

    drive(svc, FakeRunner(one(VASE), gate=gate), scenario)
    assert again.reply_calls[0]["content"] == replies.STOPPING_NOW


def test_awaiting_timer_is_stopped_in_standby_and_restarted_once_on_going_online(svc):
    svc.awaiting_timeout = 0.3
    msg = photo_msg()

    async def scenario(d):
        await d.on_message(msg)
        await d.queue.join()
        await d.on_message(cmd("!下線"))
        assert d.mode == STANDBY and d._timers == {}
        await asyncio.sleep(0.5)  # 超過期限，但待命中不會自動分開
        assert svc.store.all_rows() == []
        await d.on_message(cmd("!上線"))
        await asyncio.sleep(0.2)
        assert len(svc.store.all_rows()) == 2
        await d.on_message(cmd("!下線"))
        await d.on_message(cmd("!上線"))
        await asyncio.sleep(0.2)

    drive(svc, FakeRunner(several(TEAPOT, FAN)), scenario)
    assert len(svc.store.all_rows()) == 2


def test_pending_data_waits_in_standby_and_is_filled_in_after_going_online(svc, monkeypatch):
    lock_excel(monkeypatch)
    msg = photo_msg("放 B區03箱")
    messages = {msg.id: msg}

    async def scenario(d):
        await d.on_message(msg)
        await d.queue.join()
        assert len(svc.pending.all()) == 1
        await d.on_message(cmd("!下線"))
        monkeypatch.undo()  # Excel 關掉了
        await asyncio.sleep(0.3)
        assert len(svc.pending.all()) == 1 and svc.store.all_rows() == []
        await d.on_message(cmd("!上線"))
        await asyncio.sleep(0.3)

    drive(svc, FakeRunner(one(VASE)), scenario, with_loop=True, pending_interval=0.05, lookup=messages.get)
    assert svc.pending.all() == [] and len(svc.store.all_rows()) == 1


def test_standby_shows_idle_with_a_hint():
    status, activity = presence_for(STANDBY)
    assert status == discord.Status.idle
    assert activity.name == "待命中，管理員輸入 !上線"


def test_active_and_stopping_show_online_without_activity():
    assert presence_for(ACTIVE) == (discord.Status.online, None)
    assert presence_for(STOPPING) == (discord.Status.online, None)
