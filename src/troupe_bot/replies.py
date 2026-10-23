"""所有回覆文字的組裝。純函式，不碰 Discord；@上傳者與 allowed_mentions 由 bot.py 處理。"""

from __future__ import annotations

from .store import AssetRow
from .tasks import UNSPECIFIED_LOCATION

DISCORD_LIMIT = 1900  # 官方上限 2000，留一點空間

FAIL_ANALYSIS = "分析失敗，請再傳一次"
FAIL_EXCEL = "記錄寫入失敗（Excel 檔可能正被打開了），請稍後再傳一次"
UNSUPPORTED_IMAGE = "這個檔案不是我能處理的圖片，請傳 JPG、PNG、WebP 或 GIF"
ALREADY_DELETED = "這筆已經刪除了，不能再更新"
NOT_FOUND = "找不到這一筆紀錄"
NOTHING_TO_UPDATE = "沒看出要更新什麼。可以直接寫，例如「放在後台A衣箱」「數量改成 3」「備註：借來的」"
NO_QUERY = "看不懂要找什麼。可以試試：「找青花瓷」「B區03箱有什麼」「《白蛇傳》要用的服裝」「哪些需維修」"
QUEUE_FULL = "目前排隊太多，請稍後再傳"
TOO_MANY_PHOTOS = "一次最多 5 張照片，請分開傳"
TOO_BIG = "照片太大了（單張上限 10 MB），請縮小後再傳"
PENDING_NOTICE = "已收到，Excel 目前被占用，會在關閉後自動補登，不用重傳"
NOT_LENT = "這件目前沒有借出"
LOAN_NEED_NAME = "請寫借出人，例如：借出 王小明"


def fit(text: str, limit: int = DISCORD_LIMIT) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def chunks(text: str, limit: int = DISCORD_LIMIT) -> list[str]:
    """把太長的回覆在換行處切成多則（Discord 單則上限 2000 字）；單行就超過上限時才硬切。"""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:limit])
            line = line[limit:]
        if not current:
            current = line
        elif len(current) + 1 + len(line) <= limit:
            current += "\n" + line
        else:
            parts.append(current)
            current = line
    parts.append(current)
    return parts


def processing() -> str:
    return "處理中…"


def queued(ahead: int) -> str:
    return f"前面還有 {ahead} 件在處理，輪到你時會通知"


def _condition(row: AssetRow) -> str:
    return row.condition + ("（AI 判斷）" if row.condition_ai else "")


def _quantity(row: AssetRow) -> str:
    return f"{row.quantity}" + ("（AI 判斷）" if row.quantity_ai else "")


def _tagged_name(row: AssetRow) -> str:
    return row.name + (f"（借出中：{row.borrower}）" if row.loaned else "")


def _detail_lines(row: AssetRow) -> list[str]:
    lines = [
        f"類別：{row.category}",
        f"名稱：{row.name}",
        f"詳細特徵：{row.features or '—'}",
        f"適用場景：{row.scene or '—'}",
        f"存放位置：{row.location}",
        f"使用/適用公演：{row.play}",
        f"數量：{_quantity(row)}",
        f"物品狀況：{_condition(row)}",
    ]
    if row.loaned:
        lines.append(f"借出中：{row.borrower}（{row.borrowed_at} 起）")
    if row.remarks:
        lines.append(f"備註：{row.remarks}")
    return lines


def archive(
    row: AssetRow, *, total: int, same_count: int, same_others: list[AssetRow], duplicates: list[AssetRow],
    with_totals: bool = True,
) -> str:
    """with_totals=False：一張照片分開入庫成好幾筆時，只有最後一則附總筆數與同位置清單。"""
    lines = [f"✅ 已成功入庫（編號 #{row.id}）", *_detail_lines(row)]

    if with_totals:
        lines += ["", f"倉庫目前共 {total} 筆。"]
        place = "位置未指定的物品" if row.location == UNSPECIFIED_LOCATION else row.location
        if same_count <= 1:
            lines.append(f"{place}目前只有這一件。")
        else:
            line = f"{place}目前共 {same_count} 件（含本筆）"
            if same_others:
                more = "等" if same_count - 1 > len(same_others) else ""
                line += "，其他有：" + "、".join(_tagged_name(o) for o in same_others) + more
            lines.append(line)

    for dup in duplicates:
        lines.append(f"⚠ 可能與第 {dup.id} 筆（{dup.name}）重複")
    if row.location == UNSPECIFIED_LOCATION:
        lines.append("ℹ 沒有提供存放位置，可回覆本訊息補充")
    return "\n".join(lines)


def non_asset(row: AssetRow, *, total: int) -> str:
    what = row.name
    if row.features and row.features != row.name:
        what += f"（{row.features}）"
    lines = [
        f"你傳的不是劇團資產，是{what}。",
        f"已建檔（編號 #{row.id}），類別記為「非劇團資產」。",
        f"倉庫目前共 {total} 筆（不含非劇團資產）。",
    ]
    return "\n".join(lines)


def updated(row: AssetRow) -> str:
    return "\n".join([f"✏ 已更新編號 #{row.id}（{row.name}）", *_detail_lines(row)])


def deleted(row: AssetRow) -> str:
    return f"🗑 已刪除編號 #{row.id}（{row.name}）。這筆不再計入總筆數與查詢；紀錄仍保留在 Excel，狀態為「已刪除」。"


def lent(row: AssetRow) -> str:
    return f"📤 第 {row.id} 筆（{row.name}）已借給 {row.borrower}。存放位置仍記為「{row.location}」。"


def returned(row: AssetRow) -> str:
    return f"📥 編號 #{row.id}（{row.name}）已歸還，借出紀錄已清除。"


def already_lent(row: AssetRow) -> str:
    return f"這件已借給 {row.borrower}（{row.borrowed_at}），請先回覆「歸還」"


def confirm_items(names: list[str], *, minutes: int) -> str:
    return (
        f"這張照片裡我看到 {len(names)} 種東西：{'、'.join(names)}。\n"
        f"請回覆「分開」各入庫一筆，或「合併」合成一筆。{minutes} 分鐘內沒回覆，我會分開入庫。"
    )


def backfilled() -> str:
    return "📥 先前暫存的資料已補登入庫。"


def _query_line(row: AssetRow) -> str:
    line = f"#{row.id} {row.name}｜{row.category}｜{row.location}｜x{row.quantity}｜{row.condition}｜{row.play}"
    if row.loaned:
        line += f"｜借出中：{row.borrower}"
    if row.remarks:
        line += f"｜備註：{row.remarks}"
    return line


def query_result(total: int, hits: list[AssetRow], *, limit: int) -> str:
    if total == 0:
        return "找不到符合的紀錄"
    header = f"共 {total} 筆符合"
    if total > len(hits):
        header += f"，只列出前 {limit} 筆"
    return "\n".join([header, *(_query_line(r) for r in hits)])
