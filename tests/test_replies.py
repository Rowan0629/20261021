from troupe_bot import replies
from troupe_bot.store import AssetRow


def row(**over) -> AssetRow:
    base = dict(
        id=12, name="青花瓷花瓶", category="小道具", features="青花瓷、高30公分", scene="古典室內景",
        play="《白蛇傳》", quantity=2, condition="良好", location="B區03箱",
    )
    base.update(over)
    return AssetRow(**base)


def archive(r=None, **over):
    args = dict(total=128, same_count=1, same_others=[], duplicates=[])
    args.update(over)
    return replies.archive(r or row(), **args)


def test_archive_reply_shows_every_field_the_requirements_list():
    text = archive()
    for needle in ("已成功入庫", "#12", "小道具", "青花瓷花瓶", "青花瓷、高30公分", "古典室內景", "B區03箱", "《白蛇傳》", "良好"):
        assert needle in text
    assert "128" in text


def test_ai_judged_condition_is_labelled():
    assert "AI" in archive(row(condition_ai=True))
    assert "AI" not in archive(row(condition_ai=False))


def test_remarks_line_only_when_there_are_remarks():
    assert "備註" not in archive()
    assert "借來的，要還" in archive(row(remarks="借來的，要還"))


def test_missing_location_hint():
    assert "可回覆本訊息補充" in archive(row(location="未指定"))
    assert "可回覆本訊息補充" not in archive()


def test_duplicate_warning_names_the_earlier_entry():
    text = archive(duplicates=[row(id=3, name="青花瓷瓶")])
    assert "可能與第 3 筆" in text and "青花瓷瓶" in text


def test_same_location_line_lists_other_items():
    others = [row(id=2, name="扇子"), row(id=1, name="燈籠")]
    text = archive(same_count=3, same_others=others)
    assert "B區03箱目前共 3 件" in text and "扇子" in text and "燈籠" in text


def test_same_location_line_says_when_the_list_is_cut_short():
    others = [row(id=i, name=f"物{i}") for i in range(5)]
    assert "等" in archive(same_count=9, same_others=others)


def test_unspecified_location_group_has_its_own_wording():
    text = archive(row(location="未指定"), same_count=2, same_others=[row(id=1, name="扇子", location="未指定")])
    assert "位置未指定的物品目前共 2 件" in text


def test_non_asset_reply_names_what_it_actually_is():
    text = replies.non_asset(row(category="非劇團資產", name="馬克杯", features="白色陶瓷馬克杯"), total=5)
    assert "你傳的不是劇團資產，是馬克杯" in text and "已建檔" in text and "5" in text


def test_updated_and_deleted_replies():
    assert "已更新" in replies.updated(row()) and "後台" in replies.updated(row(location="後台A衣箱"))
    assert "已刪除" in replies.deleted(row()) and "#12" in replies.deleted(row())


def test_query_lines_are_compact_and_show_the_total():
    text = replies.query_result(15, [row(remarks="借來的")], limit=10)
    assert "共 15 筆" in text and "只列出前 10 筆" in text
    assert "#12" in text and "青花瓷花瓶" in text and "x2" in text and "借來的" in text


def test_query_without_hits():
    assert replies.query_result(0, [], limit=10) == "找不到符合的紀錄"


def test_processing_and_queue_messages():
    assert replies.processing() == "處理中…"
    assert "前面還有 3 件" in replies.queued(3)


def test_fit_truncates_to_discords_limit():
    assert len(replies.fit("字" * 5000)) <= 2000
    assert replies.fit("短") == "短"


# ------------------------------------------------------------ 🆕 數量 AI 判斷、借出中

def test_ai_counted_quantity_is_labelled_like_the_condition():
    assert "數量：2（AI 判斷）" in archive(row(quantity_ai=True))
    assert "數量：2\n" in archive(row(quantity_ai=False))


def test_a_loaned_item_says_who_has_it():
    assert "借出中：王小明" in archive(row(borrower="王小明", borrowed_at="2026-10-23 10:00:00"))
    assert "借出中" not in archive()


def test_same_location_list_marks_loaned_items():
    others = [row(id=2, name="扇子", borrower="王小明"), row(id=1, name="燈籠")]
    text = archive(same_count=3, same_others=others)
    assert "扇子（借出中：王小明）" in text and "燈籠（借出中" not in text


def test_query_lines_mark_loaned_items():
    assert "借出中：王小明" in replies.query_result(1, [row(borrower="王小明")], limit=10)


def test_archive_part_of_a_split_leaves_out_the_totals():
    text = archive(with_totals=False)
    assert "已成功入庫" in text and "倉庫目前共" not in text and "目前只有這一件" not in text


def test_loan_replies():
    assert "第 12 筆" in replies.lent(row(borrower="王小明")) and "王小明" in replies.lent(row(borrower="王小明"))
    assert "#12" in replies.returned(row()) and "歸還" in replies.returned(row())
    assert "王小明" in replies.already_lent(row(borrower="王小明", borrowed_at="2026-10-23 10:00:00"))
    assert "歸還" in replies.already_lent(row(borrower="王小明", borrowed_at="t"))
    assert "沒有借出" in replies.NOT_LENT and "借出人" in replies.LOAN_NEED_NAME


def test_confirm_message_lists_the_items_and_the_choices():
    text = replies.confirm_items(["茶壺", "扇子", "燈籠"], minutes=10)
    assert "3 種東西" in text and "茶壺、扇子、燈籠" in text
    assert "「分開」" in text and "「合併」" in text and "10 分鐘" in text


def test_pending_and_backfill_texts():
    assert "自動補登" in replies.PENDING_NOTICE and "Excel" in replies.PENDING_NOTICE
    assert "補登" in replies.backfilled()


def test_long_replies_are_cut_into_chunks_on_line_boundaries_without_losing_text():
    text = "\n".join(f"第 {i} 行" + "字" * 40 for i in range(200))
    parts = replies.chunks(text, limit=1900)
    assert len(parts) > 1 and all(len(p) <= 1900 for p in parts)
    assert "\n".join(parts) == text


def test_one_line_longer_than_the_limit_is_still_split():
    parts = replies.chunks("字" * 5000, limit=1900)
    assert all(len(p) <= 1900 for p in parts) and "".join(parts) == "字" * 5000


def test_short_text_is_a_single_chunk():
    assert replies.chunks("短", limit=1900) == ["短"]


def test_archive_no_longer_truncates_because_the_sender_splits_long_replies():
    text = archive(row(features="長" * 1000, remarks="備" * 1000))
    assert "長" * 1000 in text and "備" * 1000 in text
