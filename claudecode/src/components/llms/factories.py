from langchain_aws import BedrockEmbeddings, ChatBedrockConverse
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings, ChatOpenAI, OpenAIEmbeddings

from src.components.llms.models import (
    AzureChatConfig,
    AzureEmbedConfig,
    BedrockChatConfig,
    BedrockEmbedConfig,
    LLMParams,
    OpenAIChatConfig,
    OpenAiEmbedConfig,
)


def _create_responses_client(
    model: str,
    params: LLMParams,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
) -> ChatOpenAI:
    """Responses API 用の ChatOpenAI クライアントを生成する.

    Args:
        model: モデル名またはデプロイメント名.
        params: LLM パラメータ.
        base_url: Azure 用のベース URL. OpenAI の場合は None.
        api_key: API キー.

    Returns:
        Responses API モードの ChatOpenAI インスタンス.
    """
    base_params, model_kwargs, direct_fields = params.for_responses()
    kwargs: dict = {
        "model": model,
        "use_responses_api": True,
        "model_kwargs": model_kwargs,
        **direct_fields,
        **base_params,
    }
    if base_url is not None:
        kwargs["base_url"] = base_url
    if api_key is not None:
        kwargs["api_key"] = api_key
    return ChatOpenAI(**kwargs)


class LLMChatClientFactory:
    """LLM Chat モデルのファクトリクラス."""

    @staticmethod
    def create(
        config: AzureChatConfig | BedrockChatConfig | OpenAIChatConfig,
        params: LLMParams,
    ) -> BaseChatModel:
        """Config の型に応じた LLM Chat クライアントを生成する.

        Args:
            config: プロバイダー固有の API 設定情報.
            params: LLM 実行時の各種パラメータ.

        Returns:
            LLM クライアントのインスタンス.

        Raises:
            ValueError: 未対応の config 型が渡された場合.
        """
        if isinstance(config, AzureChatConfig) and config.use_responses_api:
            base_url = f"{config.azure_endpoint.rstrip('/')}/openai/v1/"
            return _create_responses_client(
                model=config.azure_deployment,
                params=params,
                base_url=base_url,
                api_key=config.api_key,
            )

        if isinstance(config, OpenAIChatConfig) and config.use_responses_api:
            return _create_responses_client(
                model=config.model,
                params=params,
                api_key=config.api_key,
            )

        config_ = config.model_dump(exclude_none=True, exclude={"use_responses_api"})
        params_ = params.for_completions()

        if isinstance(config, AzureChatConfig):
            return AzureChatOpenAI(**config_, **params_)

        if isinstance(config, BedrockChatConfig):
            return ChatBedrockConverse(**config_, **params_)

        if isinstance(config, OpenAIChatConfig):
            return ChatOpenAI(**config_, **params_)

        raise ValueError("Unsupported Config Type.")


class LLMEmbedClientFactory:
    """LLM Embedding モデルのファクトリクラス."""

    @staticmethod
    def create(
        config: AzureEmbedConfig | BedrockEmbedConfig | OpenAiEmbedConfig,
    ) -> Embeddings:
        """Config の型に応じた Embedding クライアントを生成する.

        Args:
            config: プロバイダー固有の API 設定情報.

        Returns:
            Embedding クライアントのインスタンス.

        Raises:
            ValueError: 未対応の config 型が渡された場合.
        """
        config_ = config.model_dump(exclude_none=True)

        if isinstance(config, AzureEmbedConfig):
            return AzureOpenAIEmbeddings(**config_)

        if isinstance(config, BedrockEmbedConfig):
            return BedrockEmbeddings(**config_)

        if isinstance(config, OpenAiEmbedConfig):
            return OpenAIEmbeddings(**config_)

        raise ValueError("Unsupported Config Type.")
