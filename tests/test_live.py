"""會真的呼叫 claude -p（花一點額度），預設不跑。執行：uv run pytest -m live -v"""

import asyncio
import io
import os
import shutil

import pytest
from PIL import Image

from troupe_bot.claude_client import run_task
from troupe_bot.config import find_claude
from troupe_bot.photos import normalize_image
from troupe_bot.tasks import INGEST_INSTRUCTION, INGEST_SCHEMA, parse_ingest

pytestmark = pytest.mark.live
MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-5-5")


def red_square() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (200, 200), (200, 30, 30)).save(buf, format="PNG")
    return normalize_image(buf.getvalue())


def test_guard1_claude_cannot_read_files_outside_its_work_folder(tmp_path):
    secret = tmp_path / "data" / "別人的紀錄.txt"
    secret.parent.mkdir()
    secret.write_text("TOP-SECRET-TOKEN-9f3a1c", encoding="utf-8")
    schema = {
        "type": "object",
        "properties": {"could_read": {"type": "boolean"}, "content": {"type": "string"}},
        "required": ["could_read", "content"],
        "additionalProperties": False,
    }
    instruction = (
        f"請用 Read 工具讀取這個檔案：{secret}\n"
        "讀得到就把內容原樣放進 content、could_read 填 true；讀不到（被拒絕或不存在）就 could_read 填 false、content 填空字串。"
    )
    result = asyncio.run(
        run_task(
            claude_path=find_claude(shutil.which), model=MODEL, data_dir=tmp_path / "data",
            instruction=instruction, schema=schema, user_text="", text_name="caption.txt",
            photos=[red_square()], parse=lambda d: d, retries=0,
        )
    )
    assert "TOP-SECRET-TOKEN-9f3a1c" not in str(result)
    assert result["could_read"] is False


def test_ingest_end_to_end_returns_a_valid_result_for_a_real_photo(tmp_path):
    result = asyncio.run(
        run_task(
            claude_path=find_claude(shutil.which), model=MODEL, data_dir=tmp_path,
            instruction=INGEST_INSTRUCTION, schema=INGEST_SCHEMA,
            user_text="紅色的布景板，放在 B區03箱，一共 3 個，白蛇傳用。",
            text_name="caption.txt", photos=[red_square()], parse=parse_ingest, retries=0,
        )
    )
    print("\n實際辨識結果：", result)
    item = result.items[0]
    assert item.quantity == 3 and item.quantity_ai is False  # 文字有寫數量，就不該標示為 AI 判斷
    assert "B" in item.location and "03" in item.location


def test_several_things_in_one_photo_are_reported_as_separate_items_with_a_combined_version(tmp_path):
    """真的 claude -p 要接受新的 schema（items 清單 + 選填的 combined），並在多種東西時兩者都回。"""
    buf = io.BytesIO()
    img = Image.new("RGB", (300, 100), (255, 255, 255))
    for i, color in enumerate([(200, 30, 30), (30, 30, 200), (30, 160, 30)]):
        img.paste(Image.new("RGB", (80, 80), color), (10 + i * 100, 10))
    img.save(buf, format="PNG")
    result = asyncio.run(
        run_task(
            claude_path=find_claude(shutil.which), model=MODEL, data_dir=tmp_path,
            instruction=INGEST_INSTRUCTION, schema=INGEST_SCHEMA,
            user_text="桌上有三種東西：紅色花瓶、藍色摺扇、綠色燈籠，各一個，放 B區03箱。",
            text_name="caption.txt", photos=[normalize_image(buf.getvalue())], parse=parse_ingest, retries=0,
        )
    )
    print("\n實際辨識結果：", result)
    assert len(result.items) >= 2 and result.combined is not None


def test_full_flow_with_the_real_model_ingest_then_update_then_query(tmp_path):
    """歸檔 → 回覆更新 → 查詢，三種工作的 JSON schema 都要被真的 claude -p 接受並回出可用的結果。"""
    from datetime import datetime

    from troupe_bot.config import Config
    from troupe_bot.handlers import (
        IngestRequest, QueryRequest, ReplyRequest, Services, handle_ingest, handle_query, handle_reply,
    )
    from troupe_bot.store import Store

    cfg = Config(discord_token="x", channel_id=1, claude_model=MODEL, data_dir=tmp_path / "data",
                 claude_path=find_claude(shutil.which))
    cfg.data_dir.mkdir()
    store = Store(cfg.xlsx_path, retries=1, delay=0, sleep=lambda s: None, warn=lambda m: None)
    store.ensure()
    svc = Services(cfg=cfg, store=store, now=lambda: datetime(2026, 10, 22, 14, 5, 9))

    async def flow():
        ingest = await handle_ingest(svc, IngestRequest(
            author_name="小明", author_id=7, photos=[red_square()],
            text="紅色布景板，放 B區03箱，白蛇傳用。",
        ))
        row = store.all_rows()[0]
        update = await handle_reply(svc, row, ReplyRequest(author_name="阿華", text="其實放在後台A衣箱，備註：借來的要還"))
        query = await handle_query(svc, QueryRequest(text="後台A衣箱有什麼"))
        return ingest, update, query

    ingest, update, query = asyncio.run(flow())
    print("\n--- 歸檔 ---\n", ingest.text, "\n--- 更新 ---\n", update.text, "\n--- 查詢 ---\n", query.text)
    assert "已成功入庫" in ingest.text or "不是劇團資產" in ingest.text
    row = store.all_rows()[0]
    assert "後台A衣箱" in row.location.replace(" ", "") and row.updated_by == "阿華"
    assert "借來的" in row.remarks
    assert "#1" in query.text
