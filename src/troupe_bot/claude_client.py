"""呼叫本機 `claude -p`：把照片與文字放進一次性的暫存資料夾，要求固定格式 JSON，解析並驗證。

防護 1（檔案範圍隔離）與防護 2（上傳者文字只當資料）都在 _once() 裡。
注意：提示詞走 stdin（不經命令列），輸出一律用 UTF-8 解碼（Windows 預設是 cp950，中文會亂碼）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from .config import CLAUDE_RETRIES, CLAUDE_TIMEOUT_SECONDS
from .tasks import DATA_RULE_SYSTEM_PROMPT, AnalysisFailed

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    returncode: int
    stdout: bytes
    stderr: bytes


Runner = Callable[[list[str], bytes, Path, float], Awaitable[RunResult]]


async def _kill_tree(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is None:
        if sys.platform == "win32":
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/T", "/F", "/PID", str(proc.pid),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
        else:
            proc.kill()
    await proc.wait()


async def subprocess_runner(args: list[str], stdin: bytes, cwd: Path, timeout: float) -> RunResult:
    proc = await asyncio.create_subprocess_exec(
        *args, cwd=str(cwd),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin), timeout)
    except asyncio.TimeoutError:
        await _kill_tree(proc)
        raise AnalysisFailed("claude -p 逾時") from None
    return RunResult(proc.returncode, out, err)


_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def extract_payload(stdout: bytes) -> Any:
    """從 `claude -p --output-format json` 的輸出取出模型回的 JSON。"""
    try:
        envelope = json.loads(stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        raise AnalysisFailed("claude 的輸出不是 JSON") from None
    if not isinstance(envelope, dict):
        raise AnalysisFailed("claude 的輸出格式不對")
    if envelope.get("is_error"):
        raise AnalysisFailed("claude 回報錯誤")
    structured = envelope.get("structured_output")
    if structured is not None:
        return structured
    result = envelope.get("result")
    if not isinstance(result, str):
        raise AnalysisFailed("claude 沒有回傳內容")
    text = result.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise AnalysisFailed("模型回的內容不是合法 JSON") from None


async def _once(
    *, claude_path, model, data_dir, instruction, schema, user_text, text_name, photos, parse, runner, timeout,
):
    # 不防護的原始值：上傳者的字直接接在指令後面；
    # 為了讓 claude 讀得到照片，暫存資料夾開在 DATA_DIR 底下，並把整個 DATA_DIR 開放給它讀
    instruction_text = instruction + ("\n\n" + user_text if user_text else "")
    job_parent: Path | None = data_dir / "tmp"
    flags: list[str] = ["--add-dir", str(data_dir), "--allowedTools", "Read"]
    text_file: tuple[str, str] | None = None

    # ==== 防護 1：claude -p 的檔案範圍隔離　開始 ====
    job_parent = None  # 改開在作業系統暫存區，不在 DATA_DIR 底下
    flags = ["--restricted", "--tools", "Read", "--strict-mcp-config"]  # 覆蓋上面的設定：只剩 Read，且只能碰這個暫存資料夾
    # ==== 防護 1 結束 ====

    # ==== 防護 2：上傳者文字只當資料　開始 ====
    instruction_text = instruction  # 指令永遠是固定常數
    text_file = (text_name, user_text)  # 上傳者的字放進檔案，當作「要分析的資料」
    flags += ["--append-system-prompt", DATA_RULE_SYSTEM_PROMPT]
    # ==== 防護 2 結束 ====

    if job_parent is not None:
        job_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="troupe-", dir=job_parent, ignore_cleanup_errors=True) as tmp:
        job = Path(tmp)
        for i, data in enumerate(photos, start=1):
            (job / f"photo{i}.jpg").write_bytes(data)
        if text_file and text_file[1].strip():
            (job / text_file[0]).write_text(text_file[1], encoding="utf-8")
        args = [
            claude_path, "-p", "--model", model,
            "--output-format", "json", "--json-schema", json.dumps(schema, ensure_ascii=False),
            "--no-session-persistence", *flags,
        ]
        result = await runner(args, instruction_text.encode("utf-8"), job, timeout)

    if result.returncode != 0:
        raise AnalysisFailed(f"claude 結束代碼 {result.returncode}：{result.stderr.decode('utf-8', 'replace')[:200]}")
    return parse(extract_payload(result.stdout))


async def run_task(
    *,
    claude_path: str,
    model: str,
    data_dir: Path,
    instruction: str,
    schema: dict,
    user_text: str,
    text_name: str,
    photos: list[bytes],
    parse: Callable[[Any], Any],
    runner: Runner | None = None,
    retries: int = CLAUDE_RETRIES,
    timeout: float = CLAUDE_TIMEOUT_SECONDS,
) -> Any:
    """執行一件 claude -p 工作；逾時、結束代碼不為 0、輸出不合格時重試，最後仍失敗才丟 AnalysisFailed。"""
    runner = runner or subprocess_runner
    last: AnalysisFailed | None = None
    for attempt in range(1, retries + 2):
        try:
            return await _once(
                claude_path=claude_path, model=model, data_dir=data_dir, instruction=instruction, schema=schema,
                user_text=user_text, text_name=text_name, photos=photos, parse=parse, runner=runner, timeout=timeout,
            )
        except AnalysisFailed as exc:
            last = exc
            log.warning("claude -p 第 %d 次失敗：%s", attempt, exc)
    assert last is not None
    raise last
