# Discord Bot 設定步驟

目標：在 Discord Developer Portal 建立 bot、打開 Message Content Intent、拿到 bot token，並把 bot 邀進你自己的 Server。

做這份文件之前，先做完 `docs/discord-server-setup.md`（你需要先有 Server 和 `CHANNEL_ID`）。

> Discord Developer Portal 的畫面大多是英文，按鈕名稱我直接寫英文，後面括號放中文意思。
> Discord 偶爾會改畫面，如果名稱有一點不同，找意思最接近的那個。

---

## ⚠️ 先看這個：bot token 是密碼

**bot token 等於 bot 的登入密碼。誰拿到它，誰就能用你的 bot 做任何事（發訊息、讀頻道內容、破壞你的 Server）。**

絕對不可以：

- ❌ 貼給任何人（包含同學、老師、朋友）
- ❌ **貼進跟 Claude 的這個對話**（也不要貼進其他任何 AI 對話）
- ❌ **commit 進 git**，或 push 到 GitHub
- ❌ 截圖時讓它入鏡，或貼在 Discord 頻道、群組、Google 文件裡

token 只能放在你電腦上的 `.env` 檔裡（專案的 `.gitignore` 已經設好會忽略它）。

> 如果 token 不小心外流了：馬上回到這份文件的步驟 4，按 **Reset Token** 產生新的，舊的就會立刻失效。然後把新的 token 更新到 `.env`。

另外分清楚兩個很像的東西：

| 東西 | 是什麼 | 可以給同學嗎 |
|---|---|---|
| 邀請連結（`discord.gg/...`） | 讓人加入 Server | 可以 |
| `CHANNEL_ID` | 頻道編號 | 可以 |
| **bot token** | **bot 的密碼** | **絕對不行** |

---

## 步驟 1：建立 Application

1. 用瀏覽器打開 <https://discord.com/developers/applications>。
2. 如果要你登入，用**你建立 Server 的那個 Discord 帳號**登入。
3. 看畫面**右上角**，點藍紫色的 **New Application**（新增應用程式）。
4. 跳出一個視窗，在 **Name** 那一格輸入名字，例如：`劇團資產管理員`。這個名字就是 bot 在 Discord 裡顯示的名字。
5. 勾選下面那個同意條款的勾勾（*I agree to the Discord Developer Terms of Service and Developer Policy*）。
6. 點 **Create**。
7. 你會進到這個 application 的設定頁。看**左邊**有一排選單（General Information、Installation、OAuth2、Bot…），後面的步驟都在這排選單裡操作。

---

## 步驟 2：先把 bot 設成「只有我能邀請」

1. 點左邊選單的 **Bot**。
2. 往下捲，找到 **Public Bot**（公開的 bot）這個開關，把它**關掉**（變成灰色）。
   - 意思：只有你自己能把這個 bot 加進 Server，別人就算拿到你的 application ID 也加不了。
3. 如果頁面下方跳出一條「有未儲存的變更」的黑色列，點 **Save Changes**。
   - 如果關閉時出現錯誤訊息說跟 *Requires OAuth2 Code Grant* 有關，確認左邊 **OAuth2** 頁的那個開關也是關閉的，再回來關 Public Bot。

---

## 步驟 3：打開 Message Content Intent（一定要做）

### 為什麼一定要打開？

Discord 預設不會把「訊息內容」給 bot。我們的 agent 需要讀：

- 上傳者在照片旁邊寫的**文字說明**（例如「放 B 區 03 箱」「白蛇傳用」）
- 訊息附帶的**照片附件**

沒有打開 Message Content Intent，bot 雖然看得到「有人傳了訊息」，但**文字說明和附件會是空的**，等於完全讀不到照片。這個權限屬於 Discord 的「特權權限」（Privileged Intent），要在這裡手動打開，程式裡光是要求是沒用的。

### 怎麼打開

