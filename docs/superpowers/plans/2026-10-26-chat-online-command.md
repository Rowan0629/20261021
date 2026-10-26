# 聊天室指令上線／下線 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** bot 開機後在背景（無視窗）待命，管理員在指定頻道打 `!上線` 才開始處理照片，`!下線` 做完手上工作後回到待命。

**Architecture:** `Dispatcher`（`bot.py`，不碰 Discord 連線）新增三種狀態 `standby / active / stopping` 與兩個指令；預設 `start_active=True` 讓既有 292 個測試不用改，`TroupeBot` 則以 `start_active=False` 建立。Discord 狀態燈（閒置／線上）由 `Dispatcher` 的 `on_mode_change` callback 通知 `TroupeBot` 更新。開機啟動改用隱藏視窗的 `.vbs` 呼叫 `啟動bot.bat`。

**Tech Stack:** Python 3.12、discord.py 2.x、pytest（`uv run pytest`）、Windows batch / VBScript。

**Spec:** `docs/superpowers/specs/2026-10-26-chat-online-command-design.md`

## Global Constraints

- `.env` 仍只有四個變數（`DISCORD_TOKEN`、`CHANNEL_ID`、`CLAUDE_MODEL`、`DATA_DIR`），不新增。
- 指令只在 `CHANNEL_ID` 頻道有效，內容須完全等於 `!上線` 或 `!下線`，不經 AI、不呼叫 `claude -p`。
- 管理員 = 發話者有 `manage_guild`（管理伺服器）權限。
- 四段防護不動，不碰 `claude_client.py`、`photos.py`、`store.py`；結束前 `uv run python tools/guard_lines.py` 必須回報四段成對、全部開啟。
- 既有測試（292 個）必須維持通過：`uv run pytest`。
- **不要 commit**：專案規則是使用者說了才 commit；`啟動bot.bat` 有使用者尚未 commit 的修改；永遠不要 `git add -A`。每個 task 結尾的 Checkpoint 只跑測試，commit 留到使用者要求時，且只 add 本計畫改到的檔案。
- 回覆文字全部放在 `replies.py`；程式註解與命名沿用現有繁體中文風格。

## Review Focus

1. 管理員用中文輸入法打全形「！上線」→ 視為指令（Task 1 測試 `test_full_width_exclamation_is_accepted`）。
2. 指令後面多帶字（「!上線 好嗎」）→ 不是指令，待命中靜默忽略（Task 1 `test_command_with_extra_text_is_not_a_command`）。
3. 上線→下線→上線反覆切換 → 等確認的計時器只有一個，不會重複入庫（Task 1 `test_awaiting_timer_is_stopped_in_standby_and_restarted_once_on_going_online`）。
4. 待命期間 Excel 的待補登資料不被補寫，上線後才補寫並通知（Task 1 `test_pending_data_waits_in_standby_and_is_filled_in_after_going_online`）。
5. 其他頻道、bot 自己發的指令 → 完全忽略（Task 1 `test_command_from_other_channel_or_a_bot_is_ignored`）。

---

### Task 1: Dispatcher 狀態與上線／下線指令

**Files:**
- Modify: `src/troupe_bot/bot.py`（`Dispatcher`：`__init__`、`on_message`、`_start_timer`、`pending_loop`、`close`；新增模組層函式與常數）
- Modify: `src/troupe_bot/replies.py`（新增文字常數）
- Test: `tests/test_dispatcher.py`（檔尾新增一段 `# ===== 聊天室指令上線／下線`）

**Interfaces:**
- Produces（Task 2 使用）:
  - 常數 `STANDBY = "standby"`、`ACTIVE = "active"`、`STOPPING = "stopping"`（`bot.py`）
  - `Dispatcher(..., start_active: bool = True, on_mode_change: Callable[[str], Awaitable[None]] | None = None)`
  - `Dispatcher.mode: str`（上述三個常數之一）
  - `Dispatcher.recover()` 可重複呼叫（每次上線都會呼叫）
  - `replies.ONLINE = "已上線"`、`ALREADY_ONLINE = "已經在運作中"`、`OFFLINE = "已下線"`、`ALREADY_STANDBY = "目前就是待命中"`、`ADMIN_ONLY = "只有伺服器管理員可以上線／下線"`、`CANCELLED_OFFLINE = "已取消下線，繼續運作"`、`STOPPING_NOW = "正在下線，等手上的工作做完"`

