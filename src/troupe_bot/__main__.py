"""啟動：uv run python -m troupe_bot（在專案資料夾執行）。

四段防護（一開始全部開啟）。行號只是大約位置，改過程式後請用 `uv run python tools/guard_lines.py` 重新查：
    防護 1：claude -p 的檔案範圍隔離        claude_client.py 約第 100–103 行（_once 裡）
    防護 2：上傳者文字只當資料              claude_client.py 約第 105–109 行（_once 裡，緊接在防護 1 後面）
    防護 3：檔名清洗                        photos.py 約第 98–101 行（photo_paths 裡）
    防護 4：Excel 公式處理                  store.py 約第 125–129 行（_set_text 裡）
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

import discord

from .bot import TroupeBot
from .config import EXCEL_RETRIES, EXCEL_RETRY_DELAY_SECONDS, Config, ConfigError, load_from_environment
from .handlers import Services
from .store import ExcelBusy, Store


def setup_logging(cfg: Config) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)
    console.addFilter(lambda record: "voice will NOT be supported" not in record.getMessage())  # 我們不用語音
    logfile = RotatingFileHandler(cfg.log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    logfile.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers[:] = [console, logfile]


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # 終端機遇到顯示不了的字元時用 ? 取代，不要讓程式因此當掉
        stream.reconfigure(errors="replace")

    try:
        cfg = load_from_environment()
    except ConfigError as exc:
        print(f"設定錯誤：{exc}", file=sys.stderr)
        return 2

    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.photos_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(cfg)
    store = Store(cfg.xlsx_path, retries=EXCEL_RETRIES, delay=EXCEL_RETRY_DELAY_SECONDS)
    try:
        store.ensure()  # 沒有檔案就建立；舊版的檔案會補上新增的欄位
    except ExcelBusy:
        print(
            f"無法啟動：{cfg.xlsx_path} 正被 Excel 打開著，沒辦法補上新的欄位。請先把它關掉再啟動。",
            file=sys.stderr,
        )
        return 5
    bot = TroupeBot(Services(cfg=cfg, store=store))

    log = logging.getLogger("troupe_bot")
    log.info("啟動中…資料夾：%s，模型：%s", cfg.data_dir, cfg.claude_model)
    try:
        bot.run(cfg.discord_token, log_handler=None)
    except discord.LoginFailure:
        print("登入失敗：DISCORD_TOKEN 不正確。請到 Developer Portal → Bot → Reset Token 重新取得，貼進 .env。", file=sys.stderr)
        return 3
    except discord.PrivilegedIntentsRequired:
        print(
            "Discord 拒絕了 Message Content Intent。請到 Developer Portal → Bot → Privileged Gateway Intents，"
            "打開 MESSAGE CONTENT INTENT 並按 Save Changes。",
            file=sys.stderr,
        )
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
