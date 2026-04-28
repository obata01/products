from pydantic import Field, model_validator

from src.common.lib.bases import BaseModel
from src.common.schema._helpers import to_azure_params
from src.components.llms.models import LLMParams

# --- Bedrock ---


class BedrockChatClientConfig(BaseModel, frozen=True):
    """Bedrock チャットクライアントの接続設定."""

    model_id: str
    region_name: str


class BedrockChatClient(BaseModel, frozen=True):
    """Bedrock チャットクライアントの定義."""

    name: str
    config: BedrockChatClientConfig
    default_params: LLMParams


# --- Azure OpenAI ---


class AzureChatClientConfig(BaseModel, frozen=True):
    """Azure チャットクライアントの接続設定."""

    model: str
    azure_deployment: str
    azure_endpoint_env: str
    api_key_env: str
    openai_api_version: str
    use_responses_api: bool = False


class AzureChatClient(BaseModel, frozen=True):
    """Azure チャットクライアントの定義."""

    name: str
    config: AzureChatClientConfig
    default_params: LLMParams

    @model_validator(mode="after")
    def _convert_azure_params(self) -> "AzureChatClient":
        if self.config.use_responses_api:
            return self
        return to_azure_params(self, "default_params")


# --- OpenAI ---


class OpenAIChatClientConfig(BaseModel, frozen=True):
    """OpenAI チャットクライアントの接続設定."""

    model: str
    api_key_env: str
    use_responses_api: bool = False


class OpenAIChatClient(BaseModel, frozen=True):
    """OpenAI チャットクライアントの定義."""

    name: str
    config: OpenAIChatClientConfig
    default_params: LLMParams


# --- チャットクライアントコレクション ---


class ChatClients(BaseModel, frozen=True):
    """チャットクライアントのプロバイダー別コレクション."""

    bedrock: list[BedrockChatClient] = Field(default_factory=list)
    azure: list[AzureChatClient] = Field(default_factory=list)
    openai: list[OpenAIChatClient] = Field(default_factory=list)


# --- Bedrock 埋め込みクライアント ---


class BedrockEmbedClientConfig(BaseModel, frozen=True):
    """Bedrock 埋め込みクライアントの接続設定."""

    model_id: str
    region_name: str


class BedrockEmbedClient(BaseModel, frozen=True):
    """Bedrock 埋め込みクライアントの定義."""

    name: str
    config: BedrockEmbedClientConfig


# --- Azure OpenAI 埋め込みクライアント ---


class AzureEmbedClientConfig(BaseModel, frozen=True):
    """Azure 埋め込みクライアントの接続設定."""

    model: str
    azure_deployment: str
    azure_endpoint_env: str
    api_key_env: str
    openai_api_version: str


class AzureEmbedClient(BaseModel, frozen=True):
    """Azure 埋め込みクライアントの定義."""

    name: str
    config: AzureEmbedClientConfig


# --- OpenAI 埋め込みクライアント ---


class OpenAIEmbedClientConfig(BaseModel, frozen=True):
    """OpenAI 埋め込みクライアントの接続設定."""

    model: str
    api_key_env: str


class OpenAIEmbedClient(BaseModel, frozen=True):
    """OpenAI 埋め込みクライアントの定義."""

    name: str
    config: OpenAIEmbedClientConfig


# --- 埋め込みクライアントコレクション ---


class EmbedClients(BaseModel, frozen=True):
    """埋め込みクライアントのプロバイダー別コレクション."""

    bedrock: list[BedrockEmbedClient] = Field(default_factory=list)
    azure: list[AzureEmbedClient] = Field(default_factory=list)
    openai: list[OpenAIEmbedClient] = Field(default_factory=list)



# --- LLM 全体設定 ---


class LLMs(BaseModel, frozen=True):
    """LLM クライアント全体の設定."""

    chat_clients: ChatClients
    embed_clients: EmbedClients = Field(default_factory=EmbedClients)