- [ ] **Step 1: 在 `tests/test_dispatcher.py` 補測試用的管理員物件**

`FakeUser` 加一個最後的欄位 `guild_permissions: object = None`；新增 `@dataclass class FakePerms: manage_guild: bool`；新增 helper `admin(id=1) -> FakeUser`（`display_name="管理員"`、`guild_permissions=FakePerms(True)`）與 `cmd(text, *, author=None, channel_id=CHANNEL) -> FakeMessage`（作者預設 `admin()`）。

- [ ] **Step 2: 寫會失敗的測試（檔尾新增）**

每個測試用 `drive(svc, runner, scenario, start_active=False, ...)`（需要狀態的另有說明）。測試名稱與斷言：

- `test_standby_ignores_photos_mentions_and_replies_silently`：待命中依序送照片、@bot 問題、回覆歸檔訊息各一則 → 全部 `reply_calls == []`、`reactions == set()`、`svc.store.all_rows() == []`、`runner.texts == []`。
- `test_admin_online_switches_to_active_and_photos_are_processed`：`!上線` → `d.mode == ACTIVE`、`msg.reply_calls[0]["content"] == replies.ONLINE`；接著傳照片 → 一筆入庫。
- `test_full_width_exclamation_is_accepted`：`！上線` → `d.mode == ACTIVE`。
- `test_command_with_extra_text_is_not_a_command`：`!上線 好嗎` → `d.mode == STANDBY`、`reply_calls == []`。
- `test_non_admin_command_is_refused_and_state_unchanged`：作者 `FakeUser(7)`（無權限）：待命中 `!上線` → 回 `replies.ADMIN_ONLY`、`mode == STANDBY`；運作中（`start_active=True`）`!下線` → 回 `replies.ADMIN_ONLY`、`mode == ACTIVE`。
- `test_command_from_other_channel_or_a_bot_is_ignored`：`cmd("!上線", channel_id=1)` 與 `cmd("!上線", author=FakeUser(1, bot=True))` → 無回覆、`mode == STANDBY`。
- `test_repeated_commands_get_a_plain_answer`：運作中 `!上線` → `replies.ALREADY_ONLINE`；待命中 `!下線` → `replies.ALREADY_STANDBY`；兩者狀態不變。
- `test_going_offline_waits_for_running_work_then_replies_offline`：`start_active=True`，`FakeRunner(one(VASE), gate=gate)`（`gate = asyncio.Event()` 可在 `drive` 之前建立，Python 3.12 的 Event 不綁定事件迴圈）。流程：傳照片、`await asyncio.sleep(0.05)` 讓 worker 卡在 gate；`task = asyncio.create_task(d.on_message(down))`、sleep；斷言 `d.mode == STOPPING` 且 `down.reply_calls == []`；此時再傳一張照片 → 該訊息無回覆無反應；`gate.set()`、`await task` → `down.reply_calls[0]["content"] == replies.OFFLINE`、`d.mode == STANDBY`、`len(svc.store.all_rows()) == 1`（只有第一張）。
- `test_online_during_stopping_cancels_the_shutdown`：同上情境，卡住期間另一位管理員 `!上線` → 回 `replies.CANCELLED_OFFLINE`、`mode == ACTIVE`；`gate.set()`、`await task` 後 `down.reply_calls == []`（不回「已下線」）、`mode == ACTIVE`。
- `test_offline_again_while_stopping_says_so`：同上情境，卡住期間再 `!下線` → 回 `replies.STOPPING_NOW`。
- `test_awaiting_timer_is_stopped_in_standby_and_restarted_once_on_going_online`：`start_active=True`、`svc.awaiting_timeout = 0.3`；傳會產生「多種東西」的照片（`several(TEAPOT, FAN)`）；`!下線` 後 `d._timers == {}`；`await asyncio.sleep(0.5)`（超過期限）→ `svc.store.all_rows() == []`；`!上線` → sleep 0.2 → 2 列（分開（AI 判定））；再 `!下線`、`!上線` 一輪、sleep 0.2 → 仍是 2 列。
- `test_pending_data_waits_in_standby_and_is_filled_in_after_going_online`：用既有 `lock_excel(monkeypatch)`；運作中傳照片 → `len(svc.pending.all()) == 1`；`!下線`；`monkeypatch.undo()`；`with_loop=True, pending_interval=0.05`，sleep 0.3 → `svc.pending.all()` 仍 1 筆、`all_rows() == []`；`!上線`、sleep 0.3 → `pending` 清空、1 列（`lookup=messages.get` 同既有補登測試）。

