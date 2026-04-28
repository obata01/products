from dependency_injector import containers, providers
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from src.common.defs.types import ClientName, NodeName
from src.common.di.builders import (
    build_chat_client_registry,
    build_embed_client_registry,
    build_node_config_registry,
)
from src.common.schema.app_config import AppConfig
from src.common.schema.node import NodeConfig
from src.common.settings.app import settings
from src.components.io.app_config import load_yaml


def _load_app_config() -> AppConfig:
    """YAML を読み込んでスキーマで検証し AppConfig を返す."""
    return AppConfig.model_validate(load_yaml(settings.config_yaml_path))


class Container(containers.DeclarativeContainer):
    """アプリケーションの依存性注入コンテナ.

    Note:
        - app_config: YAML から構築した設定 (Singleton).
        - chat_clients: クライアント名をキーとするチャットクライアント辞書 (Singleton).
        - embed_clients: クライアント名をキーとする埋め込みクライアント辞書 (Singleton).
        - node_configs: ノード名をキーとするノード設定辞書 (Singleton).
    """

    app_config: providers.Singleton[AppConfig] = providers.Singleton(_load_app_config)

    chat_clients: providers.Singleton[dict[ClientName, BaseChatModel]] = providers.Singleton(
        build_chat_client_registry,
        config=app_config,
    )

    embed_clients: providers.Singleton[dict[ClientName, Embeddings]] = providers.Singleton(
        build_embed_client_registry,
        config=app_config,
    )

    node_configs: providers.Singleton[dict[NodeName, NodeConfig]] = providers.Singleton(
        build_node_config_registry,
        config=app_config,
    )
