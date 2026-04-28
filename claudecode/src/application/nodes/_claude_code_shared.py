"""Claude Code ノード (CLI / SDK) で共通利用する dispatch / エラーハンドリング.

CLI 版 / SDK 版のどちらの実装も、最終的にはフロントエンドに同じカスタムイベント
(TOKEN / PROGRESS) を流す。発行側の薄いラッパーと共通エラーユーティリティを
ここに集約する。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NoReturn

from langchain_core.callbacks import adispatch_custom_event

from src.application.stream import CLAUDE_CODE_PROGRESS_EVENT, CLAUDE_CODE_TOKEN_EVENT
from src.common.exceptions import ClaudeCodeError

if TYPE_CHECKING:
    from logging import Logger

    from langchain_core.runnables import RunnableConfig

    from src.application.states import State


_PROMPT_LOG_PREVIEW_LEN = 200


async def dispatch_token(delta: str, config: RunnableConfig) -> None:
    """トークンデルタをカスタムイベントとして dispatch する.

    Args:
        delta: 新たに生成されたテキスト差分.
        config: LangGraph から渡される RunnableConfig.
    """
    await adispatch_custom_event(CLAUDE_CODE_TOKEN_EVENT, {"text": delta}, config=config)


async def dispatch_progress(message: str, config: RunnableConfig) -> None:
    """進捗メッセージをカスタムイベントとして dispatch する.

    Args:
        message: 進捗の説明テキスト.
        config: LangGraph から渡される RunnableConfig.
    """
    await adispatch_custom_event(CLAUDE_CODE_PROGRESS_EVENT, {"message": message}, config=config)


def resolve_session_id(config: RunnableConfig) -> str | None:
    """RunnableConfig の thread_id を Claude Code セッション ID として取り出す.

    Args:
        config: LangGraph から渡される RunnableConfig.

    Returns:
        thread_id の値. 未設定の場合は None.
    """
    return config.get("configurable", {}).get("thread_id") if config else None


def is_session_initialized(state: State) -> bool:
    """State に Claude Code セッションが初期化済みフラグが立っているか判定する.

    過去の実行で Claude Code の init イベントを受信した場合にのみ True になる。
    True のときは `--resume`、False のときは `--session-id` を使う判断に用いる.

    Args:
        state: 現在のワークフローステート.

    Returns:
        初期化済みの場合 True.
    """
    return bool(state.get("claude_code_session_initialized", False))


def _truncate(text: str, limit: int) -> str:
    """長文をログ用に先頭 ``limit`` 文字へ切り詰める.

    Args:
        text: 対象テキスト.
        limit: 切り詰め上限.

    Returns:
        切り詰め済みのテキスト.
    """
    return text if len(text) <= limit else text[:limit] + "..."


def raise_claude_code_error(  # noqa: PLR0913
    logger: Logger,
    detail: str,
    *,
    action: str,
    session_id: str | None,
    prompt: str,
    extra: dict[str, object] | None = None,
) -> NoReturn:
    """ログにコンテキストを残した上で ``ClaudeCodeError`` を送出する.

    ノード内部で発生したエラーをクライアントに返すための共通入口。
    ``logger.exception`` で現在の例外を構造化フィールド付きで記録したうえで、
    クライアント向けの detail を持つ ``ClaudeCodeError`` を raise する.

    Args:
        logger: 呼び出し元ロガー.
        detail: クライアントに返すエラー詳細.
        action: 失敗したアクション名 (例: "Claude Agent SDK 実行").
        session_id: セッション ID.
        prompt: 実行中のユーザープロンプト. 先頭のみログに残す.
        extra: 追加でログに残したいキーと値.

    Raises:
        ClaudeCodeError: 常に送出する.
    """
    context: dict[str, object] = {
        "session_id": session_id,
        "prompt": _truncate(prompt, _PROMPT_LOG_PREVIEW_LEN),
    }
    if extra:
        context.update(extra)
    logger.exception("%s に失敗しました: %s", action, context)
    raise ClaudeCodeError(detail)