- [ ] **Step 3: 跑測試確認失敗**

Run: `uv run pytest tests/test_dispatcher.py -q`
Expected: 新增的測試 FAIL（`start_active` 不是合法參數／`replies.ONLINE` 不存在）；舊測試仍通過。

- [ ] **Step 4: `replies.py` 加上 Interfaces 列的七個常數**（放在 `LOAN_NEED_NAME` 附近，文字照 Interfaces 區塊逐字）

- [ ] **Step 5: 實作 `bot.py`**

  - 模組層：三個狀態常數；`parse_command(content: str) -> str | None`：`clean_text` 後做 `unicodedata.normalize("NFKC", ...)`，等於 `"!上線"` 回 `"online"`、等於 `"!下線"` 回 `"offline"`，其他回 `None`；`is_admin(author) -> bool`：`getattr(getattr(author, "guild_permissions", None), "manage_guild", False)` 為真。
  - `Dispatcher.__init__`：新增 `start_active`、`on_mode_change`，`self.mode = ACTIVE if start_active else STANDBY`。
  - `on_message`：頻道／bot 檢查之後、既有分流之前，先 `command = parse_command(message.content)`；有指令就 `await self._command(message, command)` 後 return；接著 `if self.mode != ACTIVE: return`（待命與下線中一律靜默忽略，包含照片）。
  - `async _command(self, message, command: str) -> None`：
    - 非管理員 → 回 `ADMIN_ONLY`，return。
    - `online`：`ACTIVE` → `ALREADY_ONLINE`；`STOPPING` → `await self._set_mode(ACTIVE)`、`await self.recover()`、回 `CANCELLED_OFFLINE`；`STANDBY` → `await self._set_mode(ACTIVE)`、`await self.recover()`、回 `ONLINE`。
    - `offline`：`STANDBY` → `ALREADY_STANDBY`；`STOPPING` → `STOPPING_NOW`；`ACTIVE` → `await self._set_mode(STOPPING)`、取消所有計時器（沿用 `close()` 的取消邏輯，抽成 `_cancel_all_timers()` 讓 `close()` 也呼叫它）、`await self.queue.join()`；之後若 `self.mode != STOPPING`（期間被 `!上線` 取消）就 return，否則 `await self._set_mode(STANDBY)` 並回 `OFFLINE`。
    - 所有回覆用 `message.reply(text, mention_author=False)`。
  - `async _set_mode(self, mode: str) -> None`：設 `self.mode`，若有 `on_mode_change` 則 `await` 它（例外只記 log，不外傳）。
  - `_start_timer`：寫入前若 `self._timers` 已有同 id 的計時器就先取消（讓 `recover()` 可重複呼叫）。
  - `pending_loop`：每輪只在 `self.mode == ACTIVE` 且 `pending.all()` 非空時才 `_queue_flush()`。

- [ ] **Step 6: 跑測試確認通過**

Run: `uv run pytest -q`
Expected: 全部通過（原有 292 個 + 本 task 新增的）。

- [ ] **Step 7: Checkpoint**

