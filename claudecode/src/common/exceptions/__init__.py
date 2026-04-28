"""アプリケーション共通のカスタム例外.

API 境界で一貫したエラーレスポンスを返すため、例外の分類体系を定義する.
各例外は ``status_code`` と ``code`` を持ち、FastAPI の ``exception_handler`` や
SSE の ERROR イベントに変換される.
"""

from __future__ import annotations


class AppError(Exception):
    """アプリケーション共通の基底例外.

    Attributes:
        detail: 人が読めるエラー詳細 (クライアントに返す).
        code: クライアントが分岐に使う安定したエラーコード.
        status_code: HTTP ステータスコード.
    """

    status_code: int = 500
    code: str = "internal_error"

    def __init__(
        self,
        detail: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        """AppError を初期化する.

        Args:
            detail: エラー詳細メッセージ.
            code: エラーコードを上書きする場合に指定.
            status_code: HTTP ステータスコードを上書きする場合に指定.
        """
        super().__init__(detail)
        self.detail = detail
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code


class InvalidRequestError(AppError):
    """クライアント起因のリクエスト不正."""

    status_code = 400
    code = "invalid_request"


class ClaudeCodeError(AppError):
    """Claude Code CLI / SDK の実行エラー (上流起因)."""

    status_code = 502
    code = "claude_code_error"
