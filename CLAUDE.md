# 劇團公演資產庫存管理 agent

一支跑在本機的 Discord bot：監聽指定頻道的物品照片，用本機 `claude -p` 辨識後歸檔成 Excel 與照片資料夾，並回覆上傳者。

## 開始任何工作前

先讀 `docs/architecture.md`（產品行為、模組、資料模型、技術決定都在裡面）。需求原文在 `docs/requirements.md`。

## 四段防護

架構文件第 7 節定義了四段防護。每一段都必須在程式裡用成對的註解標清楚開始與結束，**目前一律全部開啟**：

```python
# >>> GUARD-N START: 名稱 >>>
...
# <<< GUARD-N END <<<
```

| 編號 | 名稱 |
|---|---|
| GUARD-1 | 來源檢查 |
| GUARD-2 | 圖片驗證與轉檔 |
| GUARD-3 | 提示詞注入隔離 |
| GUARD-4 | 清洗（檔名、Excel 儲存格、Discord 回覆） |

- 寫法：先放不防護的原始值，防護區塊再覆蓋或提早返回，這樣整段註解掉後程式仍能跑。
- 標記不可省略、不可改格式；新增或搬動防護邏輯時，要放在對應的標記內。
- 除非使用者明說要關（上課對照時），不要關閉、移除或繞過任何一段。

## 不可 commit 的東西

- `.env`（含 `DISCORD_TOKEN`）。只有 `.env.example` 可以 commit，裡面只能放假值。
- `DATA_DIR` 裡的所有內容（照片、`inventory.xlsx`、日誌、暫存）。預設資料夾是 `data/`，已列在 `.gitignore`。
- commit 前先看 `git status`，發現上述檔案被追蹤就停下來處理，不要 `git add -A` 蓋過去。
