import pytest

from troupe_bot.tasks import (
    AnalysisFailed,
    parse_ingest,
    parse_query,
    parse_update,
)


def valid_item(**over):
    data = {
        "category": "小道具",
        "name": "青花瓷花瓶",
        "short_name": "青花瓷瓶",
        "features": "青花瓷、高約30公分",
        "scene": "古典室內景",
        "play": "《白蛇傳》",
        "quantity": 2,
        "condition": "良好",
        "condition_source": "ai",
        "quantity_source": "uploader",
        "location": "B區03箱",
        "remarks": "",
    }
    data.update(over)
    return data


def valid_ingest(**over):
    """單一物品的辨識結果；over 的欄位會覆蓋到那一件物品上。"""
    return {"items": [valid_item(**over)]}


def parse_one(data):
    return parse_ingest(data).items[0]


def test_valid_ingest_is_parsed_field_by_field():
    r = parse_one(valid_ingest())
    assert (r.category, r.name, r.quantity, r.location) == ("小道具", "青花瓷花瓶", 2, "B區03箱")
    assert r.play == "《白蛇傳》"
    assert r.condition == "良好" and r.condition_source == "ai"


@pytest.mark.parametrize("bad", [None, "not a dict", [], 42])
def test_ingest_that_is_not_an_object_fails(bad):
    with pytest.raises(AnalysisFailed):
        parse_ingest(bad)


def test_unknown_category_fails():
    with pytest.raises(AnalysisFailed):
        parse_one(valid_ingest(category="食物"))


def test_empty_name_fails():
    with pytest.raises(AnalysisFailed):
        parse_one(valid_ingest(name="   "))


@pytest.mark.parametrize("bad", ["很多", True, 2.5, [1], {"n": 1}])
def test_non_numeric_quantity_fails(bad):
    with pytest.raises(AnalysisFailed):
        parse_one(valid_ingest(quantity=bad))


def test_missing_quantity_defaults_to_one():
    data = valid_ingest()
    del data["items"][0]["quantity"]
    assert parse_one(data).quantity == 1


@pytest.mark.parametrize("raw,expected", [(0, 1), (-3, 1), (3.0, 3)])
def test_quantity_below_one_is_clamped_and_integral_float_accepted(raw, expected):
    assert parse_one(valid_ingest(quantity=raw)).quantity == expected


def test_unknown_condition_fails():
    with pytest.raises(AnalysisFailed):
        parse_one(valid_ingest(condition="還不錯"))


def test_empty_location_becomes_unspecified():
    assert parse_one(valid_ingest(location="  ")).location == "未指定"


def test_empty_play_becomes_generic():
    assert parse_one(valid_ingest(play="")).play == "通用/未指定"


def test_non_asset_forces_play_to_not_applicable_whatever_the_model_said():
    r = parse_one(valid_ingest(category="非劇團資產", play="《白蛇傳》"))
    assert r.play == "不適用"


def test_empty_short_name_falls_back_to_name_prefix():
    r = parse_one(valid_ingest(name="一二三四五六七八九十十一十二十三", short_name=""))
    assert r.short_name == "一二三四五六七八九十十一"


def test_condition_source_defaults_to_ai_when_missing_or_odd():
    assert parse_one(valid_ingest(condition_source="whatever")).condition_source == "ai"


def test_overlong_text_is_truncated_not_rejected():
    r = parse_one(valid_ingest(features="長" * 5000))
    assert len(r.features) <= 1000


def test_update_patch_keeps_only_known_fields():
    p = parse_update({"location": "後台A衣箱", "quantity": 3, "evil": "x"})
    assert p.fields == {"location": "後台A衣箱", "quantity": 3}
    assert not p.is_empty()


def test_update_patch_remarks_are_appended_separately():
    p = parse_update({"remarks_append": "借來的，要還"})
    assert p.remarks_append == "借來的，要還"
    assert p.fields == {}
    assert not p.is_empty()


def test_update_with_nothing_is_empty():
    assert parse_update({}).is_empty()
    assert parse_update({"location": None, "remarks_append": ""}).is_empty()


