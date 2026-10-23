import json

from troupe_bot.pending import Spool


def make(tmp_path):
    return Spool(tmp_path / "pending")


def test_a_record_keeps_its_data_and_photos_on_disk(tmp_path):
    spool = make(tmp_path)
    rec = spool.create({"uploader_id": 7, "note": "茶壺"}, [b"photo-one", b"photo-two"])
    again = Spool(tmp_path / "pending").get(rec.id)  # 全新的物件 = 模擬 bot 重新啟動
    assert again.meta["uploader_id"] == 7 and again.meta["note"] == "茶壺"
    assert again.photos() == [b"photo-one", b"photo-two"]


def test_record_folders_are_named_by_a_random_id_never_by_the_content(tmp_path):
    spool = make(tmp_path)
    rec = spool.create({"name": "..\\..\\evil"}, [b"x"])
    assert rec.id.isalnum() and len(rec.id) >= 16
    assert [p.name for p in spool.root.iterdir()] == [rec.id]


def test_records_are_listed_oldest_first(tmp_path):
    spool = make(tmp_path)
    ids = [spool.create({"n": i}, []).id for i in range(5)]
    assert [r.id for r in spool.all()] == ids


def test_folders_without_a_finished_meta_file_are_ignored(tmp_path):
    spool = make(tmp_path)
    good = spool.create({"n": 1}, [b"x"])
    half = spool.root / "halfwritten"
    half.mkdir()
    (half / "photo1.jpg").write_bytes(b"x")
    broken = spool.root / "broken"
    broken.mkdir()
    (broken / "meta.json").write_text("{not json", encoding="utf-8")
    assert [r.id for r in spool.all()] == [good.id]


def test_update_merges_into_the_saved_meta(tmp_path):
    spool = make(tmp_path)
    rec = spool.create({"a": 1}, [])
    spool.update(rec.id, b=2)
    assert Spool(tmp_path / "pending").get(rec.id).meta["a"] == 1
    assert Spool(tmp_path / "pending").get(rec.id).meta["b"] == 2
    assert json.loads((spool.root / rec.id / "meta.json").read_text(encoding="utf-8"))["b"] == 2


def test_remove_deletes_the_folder_and_is_safe_to_repeat(tmp_path):
    spool = make(tmp_path)
    rec = spool.create({}, [b"x"])
    spool.remove(rec.id)
    spool.remove(rec.id)
    assert spool.get(rec.id) is None and list(spool.root.iterdir()) == []


def test_find_by_a_meta_value(tmp_path):
    spool = make(tmp_path)
    a = spool.create({"confirm_message_id": 111}, [])
    spool.create({"confirm_message_id": 222}, [])
    assert spool.find(confirm_message_id=111).id == a.id
    assert spool.find(confirm_message_id=999) is None


def test_an_empty_or_missing_root_lists_nothing(tmp_path):
    assert Spool(tmp_path / "nope").all() == []
    assert Spool(tmp_path / "nope").get("abc") is None
