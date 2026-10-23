# 劇團公演資產庫存管理 agent

跑在你電腦上的 Discord bot。只要它開著，指定頻道裡任何人傳一張（或同一件物品的多張）道具、布景、服裝的照片，它就會用本機的 `claude -p` 判斷類別、整理特徵，歸檔進 Excel、存好照片，並回覆上傳者。bot 關掉就不處理。

完整的行為、架構與技術決定見 [`docs/architecture.md`](docs/architecture.md)，需求原文見 [`docs/requirements.md`](docs/requirements.md)。

## 第一次使用

1. 照 [`docs/discord-server-setup.md`](docs/discord-server-setup.md) 建好 Server、頻道，拿到 `CHANNEL_ID`。
2. 照 [`docs/discord-bot-setup.md`](docs/discord-bot-setup.md) 建好 bot、打開 **Message Content Intent**、拿到 token、邀請 bot 進 Server（權限要包含**新增反應**）。
3. 在專案資料夾建立 `.env`（可參考 `.env.example`），填入四個設定：

   ```
   DISCORD_TOKEN=...
   CHANNEL_ID=...
   CLAUDE_MODEL=claude-haiku-5-5
   DATA_DIR=./data
   ```

   `.env` 已被 `.gitignore` 忽略，**不要 commit，也不要把 token 貼給任何人**。
4. 確認終端機輸入 `claude` 可以執行，而且 PATH 先找到的是 `claude.exe`（不是 npm 的 `claude.cmd`，程式會拒絕啟動）。

## 啟動

在專案資料夾執行：

```
uv run python -m troupe_bot
```

看到「已上線」就可以到頻道傳照片。按 `Ctrl + C` 停止。

也可以直接雙擊專案資料夾裡的 `啟動bot.bat`（效果一樣）。bot 是跑在你電腦上的程式，**視窗關掉、電腦睡眠或關機，它就下線**。想在登入 Windows 時自動啟動：按 `Win + R` 輸入 `shell:startup`，把 `啟動bot.bat` 的捷徑放進去。不要同時開兩個 bot。

資料都在 `DATA_DIR`（預設 `data/`）：

- `inventory.xlsx`：所有紀錄，新的一筆加在最後。**bot 運作時盡量不要開著它**（Windows 會鎖檔，bot 會在終端機印警告並每 3 秒重試，共 3 次；還是寫不進去，就先把資料存到 `data/pending/`，回覆上傳者「已收到，會自動補登」，等你把 Excel 關掉後約一分鐘內自動補寫）；要看請先複製一份。
- `photos/`：照片，檔名 `日期 時間 類別 名稱簡稱.jpg`。
- `bot.log`：日誌。

## 在 Discord 裡怎麼用

- **歸檔**：傳照片，可附文字說明（存放位置、數量、劇目、物品狀況、備註）。例：「放 B區03箱，兩個，白蛇傳用」。
- **補充 / 更正**：回覆 bot 的歸檔訊息，直接寫要改的，例如「放在後台A衣箱」「備註：借來的要還」。
- **刪除**：回覆歸檔訊息，只寫「刪除」兩個字（不會真的移除，只在 Excel 標記為已刪除）。
- **查詢**：@bot 加上問題，例如「@bot 找青花瓷」「@bot B區03箱有什麼」「@bot 《白蛇傳》要用的服裝」「@bot 哪些需維修」。

## 四段防護

四段防護在程式裡用成對的註解標出，**一開始全部開啟**。行號只是大約位置，改過程式後請用 `uv run python tools/guard_lines.py` 重新查（它也會檢查標記是否成對）。

| 防護 | 做什麼 | 位置 |
|---|---|---|
| 防護 1 | `claude -p` 的檔案範圍隔離：只能碰這一件的暫存資料夾，讀不到 `DATA_DIR` | `src/troupe_bot/claude_client.py` 第 100–103 行 |
| 防護 2 | 上傳者文字只當資料：寫進檔案，不接進指令 | `src/troupe_bot/claude_client.py` 第 105–109 行 |
| 防護 3 | 檔名清洗：清掉 `/ \ ..`、冒號等會讓路徑亂跑的字 | `src/troupe_bot/photos.py` 第 98–101 行 |
| 防護 4 | Excel 公式處理：`= + - @` 開頭的文字存成純文字 | `src/troupe_bot/store.py` 第 125–129 行 |

每一段都是「先放不防護的原始值，防護區塊再覆蓋」，所以把任何一段整個註解掉，程式仍然能跑，只是失去那一層保護。

## 測試

```
uv run pytest            # 自動化測試，不花額度
uv run pytest -m live    # 會真的呼叫 claude -p（花一點額度）：防護 1 對照、辨識、歸檔→更新→查詢
```