def test_update_with_bad_category_or_quantity_fails():
    with pytest.raises(AnalysisFailed):
        parse_update({"category": "食物"})
    with pytest.raises(AnalysisFailed):
        parse_update({"quantity": "很多"})


def test_query_trims_and_drops_empty_keywords():
    q = parse_query({"keywords": [" 青花瓷 ", "", "  "], "category": "小道具"})
    assert q.keywords == ["青花瓷"]
    assert q.category == "小道具"


def test_query_with_bad_category_or_keywords_type_fails():
    with pytest.raises(AnalysisFailed):
        parse_query({"category": "食物"})
    with pytest.raises(AnalysisFailed):
        parse_query({"keywords": "青花瓷"})


def test_query_with_no_conditions_is_empty():
    assert parse_query({}).is_empty()


# ------------------------------------------------------------ 🆕 多件物品、數量來源

def test_quantity_source_marks_whether_the_number_was_counted_by_the_ai():
    assert parse_one(valid_ingest(quantity_source="uploader")).quantity_ai is False
    assert parse_one(valid_ingest(quantity_source="ai")).quantity_ai is True


def test_quantity_source_defaults_to_ai_when_missing_or_odd():
    assert parse_one(valid_ingest(quantity_source="whatever")).quantity_ai is True
    data = valid_ingest()
    del data["items"][0]["quantity_source"]
    assert parse_one(data).quantity_ai is True


def test_a_single_item_has_no_combined_version():
    batch = parse_ingest(valid_ingest())
    assert len(batch.items) == 1 and batch.combined is None


def test_several_items_need_a_combined_version():
    data = {"items": [valid_item(name="茶壺"), valid_item(name="扇子")]}
    with pytest.raises(AnalysisFailed):
        parse_ingest(data)
    data["combined"] = valid_item(name="桌上陳設一組")
    batch = parse_ingest(data)
    assert [i.name for i in batch.items] == ["茶壺", "扇子"]
    assert batch.combined.name == "桌上陳設一組"


def test_every_item_is_validated_not_just_the_first():
    data = {"items": [valid_item(), valid_item(category="食物")], "combined": valid_item()}
    with pytest.raises(AnalysisFailed):
        parse_ingest(data)


@pytest.mark.parametrize("bad", [{}, {"items": []}, {"items": "茶壺"}, {"items": [1, 2]}])
def test_missing_or_malformed_items_fail(bad):
    with pytest.raises(AnalysisFailed):
        parse_ingest(bad)


def test_more_than_eight_items_keeps_the_first_eight():
    data = {"items": [valid_item(name=f"物{i}") for i in range(10)], "combined": valid_item()}
    assert [i.name for i in parse_ingest(data).items] == [f"物{i}" for i in range(8)]


def test_each_item_of_a_mixed_photo_keeps_its_own_category_rules():
    data = {"items": [valid_item(), valid_item(category="非劇團資產", name="馬克杯", play="《白蛇傳》")],
            "combined": valid_item()}
    items = parse_ingest(data).items
    assert items[0].play == "《白蛇傳》" and items[1].play == "不適用"


def test_the_fixed_instruction_explains_big_vs_small_props_and_counting():
    from troupe_bot.tasks import INGEST_INSTRUCTION

    assert "單手" in INGEST_INSTRUCTION and "陳設" in INGEST_INSTRUCTION
    assert "quantity_source" in INGEST_INSTRUCTION and "combined" in INGEST_INSTRUCTION


def test_ingest_schema_requires_items_and_the_quantity_source():
    from troupe_bot.tasks import INGEST_SCHEMA

    assert INGEST_SCHEMA["required"] == ["items"]
    item = INGEST_SCHEMA["properties"]["items"]["items"]
    assert "quantity_source" in item["required"]
    assert INGEST_SCHEMA["properties"]["items"]["maxItems"] == 8


# ------------------------------------------------------------ 🆕 查詢「借出中」

def test_query_can_ask_for_loaned_items_only():
    q = parse_query({"loaned": True})
    assert q.loaned is True and not q.is_empty()
    assert parse_query({"loaned": False}).is_empty()
    assert parse_query({}).loaned is False


def test_query_loaned_must_be_a_boolean():
    with pytest.raises(AnalysisFailed):
        parse_query({"loaned": "是"})
