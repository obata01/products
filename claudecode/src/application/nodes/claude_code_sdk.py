"""Claude Agent SDK を利用してユーザーメッセージを処理するノード.

CLI 版 (src/application/nodes/claude_code.py) と同じ責務を果たすが、
subprocess 管理と stream-json のパースを SDK に委譲することで実装が薄い.
dispatch するカスタムイベント (TOKEN / PROGRESS) は CLI 版と共通で、
フロントエンド側は実装差を意識する必要がない。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    query,
)
from langchain_core.messages import AIMessage

from src.application.nodes._claude_code_shared import (
    dispatch_progress,
    dispatch_token,
    is_session_initialized,
    raise_claude_code_error,
    resolve_session_id,
)
from src.common.lib import logging
from src.common.settings.app import settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from langchain_core.runnables import RunnableConfig

    from src.application.states import State

logger = logging.getLogger(__name__)

_STDERR_TAIL_LINES = 20
_RESULT_ERROR_SUBTYPE_DETAILS: dict[str, str] = {
    "error_max_turns": "最大ターン数 ({max_turns}) に達したため処理を完了できませんでした。",
    "error_during_execution": "Claude Code の実行中にエラーが発生しました。",
}


@dataclass
class _SdkRunResult:
    """SDK ストリーム消費結果. ResultMessage で返るメタ情報も保持する."""

    full_text: str
    session_initialized: bool
    result_message: ResultMessage | None


def _build_options(
    session_id: str | None,
    *,
    resume: bool,
    stderr_callback: Any,
) -> ClaudeAgentOptions:
    """Claude Agent SDK のオプションを構築する.

    Args:
        session_id: Claude Code セッション ID (UUID). None のときは SDK が新規発行する.
        resume: 既存セッションの継続なら True (`resume=`). 新規作成なら False (`session_id=`).
        stderr_callback: CLI の stderr 1 行ごとに呼ばれるコールバック.

    Returns:
        ClaudeAgentOptions.
    """
    max_turns = settings.claude_code_max_turns if settings.claude_code_max_turns > 0 else None
    return ClaudeAgentOptions(
        session_id=None if resume else session_id,
        resume=session_id if resume else None,
        include_partial_messages=True,
        max_turns=max_turns,
        permission_mode=settings.claude_code_permission_mode,
        stderr=stderr_callback,
    )


async def _handle_stream_event(
    event: dict[str, Any],
    config: RunnableConfig,
    full_text: str,
) -> str:
    """StreamEvent が内包する Anthropic API の生イベントを処理する.

    text_delta はトークンとして、tool_use の開始は進捗として dispatch する。

    Args:
        event: StreamEvent.event フィールド (Anthropic API の生イベント).
        config: LangGraph から渡される RunnableConfig.
        full_text: これまでの生成テキスト.

    Returns:
        更新後の full_text.
    """
    event_type = event.get("type", "")

    if event_type == "content_block_delta":
        delta = event.get("delta", {})
        if delta.get("type") == "text_delta":
            text = delta.get("text", "")
            if text:
                await dispatch_token(text, config)
                return full_text + text
        return full_text

    if event_type == "content_block_start":
        block = event.get("content_block", {})
        if block.get("type") == "tool_use":
            tool_name = block.get("name", "")
            if tool_name:
                await dispatch_progress(f"ツール実行中: {tool_name}", config)

    return full_text


async def _handle_message(
    msg: Any,
    config: RunnableConfig,
    full_text: str,
) -> str:
    """SDK から届いた 1 メッセージを種別ごとに処理し、更新後の full_text を返す.

    Args:
        msg: SDK が yield するメッセージ (SystemMessage / StreamEvent / ResultMessage 等).
        config: LangGraph から渡される RunnableConfig.
        full_text: これまでの生成テキスト.

    Returns:
        更新後の full_text.
    """
    if isinstance(msg, SystemMessage):
        if msg.subtype == "init":
            await dispatch_progress("Claude Code セッション開始", config)
        return full_text

    if isinstance(msg, StreamEvent):
        return await _handle_stream_event(msg.event, config, full_text)

    if isinstance(msg, ResultMessage):
        if not msg.is_error and msg.result:
            return msg.result
        return full_text

    return full_text


async def _consume_messages(
    messages: AsyncIterator[Any],
    config: RunnableConfig,
) -> _SdkRunResult:
    """SDK の非同期イテレータを回しきり、累計テキストと観測結果を返す.

    SDK は ResultMessage を yield した後に "error" 制御メッセージを受け取ると
    素の ``Exception`` を送出する仕様 (claude_agent_sdk/_internal/query.py).
    この場合 ResultMessage に既にエラー詳細 (subtype / errors / permission_denials) が
    入っているため、ResultMessage を取得済みの例外は呑み込み、上位で
    ``_raise_for_result_error`` から具体的な ClaudeCodeError として送出させる.

    Args:
        messages: SDK `query(...)` が返す async iterator.
        config: LangGraph から渡される RunnableConfig.

    Returns:
        テキスト・init 観測フラグ・最終 ResultMessage をまとめた ``_SdkRunResult``.
    """
    full_text = ""
    session_initialized = False
    result_message: ResultMessage | None = None
    try:
        async for msg in messages:
            if isinstance(msg, SystemMessage) and msg.subtype == "init":
                session_initialized = True
            if isinstance(msg, ResultMessage):
                result_message = msg
            full_text = await _handle_message(msg, config, full_text)
    except Exception:
        if result_message is None:
            raise
        logger.debug("SDK terminal exception swallowed in favor of ResultMessage error info", exc_info=True)
    return _SdkRunResult(full_text=full_text, session_initialized=session_initialized, result_message=result_message)


def _summarize_permission_denials(result: ResultMessage) -> str | None:
    """ResultMessage の permission_denials を 1 行サマリにする.

    Args:
        result: SDK の最終 ResultMessage.

    Returns:
        サマリ文字列. 拒否がなければ None.
    """
    denials = getattr(result, "permission_denials", None) or []
    if not denials:
        return None
    tools = sorted({d.get("tool_name", "?") for d in denials})
    return f"権限拒否されたツール: {', '.join(tools)} (計 {len(denials)} 件)"


def _build_error_detail(result: ResultMessage) -> str:
    """エラー終了した ResultMessage から、人が読める detail を構築する.

    Args:
        result: ``is_error=True`` の ResultMessage.

    Returns:
        クライアントに返すエラー詳細メッセージ.
    """
    template = _RESULT_ERROR_SUBTYPE_DETAILS.get(
        result.subtype,
        "Claude Code の実行に失敗しました ({subtype})。",
    )
    base = template.format(subtype=result.subtype, max_turns=settings.claude_code_max_turns)

    parts = [base]
    if errors := getattr(result, "errors", None):
        parts.append("詳細: " + " / ".join(str(e) for e in errors))
    if denials_summary := _summarize_permission_denials(result):
        parts.append(denials_summary)
    return " ".join(parts)


def _raise_for_result_error(
    result: ResultMessage,
    *,
    session_id: str | None,
    prompt: str,
) -> None:
    """ResultMessage がエラーを示している場合に ClaudeCodeError を送出する.

    Args:
        result: SDK の最終 ResultMessage.
        session_id: セッション ID (ログ用).
        prompt: 元のユーザープロンプト (ログ用).

    Raises:
        ClaudeCodeError: エラー終了の場合に送出.
    """
    if not result.is_error:
        return
    raise_claude_code_error(
        logger,
        _build_error_detail(result),
        action="Claude Agent SDK 実行 (CLI エラー終了)",
        session_id=session_id,
        prompt=prompt,
        extra={
            "subtype": result.subtype,
            "errors": getattr(result, "errors", None),
            "permission_denials": getattr(result, "permission_denials", None),
            "num_turns": getattr(result, "num_turns", None),
        },
    )


async def claude_code_sdk(state: State, config: RunnableConfig) -> dict:
    """Claude Agent SDK でユーザーメッセージを処理するノード.

    SDK の `query(...)` を async iterator として回し、トークンと進捗を
    リアルタイムに dispatch する。最終テキストは ResultMessage.result を採用する.

    Args:
        state: 現在のワークフローステート.
        config: LangGraph から渡される RunnableConfig.

    Returns:
        chat_history キーに AIMessage を含む辞書.

    Note:
        `query(...)` は内部的にリクエストごとに CLI を都度起動・終了するステートレス実装。
        会話履歴は `ClaudeAgentOptions.session_id` / `resume` 経由で Claude Code 側の
        ローカルセッションに紐づける。起動オーバーヘッドは数百 ms 程度で現状実害は小さい
        ため当面この構成で運用し、応答時間を削りたくなった段階で ClaudeSDKClient 等の
        永続接続化を検討する.
    """
    message = state["last_user_message"]
    session_id = resolve_session_id(config)
    resume = is_session_initialized(state)
    stderr_lines: list[str] = []
    options = _build_options(session_id, resume=resume, stderr_callback=stderr_lines.append)

    logger.info(
        "Claude Agent SDK 実行開始: session_id=%s, resume=%s, prompt=%s",
        session_id,
        resume,
        message[:100],
    )

    try:
        run = await asyncio.wait_for(
            _consume_messages(query(prompt=message, options=options), config),
            timeout=settings.claude_code_timeout,
        )
    except TimeoutError:
        raise_claude_code_error(
            logger,
            f"Claude Code の処理が {settings.claude_code_timeout} 秒以内に完了しませんでした。",
            action="Claude Agent SDK 実行 (タイムアウト)",
            session_id=session_id,
            prompt=message,
            extra={
                "timeout_sec": settings.claude_code_timeout,
                "stderr_tail": stderr_lines[-_STDERR_TAIL_LINES:],
            },
        )
    except Exception as e:  # noqa: BLE001 — SDK は ClaudeSDKError 以外に素の Exception も投げる
        raise_claude_code_error(
            logger,
            f"Claude Code の実行に失敗しました: {e}",
            action="Claude Agent SDK 実行",
            session_id=session_id,
            prompt=message,
            extra={"stderr_tail": stderr_lines[-_STDERR_TAIL_LINES:]},
        )

    # CLI が exit 0 でも is_error=True を返すケース (max_turns 到達 / permission_denied 等)
    if run.result_message is not None:
        _raise_for_result_error(run.result_message, session_id=session_id, prompt=message)

    if not run.full_text:
        raise_claude_code_error(
            logger,
            "Claude Code から応答を取得できませんでした。",
            action="Claude Agent SDK 実行 (空応答)",
            session_id=session_id,
            prompt=message,
            extra={
                "session_initialized": run.session_initialized,
                "stderr_tail": stderr_lines[-_STDERR_TAIL_LINES:],
            },
        )

    logger.info(
        "Claude Agent SDK 完了: session_id=%s, result_length=%d, session_initialized=%s",
        session_id,
        len(run.full_text),
        run.session_initialized,
    )

    return {
        "chat_history": [AIMessage(content=run.full_text)],
        "claude_code_session_initialized": run.session_initialized,
    }