1. 還在左邊選單的 **Bot** 頁。
2. 往下捲，找到 **Privileged Gateway Intents**（特權閘道意圖）這一區。
3. 這一區有三個開關：Presence Intent、Server Members Intent、**Message Content Intent**。
4. **只把 Message Content Intent 打開**（變成藍色/綠色）。另外兩個保持關閉，我們用不到。
5. 畫面下方會跳出一條黑色的列，寫著有未儲存的變更。點 **Save Changes**。
6. **一定要確認有儲存**：重新整理頁面（`F5`），再看一次 Message Content Intent 還是開著的才算成功。

> 之後如果程式啟動時看到 `PrivilegedIntentsRequired` 的錯誤，就是這一步沒打開或沒儲存。

---

## 步驟 4：拿到 bot token

1. 還在左邊選單的 **Bot** 頁，往上看到 **Token** 這一區。
2. 點 **Reset Token**（重設 token）。
   - 第一次產生也是按這個按鈕，不是只有「已經有 token 才能重設」。
3. 跳出確認視窗，點 **Yes, do it!**。
4. Discord 可能會要你輸入密碼或兩步驟驗證碼，照著做。
5. 畫面會出現一長串英文數字和點（約 70 個字元），這就是 bot token。
6. **這串只會顯示這一次**，離開頁面就看不到了（只能重新產生）。馬上做下一步。

### 把 token 放進 `.env`（只放這裡）

1. 打開檔案總管，進入專案資料夾 `C:\Users\a0903\20261021`。
2. 在資料夾空白處按滑鼠右鍵 → **新增** → **文字文件**。
3. 打開這個新文字文件（記事本），貼上下面四行，然後把 `你的token` 和 `你的頻道ID` 換掉：

   ```
   DISCORD_TOKEN=你的token
   CHANNEL_ID=你的頻道ID
   CLAUDE_MODEL=claude-haiku-5-5
   DATA_DIR=./data
   ```

   - `DISCORD_TOKEN=` 後面：回到 Developer Portal，點 token 旁邊的 **Copy**，再回記事本貼上。等號兩邊**不要有空格**，也**不要加引號**。
   - `CHANNEL_ID=` 後面：貼上 `docs/discord-server-setup.md` 步驟 C-2 拿到的那串數字。
4. 在記事本點 **檔案** → **另存新檔**。
5. 「檔案名稱」輸入 `.env`（前面有一個點，**沒有**其他副檔名）。
6. **「存檔類型」要選「所有檔案」**，否則記事本會偷偷存成 `.env.txt`，程式就讀不到。
7. 存檔位置確認是 `C:\Users\a0903\20261021`，點 **存檔**。
8. 關掉記事本。

### 確認 `.env` 沒有被 git 追蹤

1. 在專案資料夾空白處按 `Shift` + 滑鼠右鍵，選 **在此處開啟 PowerShell 視窗**（或「在終端機中開啟」）。
2. 輸入：`git status`，按 Enter。
3. 畫面上**不應該**出現 `.env`。沒出現就是正確的（它已被 `.gitignore` 忽略）。
4. 如果 `.env` 出現在「未追蹤的檔案」清單，**不要 commit**，先停下來問我。

> 再提醒一次：**不要把 `.env` 的內容貼進跟 Claude 的對話**。要請我幫忙看設定問題時，只說「token 已經放好了」，或把 token 那一行遮掉再貼。

---

## 步驟 5：產生邀請網址並把 bot 邀進你的 Server

### 5-1 選權限

1. 點左邊選單的 **OAuth2**。
2. 往下捲，找到 **OAuth2 URL Generator** 這一區。
3. 在 **Scopes**（範圍）那一大塊清單，**只勾選 `bot`**。其他都不要勾（也不需要勾 `applications.commands`）。
4. 勾了 `bot` 之後，下面會出現 **Bot Permissions**（bot 權限）一大塊清單。只勾這三個，其他都不要勾：

   | 權限 | 在清單的哪一區 | 為什麼需要 |
   |---|---|---|
   | **View Channels**（檢視頻道） | General Permissions | 看得到頻道才讀得到照片 |
   | **Send Messages**（傳送訊息） | Text Permissions | 回覆「處理中」和歸檔結果 |
   | **Read Message History**（讀取訊息歷史） | Text Permissions | 回覆某則歸檔訊息時，要能找到被回覆的那則 |

