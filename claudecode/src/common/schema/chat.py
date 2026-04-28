from uuid import UUID

from pydantic import Field, field_validator

from src.common.lib.bases import BaseModel


class ChatRequest(BaseModel, frozen=True):
    """チャットリクエストのスキーマ."""

    session_id: str | None = Field(
        default=None,
        description="セッションを一意に識別する UUID. 省略時はサーバ側で UUID を発行し、レスポンスに含めて返す.",
    )
    message: str = Field(description="ユーザーからの入力メッセージ.")
    stream: bool = Field(default=False, description="true のときストリーミングレスポンス (SSE) を返す.")

    @field_validator("session_id")
    @classmethod
    def _validate_uuid(cls, value: str | None) -> str | None:
        """session_id が UUID 形式であることを検証する.

        Raises:
            ValueError: UUID として解釈できない場合.
        """
        if value is None:
            return value
        try:
            UUID(value)
        except ValueError as e:
            msg = "session_id must be a valid UUID string"
            raise ValueError(msg) from e
        return value


class ChatResponse(BaseModel, frozen=True):
    """チャットレスポンスのスキーマ."""

    session_id: str = Field(description="リクエストと対応するセッション ID.")
    message: str = Field(description="アシスタントからの返答メッセージ.")
