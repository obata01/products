from enum import StrEnum
from typing import TypeVar

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel

ChatClientBase = TypeVar("ChatClientBase", bound=BaseChatModel)
EmbedClientBase = TypeVar("EmbedClientBase", bound=Embeddings)


class ProviderType(StrEnum):
    """LLMのプロバイダーの定義名称."""

    AZURE = "azure"
    BEDROCK = "bedrock"


#############################################################
# 生成AI LLMクライアントの設定情報.
#############################################################


class AzureChatConfig(BaseModel, frozen=True):
    """Azure OpenAI設定情報."""

    model: str
    azure_endpoint: str
    azure_deployment: str
    openai_api_version: str
    api_key: str
    use_responses_api: bool = False


class BedrockChatConfig(BaseModel, frozen=True):
    """AWS Bedrock Converse API 設定情報."""

    model_id: str
    region_name: str


class OpenAIChatConfig(BaseModel, frozen=True):
    """OpenAI 設定情報."""

    model: str
    api_key: str
    use_responses_api: bool = False


#############################################################
# 生成AI LLMパラメータ.
#############################################################


class LLMParams(BaseModel, frozen=True):
    """LLMパラメータ一覧.

    Attributes:
        temperature: サンプリング温度.
        max_tokens: Chat Completions API 用の最大トークン数.
        top_p: Top-p サンプリング.
        max_completion_tokens: Chat Completions API 用の最大出力トークン数.
        max_output_tokens: Responses API 用の最大出力トークン数.
        reasoning: Responses API 用の推論設定.
    """

    _RESPONSES_MODEL_KWARGS: frozenset[str] = frozenset({"max_output_tokens"})
    _RESPONSES_DIRECT_FIELDS: frozenset[str] = frozenset({"reasoning"})
    _COMPLETIONS_ONLY_FIELDS: frozenset[str] = frozenset({"max_tokens", "max_completion_tokens"})

    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    max_completion_tokens: int | None = None
    max_output_tokens: int | None = None
    reasoning: dict[str, str] | None = None

    def for_completions(self) -> dict:
        """Chat Completions API 用のパラメータ辞書を返す.

        Returns:
            Responses API 専用フィールドを除外した辞書.
        """
        exclude = self._RESPONSES_MODEL_KWARGS | self._RESPONSES_DIRECT_FIELDS
        return self.model_dump(exclude_none=True, exclude=exclude)

    def for_responses(self) -> tuple[dict, dict, dict]:
        """Responses API 用のパラメータを 3 分割して返す.

        Returns:
            (base_params, model_kwargs, direct_fields) のタプル.
            base_params: temperature, top_p など共通パラメータ.
            model_kwargs: model_kwargs 経由で渡すパラメータ (max_output_tokens).
            direct_fields: ChatOpenAI に直接渡すパラメータ (reasoning).
        """
        all_params = self.model_dump(exclude_none=True)
        responses_fields = self._RESPONSES_MODEL_KWARGS | self._RESPONSES_DIRECT_FIELDS
        exclude = self._COMPLETIONS_ONLY_FIELDS | responses_fields

        base_params = {k: v for k, v in all_params.items() if k not in exclude}
        model_kwargs = {k: v for k, v in all_params.items() if k in self._RESPONSES_MODEL_KWARGS}
        direct_fields = {k: v for k, v in all_params.items() if k in self._RESPONSES_DIRECT_FIELDS}
        return base_params, model_kwargs, direct_fields


#############################################################
# Embedding用 LLMクライアント設定情報.
#############################################################


class OpenAiEmbedConfig(BaseModel, frozen=True):
    """OpenAI Embeddingモデルの設定情報."""

    model: str
    api_key: str


class AzureEmbedConfig(BaseModel, frozen=True):
    """Azure OpenAI設定情報."""

    model: str
    azure_endpoint: str
    azure_deployment: str
    openai_api_version: str
    api_key: str


class BedrockEmbedConfig(BaseModel, frozen=True):
    """AWS Bedrockモデル設定情報."""

    model_id: str
    region_name: str