Run: `uv run python tools/guard_lines.py`
Expected: 四段防護標記成對、全部開啟。不 commit。

---

### Task 2: TroupeBot 以待命啟動並更新 Discord 狀態燈

**Files:**
- Modify: `src/troupe_bot/bot.py`（`TroupeBot.on_ready`、新增 `presence_for`、`TroupeBot._apply_presence`）
- Test: `tests/test_dispatcher.py`（或新檔 `tests/test_presence.py`，擇一，沿用現有 import 風格）

**Interfaces:**
- Consumes: `STANDBY / ACTIVE / STOPPING`、`Dispatcher(start_active=..., on_mode_change=...)`、`Dispatcher.mode`（Task 1）
- Produces: `presence_for(mode: str) -> tuple[discord.Status, discord.CustomActivity | None]`；`async TroupeBot._apply_presence(mode: str) -> None`

- [ ] **Step 1: 寫會失敗的測試**

- `test_standby_shows_idle_with_a_hint`：`status, activity = presence_for(STANDBY)` → `status == discord.Status.idle`、`activity.name == "待命中，管理員輸入 !上線"`。
- `test_active_and_stopping_show_online_without_activity`：`presence_for(ACTIVE)` 與 `presence_for(STOPPING)` 都是 `(discord.Status.online, None)`。

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest -k presence -q`
Expected: FAIL（`presence_for` 未定義）。

- [ ] **Step 3: 實作**

  - `presence_for(mode)`：依上面測試的值回傳。
  - `TroupeBot._apply_presence(mode)`：`status, activity = presence_for(mode)`，呼叫 `await self.change_presence(status=status, activity=activity)`。
  - `TroupeBot.on_ready`：建立 `Dispatcher` 時傳 `start_active=False, on_mode_change=self._apply_presence`；建立後只啟動 `worker()` 與 `pending_loop()` 兩個背景工作，**不再呼叫 `recover()`**（改由 `!上線` 觸發）；每次 `on_ready` 都 `await self._apply_presence(self.dispatcher.mode)`（重新連線後狀態燈才會跟著對）。log 文字改為「已連線，待命中：…」，並提示管理員輸入 `!上線`。

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest -q`
Expected: 全部通過。

- [ ] **Step 5: Checkpoint**

Run: `uv run python tools/guard_lines.py`
Expected: 四段防護成對、全部開啟。不 commit。

---

### Task 3: 隱藏視窗啟動

**Files:**
- Modify: `啟動bot.bat`（保留使用者目前未 commit 的「意外停止自動重開」版本，在其上修改）
- Create: `start_bot_hidden.vbs`（檔名刻意用英文：WSH 以系統 ANSI 編碼讀 `.vbs`，內容若含中文路徑會亂碼）
- Modify: `docs/superpowers/specs/2026-10-26-chat-online-command-design.md`（§5、§8：檔名改 `start_bot_hidden.vbs`；隱藏模式的錯誤紀錄改寫到 `data\startup.log`，因為設定錯誤發生在 `bot.log` 建立之前）

**Interfaces:**
- Consumes: bot 啟動結束碼約定（`0` 正常；`2–5` 設定問題；`-1073741510` Ctrl+C）
- Produces: `啟動bot.bat hidden`（隱藏模式的呼叫方式，只有 `.vbs` 使用）

此 task 無法用 pytest 驗證，驗證步驟為手動指令。

- [ ] **Step 1: 修改 `啟動bot.bat`**

  - 第一個參數為 `hidden`（不分大小寫）時設 `HIDDEN=1`。
  - 隱藏模式：不設 `title`；輸出用 `>>` 附加到 `%~dp0data\startup.log`（stdout 與 stderr 都導）；執行前 `if not exist data mkdir data`，並設 `PYTHONIOENCODING=utf-8`；每次啟動 python 前若該檔超過 1,000,000 位元組就刪掉（避免無限成長）；到 `:stopped` 時**不 `pause`**（看不見的視窗會卡住）。
  - 重新啟動前的等待改用 `ping -n 11 127.0.0.1 >nul` 取代 `timeout /t 10 /nobreak`（隱藏視窗的 stdin 無效時 `timeout` 會立刻失敗，變成無間隔的重開迴圈）。一般（有視窗）模式也一併改用 `ping`，行為一致。
  - 非隱藏模式其餘行為不變；提示文字中的「看到『已上線』」改成「看到『待命中』後，到 Discord 由管理員輸入 !上線」。