5. **絕對不要勾 Administrator（管理員）**。bot 只拿它需要的權限，萬一出事影響最小。
6. 如果清單下方有 **Integration Type**（安裝類型），選 **Guild Install**（安裝到伺服器）。

### 5-2 複製網址並邀請

1. 捲到最下面，**Generated URL** 那一格會有一條很長的網址，開頭是 `https://discord.com/oauth2/authorize?client_id=...`。
2. 點旁邊的 **Copy**。
3. 開新的瀏覽器分頁，貼上網址，按 Enter。
4. 出現「把 XXX 加進伺服器」的畫面，點 **Add to Server** 下面的下拉選單，選**你自己的 Server**（例如「劇團道具倉庫」）。
   - 如果下拉選單裡找不到你的 Server：你現在登入的帳號不是 Server 擁有者，換成建立 Server 的那個帳號。
5. 點 **繼續**（*Continue*）。
6. 下一頁會列出 bot 會得到的權限，確認只有上面那三個（檢視頻道、傳送訊息、讀取訊息歷史），點 **授權**（*Authorize*）。
7. 做人機驗證（勾「我不是機器人」之類的）。
8. 看到「已授權」就完成了。

> 小提示：網址裡面會有 `permissions=68608`，這就是上面三個權限加起來的數字。看到這個數字代表你只勾了這三個。

### 5-3 確認 bot 進來了

1. 回到 Discord，打開你的 Server，點 `# 資產登記`。
2. 頻道裡會出現一行系統訊息：「XXX 加入了這個伺服器」。
3. 看右邊成員列表，往下找到「機器人」(BOT) 分類，會看到你的 bot。
4. **它現在是「離線」是正常的**，因為程式還沒有執行。bot 程式啟動後才會變成「線上」。

---

## 完成檢查表

- [ ] 我在 Developer Portal 建立了 application
- [ ] Public Bot 已關閉
- [ ] **Message Content Intent 已打開，而且重新整理後還是開著**
- [ ] 我已經拿到 token，並放進 `C:\Users\a0903\20261021\.env`
- [ ] `.env` 的檔名沒有被存成 `.env.txt`
- [ ] 我執行 `git status` 看不到 `.env`
- [ ] 邀請網址只勾了 `bot`，權限只有檢視頻道、傳送訊息、讀取訊息歷史（沒有 Administrator）
- [ ] bot 出現在 Server 的成員列表（離線沒關係）
- [ ] **我沒有把 token 貼給任何人，也沒有貼進跟 Claude 的對話**

## 常見問題

| 狀況 | 怎麼辦 |
|---|---|
| 程式啟動出現 `PrivilegedIntentsRequired` | 步驟 3 沒打開或沒按 Save Changes，重做並重新整理確認 |
| 程式啟動出現 `LoginFailure` / `Improper token` | token 貼錯（多了空格、引號，或少複製一段）。回步驟 4 按 Reset Token 產生新的，重貼 |
| bot 上線了但看不到照片和文字 | Message Content Intent 沒開，見步驟 3 |
| bot 上線了但不回覆 | 檢查 `.env` 的 `CHANNEL_ID` 是不是 `# 資產登記` 的 ID；檢查 bot 在這個頻道有「檢視頻道」和「傳送訊息」 |
| 找不到 `.env` 檔 | 檔案總管預設會隱藏副檔名，點上方 **檢視** → **顯示** → 勾選 **副檔名**；確認不是 `.env.txt` |
| token 不小心貼出去了 | 馬上回步驟 4 按 Reset Token，舊的立刻失效，再更新 `.env` |
| 邀請網址授權時找不到我的 Server | 登入的帳號不是 Server 擁有者，換成建立 Server 的帳號 |
