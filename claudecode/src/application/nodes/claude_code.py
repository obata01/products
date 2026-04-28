"""Claude Code CLI を呼び出してユーザーメッセージを処理するノード.

Claude Code の stream-json 出力をパースし、トークン単位でカスタムイベントを
dispatch することで LangGraph の astream_events 経由のストリーミングを実現する。
ファイルシステムへの書き込みは行わず、すべてメモリ上で完結する。
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage

from src.application.nodes._claude_code_shared import (
    dispatch_progress,
    dispatch_token,
    is_session_initialized,
    raise_claude_code_error,
    resolve_session_id,
)
from src.common.defs.claude_code import (
    ClaudeCodeContentBlockType,
    ClaudeCodeEventType,
    ClaudeCodeSystemSubtype,
)
from src.common.lib import logging
from src.common.settings.app import settings

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

    from src.application.states import State

logger = logging.getLogger(__name__)


def _extract_assistant_text(content_blocks: list[dict[str, Any]]) -> str:
    """Assistant メッセージの content blocks からテキストを結合して返す.

    Args:
        content_blocks: Claude Code が返す content block のリスト.

    Returns:
        結合されたテキスト.
    """
    return "".join(
        block.get("text", "")
        for block in content_blocks
        if isinstance(block, dict) and block.get("type") == ClaudeCodeContentBlockType.TEXT
    )


def _build_command(message: str, session_id: str | None, *, resume: bool) -> list[str]:
    """Claude Code CLI の実行コマンドを構築する.

    Args:
        message: ユーザーからの入力メッセージ.
        session_id: Claude Code セッション ID (UUID). None のときは付けない.
        resume: 既存セッションの継続なら True (`--resume`). 新規作成なら False (`--session-id`).

    Returns:
        subprocess に渡すコマンドリスト.
    """
    cmd = [settings.claude_code_cli_path]
    if session_id:
        flag = "--resume" if resume else "--session-id"
        cmd.extend([flag, session_id])
    cmd.extend(
        [
            # NOTE: --bare は OAuth 認証と併用すると認証エラーになるため除外
            "-p",
            message,
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
        ]
    )
    if settings.claude_code_max_turns > 0:
        cmd.extend(["--max-turns", str(settings.claude_code_max_turns)])
    if settings.claude_code_permission_mode is not None:
        cmd.extend(["--permission-mode", settings.claude_code_permission_mode])
    return cmd


def _is_init_event(event: dict[str, Any]) -> bool:
    """イベントが Claude Code のセッション初期化通知かを判定する.

    Args:
        event: パース済みの stream-json イベント.

    Returns:
        `type == "system"` かつ `subtype == "init"` の場合 True.
    """
    return (
        event.get("type") == ClaudeCodeEventType.SYSTEM
        and event.get("subtype") == ClaudeCodeSystemSubtype.INIT
    )


async def _drain_stderr(proc: asyncio.subprocess.Process) -> str:
    """Stderr を非同期で読み切って返す.

    stdout と同時に drain することでパイプバッファのデッドロックを防ぐ。

    Args:
        proc: 実行中のサブプロセス.

    Returns:
        stderr の内容.
    """
    data = await proc.stderr.read()
    return data.decode("utf-8", errors="replace")


async def _handle_event(
    event: dict[str, Any],
    config: RunnableConfig,
    full_text: str,
    prev_len: int,
) -> tuple[str, int]:
    """Stream-json の 1 イベントを処理しカスタムイベントを dispatch する.

    Args:
        event: パース済みの stream-json イベント.
        config: LangGraph から渡される RunnableConfig.
        full_text: これまでの生成テキスト全文.
        prev_len: 前回までのテキスト長 (デルタ計算用).

    Returns:
        (更新後の full_text, 更新後の prev_len) のタプル.
    """
    event_type = event.get("type", "")

    if event_type == ClaudeCodeEventType.ASSISTANT:
        content_blocks = event.get("message", {}).get("content", [])
        text = _extract_assistant_text(content_blocks)
        delta = text[prev_len:]
        if delta:
            await dispatch_token(delta, config)
            return text, len(text)
        return full_text, len(text)

    if event_type == ClaudeCodeEventType.RESULT:
        return event.get("result", full_text), prev_len

    if event_type == ClaudeCodeEventType.SYSTEM and event.get("subtype") == ClaudeCodeSystemSubtype.INIT:
        await dispatch_progress("Claude Code セッション開始", config)

    elif event_type == ClaudeCodeEventType.TOOL_USE:
        tool_name = event.get("tool", event.get("name", ""))
        if tool_name:
            await dispatch_progress(f"ツール実行中: {tool_name}", config)

    return full_text, prev_len


async def _process_stream(
    proc: asyncio.subprocess.Process,
    config: RunnableConfig,
) -> tuple[str, bool]:
    """Claude Code CLI の stream-json 出力をパースしてイベントを dispatch する.

    Args:
        proc: 実行中の Claude Code サブプロセス.
        config: LangGraph から渡される RunnableConfig.

    Returns:
        (最終的な生成テキスト, セッション init を観測したか) のタプル.
    """
    full_text = ""
    prev_len = 0
    session_initialized = False

    async for raw_line in proc.stdout:
        line = raw_line.decode("utf-8").strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            logger.debug("Claude Code: JSON パース失敗: %s", line[:200])
            continue

        if _is_init_event(event):
            session_initialized = True

        full_text, prev_len = await _handle_event(event, config, full_text, prev_len)

    return full_text, session_initialized


async def claude_code(state: State, config: RunnableConfig) -> dict:
    """Claude Code CLI でユーザーメッセージを処理するノード.

    subprocess で Claude Code を非対話実行し、stream-json 出力から
    トークンと進捗をリアルタイムに dispatch する。
    ファイル I/O は行わずメモリ上で完結する。

    Args:
        state: 現在のワークフローステート.
        config: LangGraph から渡される RunnableConfig.

    Returns:
        chat_history キーに AIMessage を含む辞書.

    Note:
        リクエストごとに CLI を都度起動・終了するステートレス設計。会話履歴は
        `--session-id` / `--resume` で Claude Code 側のローカルセッションに紐づける。
        起動オーバーヘッドは数百 ms 程度で現状実害は小さいため当面この構成で運用し、
        応答時間を削りたくなった段階で ClaudeSDKClient 等の永続接続化を検討する.
    """
    message = state["last_user_message"]
    session_id = resolve_session_id(config)
    resume = is_session_initialized(state)
    cmd = _build_command(message, session_id, resume=resume)

    logger.info(
        "Claude Code CLI 実行開始: session_id=%s, resume=%s, prompt=%s",
        session_id,
        resume,
        message[:100],
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        raise_claude_code_error(
            logger,
            f"Claude Code CLI が見つかりません (path={settings.claude_code_cli_path})。",
            action="Claude Code CLI 起動",
            session_id=session_id,
            prompt=message,
            extra={"cli_path": settings.claude_code_cli_path},
        )

    # stdout と stderr を並行して読み取り、パイプバッファのデッドロックを防止する
    stderr_task = asyncio.create_task(_drain_stderr(proc))

    try:
        full_text, session_initialized = await asyncio.wait_for(
            _process_stream(proc, config),
            timeout=settings.claude_code_timeout,
        )
    except TimeoutError:
        proc.kill()
        await proc.wait()
        stderr_text = await stderr_task
        raise_claude_code_error(
            logger,
            f"Claude Code の処理が {settings.claude_code_timeout} 秒以内に完了しませんでした。",
            action="Claude Code CLI 実行 (タイムアウト)",
            session_id=session_id,
            prompt=message,
            extra={
                "timeout_sec": settings.claude_code_timeout,
                "stderr": stderr_text[:500],
            },
        )

    await proc.wait()
    stderr_text = await stderr_task

    if proc.returncode != 0:
        raise_claude_code_error(
            logger,
            f"Claude Code CLI が失敗しました: {stderr_text.strip()[:200] or 'no stderr output'}",
            action="Claude Code CLI 実行",
            session_id=session_id,
            prompt=message,
            extra={"returncode": proc.returncode, "stderr": stderr_text[:500]},
        )

    if not full_text:
        raise_claude_code_error(
            logger,
            "Claude Code から応答を取得できませんでした。",
            action="Claude Code CLI 実行 (空応答)",
            session_id=session_id,
            prompt=message,
            extra={"session_initialized": session_initialized},
        )

    logger.info(
        "Claude Code CLI 完了: session_id=%s, result_length=%d, session_initialized=%s",
        session_id,
        len(full_text),
        session_initialized,
    )

    return {
        "chat_history": [AIMessage(content=full_text)],
        "claude_code_session_initialized": session_initialized,
    }
