# 劇團公演資產庫存管理 agent

一支跑在本機的 Discord bot：監聽指定頻道的物品照片，用本機 `claude -p` 辨識後歸檔成 Excel 與照片資料夾，並回覆上傳者。

## 開始任何工作前

先讀 `docs/architecture.md`（產品行為、模組、資料模型、技術決定都在裡面）。需求原文在 `docs/requirements.md`。

## 常用指令

- 啟動 bot：`uv run python -m troupe_bot`（在專案資料夾執行）
- 測試：`uv run pytest`（預設不含會呼叫真 claude 的 live 測試；要跑用 `uv run pytest -m live`）
- 查四段防護的行號、檢查標記成對：`uv run python tools/guard_lines.py`

## 四段防護

四段防護都在程式裡用成對的註解標清楚開始與結束，**目前一律全部開啟**：

```python
# ==== 防護 N：名稱　開始 ====
...
# ==== 防護 N 結束 ====
```

| 編號 | 名稱 | 位置 |
|---|---|---|
| 防護 1 | claude -p 的檔案範圍隔離 | `claude_client.py` `_once()` |
| 防護 2 | 上傳者文字只當資料 | `claude_client.py` `_once()` |
| 防護 3 | 檔名清洗 | `photos.py` `photo_paths()` |
| 防護 4 | Excel 公式處理 | `store.py` `_set_text()` |

- 寫法：先放「不防護的原始值」，防護區塊再去覆蓋，這樣整段註解掉後程式仍能跑。
- 標記格式不可改（開始行有全形空白「　」）；新增或搬動防護邏輯時，要放在對應的標記內，並重跑 `tools/guard_lines.py`。
- 除非使用者明說要關（上課對照時），不要關閉、移除或繞過任何一段。
- 改動防護相關程式時，對應的測試（`tests/test_claude_client.py`、`test_photos.py`、`test_store.py`）要一起維持通過。

## 不可 commit 的東西

- `.env`（含 `DISCORD_TOKEN`）。只有 `.env.example` 可以 commit，裡面只能放假值。不要把 token 貼進對話、日誌或文件。
- `DATA_DIR` 裡的所有內容（照片、`inventory.xlsx`、日誌、暫存）。預設資料夾是 `data/`，已列在 `.gitignore`。
- commit 前先看 `git status`，發現上述檔案被追蹤就停下來處理，不要 `git add -A` 蓋過去。
