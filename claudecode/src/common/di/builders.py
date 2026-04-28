"""DI 用のレジストリビルダー."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from src.common.defs.types import ClientName, NodeName
from src.common.lib import logging
from src.components.llms.factories import LLMChatClientFactory, LLMEmbedClientFactory
from src.components.llms.models import (
    AzureChatConfig,
    AzureEmbedConfig,
    BedrockChatConfig,
    BedrockEmbedConfig,
    OpenAIChatConfig,
    OpenAiEmbedConfig,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from langchain_core.embeddings import Embeddings
    from langchain_core.language_models import BaseChatModel

    from src.common.schema.app_config import AppConfig
    from src.common.schema.llm import (
        AzureChatClient,
        AzureEmbedClient,
        BedrockChatClient,
        BedrockEmbedClient,
        OpenAIChatClient,
        OpenAIEmbedClient,
    )
    from src.common.schema.node import NodeConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 汎用ヘルパー
# ---------------------------------------------------------------------------


def _build_registry[T](
    provider_entries: Iterable[tuple[Iterable, Callable[..., T | None]]],
) -> dict[ClientName, T]:
    """複数プロバイダーのクライアントリストを走査し、名前引き辞書を構築する.

    各 builder がクライアント定義を受け取りインスタンスを返す。
    None を返した場合 (環境変数不足など) はスキップする。

    Args:
        provider_entries: (クライアント定義リスト, ビルダー関数) のペア列.

    Returns:
        ClientName をキーとするインスタンスの辞書.
    """
    registry: dict[ClientName, T] = {}
    for clients, build in provider_entries:
        for client in clients:
            instance = build(client)
            if instance is not None:
                registry[ClientName(client.name)] = instance
    return registry


def _resolve_azure_env(client: object, client_type: str) -> tuple[str, str] | None:
    """Azure クライアントの環境変数を解決する.

    Args:
        client: azure_endpoint_env / api_key_env を持つクライアント定義.
        client_type: ログ用のクライアント種別名 ("chat" / "embed").

    Returns:
        (azure_endpoint, api_key) のタプル. 欠損時は None.
    """
    azure_endpoint = os.environ.get(client.config.azure_endpoint_env)
    api_key = os.environ.get(client.config.api_key_env)
    if azure_endpoint is None or api_key is None:
        logger.warning("Skipping Azure %s client '%s': missing env vars.", client_type, client.name)
        return None
    return azure_endpoint, api_key


def _resolve_openai_env(client: object, client_type: str) -> str | None:
    """OpenAI クライアントの環境変数を解決する.

    Args:
        client: api_key_env を持つクライアント定義.
        client_type: ログ用のクライアント種別名 ("chat" / "embed").

    Returns:
        api_key 文字列. 欠損時は None.
    """
    api_key = os.environ.get(client.config.api_key_env)
    if api_key is None:
        logger.warning("Skipping OpenAI %s client '%s': missing env vars.", client_type, client.name)
        return None
    return api_key


# ---------------------------------------------------------------------------
# Chat クライアントビルダー
# ---------------------------------------------------------------------------


def _build_bedrock_chat(client: BedrockChatClient) -> BaseChatModel:
    cfg = BedrockChatConfig(model_id=client.config.model_id, region_name=client.config.region_name)
    return LLMChatClientFactory.create(config=cfg, params=client.default_params)


def _build_azure_chat(client: AzureChatClient) -> BaseChatModel | None:
    env = _resolve_azure_env(client, "chat")
    if env is None:
        return None
    cfg = AzureChatConfig(
        model=client.config.model,
        azure_endpoint=env[0],
        azure_deployment=client.config.azure_deployment,
        openai_api_version=client.config.openai_api_version,
        api_key=env[1],
        use_responses_api=client.config.use_responses_api,
    )
    return LLMChatClientFactory.create(config=cfg, params=client.default_params)


def _build_openai_chat(client: OpenAIChatClient) -> BaseChatModel | None:
    api_key = _resolve_openai_env(client, "chat")
    if api_key is None:
        return None
    cfg = OpenAIChatConfig(
        model=client.config.model,
        api_key=api_key,
        use_responses_api=client.config.use_responses_api,
    )
    return LLMChatClientFactory.create(config=cfg, params=client.default_params)


# ---------------------------------------------------------------------------
# Embed クライアントビルダー
# ---------------------------------------------------------------------------


def _build_bedrock_embed(client: BedrockEmbedClient) -> Embeddings:
    cfg = BedrockEmbedConfig(model_id=client.config.model_id, region_name=client.config.region_name)
    return LLMEmbedClientFactory.create(config=cfg)


def _build_azure_embed(client: AzureEmbedClient) -> Embeddings | None:
    env = _resolve_azure_env(client, "embed")
    if env is None:
        return None
    cfg = AzureEmbedConfig(
        model=client.config.model,
        azure_endpoint=env[0],
        azure_deployment=client.config.azure_deployment,
        openai_api_version=client.config.openai_api_version,
        api_key=env[1],
    )
    return LLMEmbedClientFactory.create(config=cfg)


def _build_openai_embed(client: OpenAIEmbedClient) -> Embeddings | None:
    api_key = _resolve_openai_env(client, "embed")
    if api_key is None:
        return None
    cfg = OpenAiEmbedConfig(model=client.config.model, api_key=api_key)
    return LLMEmbedClientFactory.create(config=cfg)


# ---------------------------------------------------------------------------
# 公開 API
# ---------------------------------------------------------------------------


def build_chat_client_registry(config: AppConfig) -> dict[ClientName, BaseChatModel]:
    """チャットクライアントをプロバイダー横断で名前引きできる辞書として構築する.

    Args:
        config: バリデーション済みのアプリケーション設定.

    Returns:
        クライアント名をキーとするチャットクライアントの辞書.
    """
    cc = config.llms.chat_clients
    return _build_registry([
        (cc.bedrock, _build_bedrock_chat),
        (cc.azure, _build_azure_chat),
        (cc.openai, _build_openai_chat),
    ])


def build_embed_client_registry(config: AppConfig) -> dict[ClientName, Embeddings]:
    """埋め込みクライアントを名前引きできる辞書として構築する.

    Args:
        config: バリデーション済みのアプリケーション設定.

    Returns:
        クライアント名をキーとする埋め込みクライアントの辞書.
    """
    ec = config.llms.embed_clients
    return _build_registry([
        (ec.bedrock, _build_bedrock_embed),
        (ec.azure, _build_azure_embed),
        (ec.openai, _build_openai_embed),
    ])


def build_node_config_registry(config: AppConfig) -> dict[NodeName, NodeConfig]:
    """ノード設定をノード名で引ける辞書として構築する.

    Args:
        config: バリデーション済みのアプリケーション設定.

    Returns:
        ノード名をキーとするノード設定の辞書.
    """
    return {NodeName(node.name.upper()): node for node in config.nodes}
