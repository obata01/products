from src.common.lib.bases import BaseModel


class CheckpointConfig(BaseModel, frozen=True):
    """チェックポイントの設定."""

    kind: str
    dsn: str
