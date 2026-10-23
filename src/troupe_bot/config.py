"""設定：從 .env 讀 DISCORD_TOKEN、CHANNEL_ID、CLAUDE_MODEL、DATA_DIR，並確認 claude 可用。

錯誤訊息只會說「哪個設定有問題」，不會把 token 印出來。
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REQUIRED = ("DISCORD_TOKEN", "CHANNEL_ID", "CLAUDE_MODEL", "DATA_DIR")

# 程式常數（不放 .env，維持設定只有四個變數）
CLAUDE_TIMEOUT_SECONDS = 120
CLAUDE_RETRIES = 1
QUEUE_MAX = 50
MAX_PHOTOS_PER_MESSAGE = 5
MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
EXCEL_RETRIES = 3  # Excel 被占用時先試 3 次（每次隔 3 秒），仍失敗就把資料暫存到 pending/ 等之後補登
EXCEL_RETRY_DELAY_SECONDS = 3.0
AWAITING_TIMEOUT_SECONDS = 600  # 照片裡有多種東西時，等上傳者回覆「分開／合併」的時間（10 分鐘）
PENDING_RETRY_SECONDS = 60  # 待補登的資料，每隔多久試著補寫一次


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    discord_token: str
    channel_id: int
    claude_model: str
    data_dir: Path
    claude_path: str

    @property
    def photos_dir(self) -> Path:
        return self.data_dir / "photos"

    @property
    def pending_dir(self) -> Path:
        return self.data_dir / "pending"

    @property
    def awaiting_dir(self) -> Path:
        return self.data_dir / "awaiting"

    @property
    def xlsx_path(self) -> Path:
        return self.data_dir / "inventory.xlsx"

    @property
    def log_path(self) -> Path:
        return self.data_dir / "bot.log"


def find_claude(which: Callable[[str], str | None] = shutil.which) -> str:
    path = which("claude")
    if not path:
        raise ConfigError("找不到 claude 指令。請先安裝 Claude Code，並確認在終端機輸入 claude 可以執行。")
    if path.lower().endswith((".cmd", ".bat")):
        raise ConfigError(
            f"PATH 裡先找到的 claude 是 {path}（.cmd/.bat 包裝檔）。"
            "它會經過 cmd.exe 解析參數，不安全也容易出錯；請讓 PATH 先找到 claude.exe（例如 ~\\.local\\bin\\claude.exe）。"
        )
    return path


def load_config(
    env: Mapping[str, str],
    project_root: Path = PROJECT_ROOT,
    which: Callable[[str], str | None] = shutil.which,
) -> Config:
    values = {name: (env.get(name) or "").strip() for name in REQUIRED}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ConfigError("缺少設定：" + "、".join(missing) + "（請在專案資料夾的 .env 裡填寫）")

    try:
        channel_id = int(values["CHANNEL_ID"])
    except ValueError:
        raise ConfigError("CHANNEL_ID 必須是一串數字（在 Discord 對頻道按右鍵 → 複製頻道 ID）") from None

    if not values["DISCORD_TOKEN"].isascii():
        raise ConfigError("DISCORD_TOKEN 還是佔位字串，請在 .env 裡換成真正的 bot token")

    data_dir = Path(values["DATA_DIR"])
    if not data_dir.is_absolute():
        data_dir = project_root / data_dir

    return Config(
        discord_token=values["DISCORD_TOKEN"],
        channel_id=channel_id,
        claude_model=values["CLAUDE_MODEL"],
        data_dir=data_dir.resolve(),
        claude_path=find_claude(which),
    )


def load_from_environment(project_root: Path = PROJECT_ROOT) -> Config:
    """.env 的內容為底，系統環境變數優先。"""
    env = {**{k: v for k, v in dotenv_values(project_root / ".env").items() if v is not None}, **os.environ}
    return load_config(env, project_root)
