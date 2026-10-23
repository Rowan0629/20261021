from troupe_bot.search import find_duplicates, normalize_location, run_query, same_location, total_count
from troupe_bot.store import AssetRow
from troupe_bot.tasks import QuerySpec


def row(id, name="青花瓷花瓶", category="小道具", location="B區03箱", **over) -> AssetRow:
    return AssetRow(id=id, name=name, category=category, location=location, **over)


# ------------------------------------------------------------ 位置正規化


def test_location_normalization_ignores_width_case_and_spaces():
    assert normalize_location("B區03箱") == normalize_location("ｂ 區 ０３ 箱")


# ------------------------------------------------------------ 總筆數


def test_total_count_skips_deleted_and_non_assets():
    rows = [row(1), row(2), row(3, status="已刪除"), row(4, category="非劇團資產")]
    assert total_count(rows) == 2


# ------------------------------------------------------------ 疑似重複


def test_similar_name_in_same_location_is_a_duplicate():
    new = row(5, name="青花瓷瓶")
    assert [d.id for d in find_duplicates([row(1), new], new)] == [1]


def test_same_name_in_a_different_location_is_not_a_duplicate():
    new = row(5, location="後台A衣箱")
    assert find_duplicates([row(1), new], new) == []


def test_different_category_or_deleted_rows_are_not_duplicates():
    new = row(5)
    rows = [row(1, category="大道具"), row(2, status="已刪除"), new]
    assert find_duplicates(rows, new) == []


def test_unspecified_locations_need_a_much_closer_name():
    new = row(5, name="鳳冠", location="未指定")
    assert find_duplicates([row(1, name="鳳冠", location="未指定"), new], new)[0].id == 1
    assert find_duplicates([row(1, name="鳳冠頭飾組", location="未指定"), new], new) == []


def test_new_row_is_never_its_own_duplicate_and_non_assets_are_skipped():
    new = row(5)
    assert find_duplicates([new], new) == []
    other = row(6, category="非劇團資產")
    assert find_duplicates([row(7, category="非劇團資產"), other], other) == []


def test_at_most_three_duplicates_are_reported():
    rows = [row(i) for i in range(1, 7)]
    assert len(find_duplicates(rows, rows[-1])) == 3


# ------------------------------------------------------------ 同位置清單


def test_same_location_counts_the_new_item_and_lists_others_newest_first():
    rows = [row(1, name="A"), row(2, name="B", location="C區"), row(3, name="C"), row(4, name="D")]
    count, others = same_location(rows, rows[-1])
    assert count == 3
    assert [o.id for o in others] == [3, 1]


def test_same_location_is_capped_but_reports_the_true_count():
    rows = [row(i, name=f"物{i}") for i in range(1, 10)]
    count, others = same_location(rows, rows[-1], limit=5)
    assert count == 9 and len(others) == 5


def test_same_location_ignores_deleted_and_non_assets():
    rows = [row(1, status="已刪除"), row(2, category="非劇團資產"), row(3)]
    assert same_location(rows, rows[-1]) == (1, [])


def test_same_location_for_a_non_asset_is_empty():
    new = row(3, category="非劇團資產")
    assert same_location([row(1), new], new) == (0, [])


def test_unspecified_location_groups_with_other_unspecified_items():
    rows = [row(1, location="未指定"), row(2, location="B區"), row(3, location="未指定")]
    count, others = same_location(rows, rows[-1])
    assert count == 2 and [o.id for o in others] == [1]


# ------------------------------------------------------------ 查詢


def test_keyword_matches_name_features_scene_and_remarks():
    rows = [
        row(1, name="花瓶", features="青花瓷"),
        row(2, name="茶壺", scene="茶館青花瓷風格"),
        row(3, name="椅子", remarks="借來的青花瓷組"),
        row(4, name="扇子"),
    ]
    total, hits = run_query(rows, QuerySpec(keywords=["青花瓷"]))
    assert total == 3 and [h.id for h in hits] == [3, 2, 1]


def test_all_keywords_must_match():
    rows = [row(1, name="花瓶", features="青花瓷 木底座"), row(2, name="茶壺", features="青花瓷")]
    assert run_query(rows, QuerySpec(keywords=["青花瓷", "木底座"]))[0] == 1


def test_play_query_ignores_title_brackets():
    rows = [row(1, play="《白蛇傳》"), row(2, play="《紅樓夢》")]
    assert [r.id for r in run_query(rows, QuerySpec(play="白蛇傳"))[1]] == [1]


def test_location_and_condition_and_category_filters():
    rows = [
        row(1, location="B區03箱", condition="需維修"),
        row(2, location="B區03箱", condition="良好"),
        row(3, location="後台A衣箱", condition="需維修", category="服裝"),
    ]
    assert [r.id for r in run_query(rows, QuerySpec(location="b區03箱"))[1]] == [2, 1]
    assert [r.id for r in run_query(rows, QuerySpec(condition="需維修"))[1]] == [3, 1]
    assert [r.id for r in run_query(rows, QuerySpec(category="服裝"))[1]] == [3]


def test_deleted_rows_and_non_assets_are_hidden_unless_asked_for():
    rows = [row(1, status="已刪除"), row(2, category="非劇團資產", name="馬克杯"), row(3)]
    assert [r.id for r in run_query(rows, QuerySpec(keywords=["杯"]))[1]] == []
    assert [r.id for r in run_query(rows, QuerySpec(category="非劇團資產"))[1]] == [2]


def test_results_are_capped_but_total_is_reported():
    rows = [row(i) for i in range(1, 16)]
    total, hits = run_query(rows, QuerySpec(keywords=["花瓶"]), limit=10)
    assert total == 15 and len(hits) == 10 and hits[0].id == 15


# ------------------------------------------------------------ 🆕 借出中

def test_loaned_items_still_count_in_the_total_and_in_the_same_location_list():
    rows = [row(1), row(2, borrower="王小明"), row(3)]
    assert total_count(rows) == 3
    count, others = same_location(rows, rows[2])
    assert count == 3 and [o.id for o in others] == [2, 1]


def test_query_loaned_lists_only_items_that_are_out():
    rows = [row(1), row(2, name="扇子", borrower="王小明"), row(3, name="燈籠", borrower="李大華", status="已刪除")]
    total, hits = run_query(rows, QuerySpec(loaned=True))
    assert (total, [h.id for h in hits]) == (1, [2])


def test_loaned_filter_combines_with_other_conditions():
    rows = [row(1, name="扇子", borrower="王小明"), row(2, name="燈籠", borrower="李大華")]
    total, hits = run_query(rows, QuerySpec(keywords=["燈籠"], loaned=True))
    assert [h.id for h in hits] == [2]
