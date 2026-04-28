from src.common.lib.bases import BaseModel
from src.common.schema.checkpoint import CheckpointConfig
from src.common.schema.llm import LLMs
from src.common.schema.node import NodeConfig


class AppConfig(BaseModel, frozen=True):
    """アプリケーション設定のルートモデル."""

    llms: LLMs
    nodes: list[NodeConfig]
    checkpoint: CheckpointConfig