- [ ] **Step 2: 建立 `start_bot_hidden.vbs`**

只含 ASCII：以 `WScript.ScriptFullName` 取得所在資料夾，在該資料夾找出檔名結尾為 `bot.bat` 的檔案（即 `啟動bot.bat`，避免在 `.vbs` 內寫中文），用 `WScript.Shell.Run("cmd /c """<完整路徑>""" hidden", 0, False)` 啟動（視窗樣式 0 = 隱藏、不等待）。找不到就靜默結束。

- [ ] **Step 3: 手動驗證——設定錯誤時不卡死、原因寫進紀錄**

PowerShell（在專案資料夾；`CHANNEL_ID` 用環境變數覆蓋成非數字，不會動到 `.env`）:

```powershell
Remove-Item data\startup.log -ErrorAction SilentlyContinue
$env:CHANNEL_ID = 'abc'; wscript.exe start_bot_hidden.vbs; Start-Sleep 15; Remove-Item Env:CHANNEL_ID
Get-Content data\startup.log -Encoding UTF8
Get-Process cmd -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -eq '' } | Select-Object Id
```

Expected: 過程中沒有任何視窗跳出；`startup.log` 內有「設定錯誤：CHANNEL_ID 必須是一串數字」；沒有殘留卡住的隱藏 `cmd`（結束碼 2 屬於 `:stopped`，直接結束）。

- [ ] **Step 4: 手動驗證——有視窗模式不受影響**

雙擊（或 `cmd /c 啟動bot.bat`）仍可啟動，顯示待命提示。驗證後 Ctrl+C 結束。不需連 Discord 的部分只確認啟動訊息與結束碼處理。

- [ ] **Step 5: 更新規格檔 §5、§8 對應文字**（內容見 Files）

---

### Task 4: 文件

**Files:**
- Modify: `docs/architecture.md`
- Modify: `README.md`

- [ ] **Step 1: `docs/architecture.md`**
  - §1 目標段落「bot 關掉就不處理任何訊息」之後補一段：開機後預設「待命」，管理員 `!上線` 才運作。
  - §4.3 訊息分流表最上方新增一列：`!上線` / `!下線`（`CHANNEL_ID` 頻道、管理員）→ **狀態切換**；並加註「待命或下線中，其餘一律忽略」。
  - §15 資料夾結構：`啟動bot.bat` 說明改為「手動啟動（有視窗）」，新增 `start_bot_hidden.vbs`（放進 `shell:startup` 開機背景待命）；`data/` 下新增 `startup.log`。
  - §16 新增小節「G. 上線／下線指令」，內容直接採用規格 §8 的實測清單（⚠️ 標記，尚未實測）。
  - 檔頭的測試數量更新為實際 `uv run pytest` 的數字。
- [ ] **Step 2: `README.md`**
  - 「啟動」段落：說明開機後待命、管理員輸入 `!上線` / `!下線`；背景啟動改為把 `start_bot_hidden.vbs` 的捷徑放進 `shell:startup`，並提醒**刪掉舊的 `啟動bot.bat` 捷徑**；說明意外當掉被自動重開後會回到待命，需要再 `!上線`。
  - 「在 Discord 裡怎麼用」新增 `!上線` / `!下線` 一條。
- [ ] **Step 3: 最終驗證**

Run: `uv run pytest -q` 與 `uv run python tools/guard_lines.py`
Expected: 全部通過；四段防護成對、全部開啟。再 `git status` 確認沒有 `.env`、`data/` 內容被追蹤。不 commit，等使用者指示。
