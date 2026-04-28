from pydantic import model_validator

from src.common.lib.bases import BaseModel
from src.components.llms.models import LLMParams, ProviderType


class NodeChatClientRef(BaseModel, frozen=True):
    """ノードが参照するチャットクライアントの指定."""

    provider: str
    client_name: str


class NodeEmbedClientRef(BaseModel, frozen=True):
    """ノードが参照する埋め込みクライアントの指定."""

    provider: str | None = None
    client_name: str | None = None


class ChatPromptConfig(BaseModel, frozen=True):
    """チャットプロンプトの設定."""

    template_file: str


class NodeConfig(BaseModel, frozen=True):
    """ノードの設定."""

    name: str
    chat_client: NodeChatClientRef
    chat_params: LLMParams
    chat_prompt: ChatPromptConfig
    embed_client: NodeEmbedClientRef | None = None

    @model_validator(mode="after")
    def _convert_azure_params(self) -> "NodeConfig":
        if self.chat_client.provider == ProviderType.AZURE:
            params = self.chat_params
            if params.max_tokens is not None and params.max_completion_tokens is None:
                converted = params.model_copy(update={"max_completion_tokens": params.max_tokens, "max_tokens": None})
                object.__setattr__(self, "chat_params", converted)
        return self
