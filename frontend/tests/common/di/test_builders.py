from unittest.mock import MagicMock, patch

import pytest

from src.common.di.builders import (
    build_chat_client_registry,
    build_embed_client_registry,
    build_node_config_registry,
)
from src.common.defs.types import NodeName
from src.common.schema.app_config import AppConfig
from src.common.schema.checkpoint import CheckpointConfig
from src.common.schema.llm import (
    AzureChatClient,
    AzureChatClientConfig,
    AzureEmbedClient,
    AzureEmbedClientConfig,
    BedrockChatClient,
    BedrockChatClientConfig,
    BedrockEmbedClient,
    BedrockEmbedClientConfig,
    ChatClients,
    EmbedClients,
    LLMs,
    OpenAIChatClient,
    OpenAIChatClientConfig,
    OpenAIEmbedClient,
    OpenAIEmbedClientConfig,
)
from src.common.schema.node import ChatPromptConfig, NodeChatClientRef, NodeConfig
from src.components.llms.models import LLMParams


@pytest.fixture
def empty_config() -> AppConfig:
    return AppConfig(
        llms=LLMs(
            chat_clients=ChatClients(),
            embed_clients=EmbedClients(),
        ),
        nodes=[],
        checkpoint=CheckpointConfig(
            kind="memory",
            dsn="",
        ),
    )


@pytest.fixture
def bedrock_chat_client() -> BedrockChatClient:
    return BedrockChatClient(
        name="bedrock-chat",
        config=BedrockChatClientConfig(
            model_id="anthropic.claude-3",
            region_name="us-east-1",
        ),
        default_params=LLMParams(),
    )


@pytest.fixture
def azure_chat_client() -> AzureChatClient:
    return AzureChatClient(
        name="azure-chat",
        config=AzureChatClientConfig(
            model="gpt-4",
            azure_deployment="gpt-4-deploy",
            azure_endpoint_env="TEST_AZURE_ENDPOINT",
            api_key_env="TEST_AZURE_API_KEY",
            openai_api_version="2024-01-01",
        ),
        default_params=LLMParams(),
    )


@pytest.fixture
def openai_chat_client() -> OpenAIChatClient:
    return OpenAIChatClient(
        name="openai-chat",
        config=OpenAIChatClientConfig(
            model="gpt-4o",
            api_key_env="TEST_OPENAI_API_KEY",
        ),
        default_params=LLMParams(),
    )


@pytest.fixture
def bedrock_embed_client() -> BedrockEmbedClient:
    return BedrockEmbedClient(
        name="bedrock-embed",
        config=BedrockEmbedClientConfig(
            model_id="amazon.titan-embed-v1",
            region_name="us-east-1",
        ),
    )


@pytest.fixture
def azure_embed_client() -> AzureEmbedClient:
    return AzureEmbedClient(
        name="azure-embed",
        config=AzureEmbedClientConfig(
            model="text-embedding-3-small",
            azure_deployment="embed-deploy",
            azure_endpoint_env="TEST_AZURE_ENDPOINT",
            api_key_env="TEST_AZURE_API_KEY",
            openai_api_version="2024-01-01",
        ),
    )


@pytest.fixture
def openai_embed_client() -> OpenAIEmbedClient:
    return OpenAIEmbedClient(
        name="openai-embed",
        config=OpenAIEmbedClientConfig(
            model="text-embedding-3-small",
            api_key_env="TEST_OPENAI_API_KEY",
        ),
    )


@pytest.fixture
def sample_node() -> NodeConfig:
    return NodeConfig(
        name="sample",
        chat_client=NodeChatClientRef(
            provider="bedrock",
            client_name="bedrock-chat",
        ),
        chat_params=LLMParams(),
        chat_prompt=ChatPromptConfig(
            template_file="nodes/sample.lc.tpl",
        ),
    )


def test_build_node_config_registry_uppercases_name(sample_node):
    """ノード名が大文字の NodeName キーでレジストリに登録されることを確認."""
    config = AppConfig(
        llms=LLMs(
            chat_clients=ChatClients(),
            embed_clients=EmbedClients(),
        ),
        nodes=[sample_node],
        checkpoint=CheckpointConfig(
            kind="memory",
            dsn="",
        ),
    )

    registry = build_node_config_registry(config)

    assert NodeName.SAMPLE in registry
    assert registry[NodeName.SAMPLE] is sample_node


def test_build_node_config_registry_empty(empty_config):
    """ノードが存在しない場合は空の辞書を返すことを確認."""
    registry = build_node_config_registry(empty_config)

    assert registry == {}


@patch("src.common.di.builders.LLMChatClientFactory.create")
def test_build_chat_client_registry_bedrock_always_registered(mock_create, bedrock_chat_client):
    """Bedrock クライアントは環境変数なしで登録されることを確認."""
    mock_create.return_value = MagicMock()
    config = AppConfig(
        llms=LLMs(
            chat_clients=ChatClients(bedrock=[bedrock_chat_client]),
            embed_clients=EmbedClients(),
        ),
        nodes=[],
        checkpoint=CheckpointConfig(
            kind="memory",
            dsn="",
        ),
    )

    registry = build_chat_client_registry(config)

    assert "bedrock-chat" in registry
    mock_create.assert_called_once()


@patch("src.common.di.builders.LLMChatClientFactory.create")
def test_build_chat_client_registry_azure_skipped_without_env(mock_create, azure_chat_client, monkeypatch):
    """Azure クライアントは環境変数が未設定の場合スキップされることを確認."""
    monkeypatch.delenv("TEST_AZURE_ENDPOINT", raising=False)
    monkeypatch.delenv("TEST_AZURE_API_KEY", raising=False)
    config = AppConfig(
        llms=LLMs(
            chat_clients=ChatClients(azure=[azure_chat_client]),
            embed_clients=EmbedClients(),
        ),
        nodes=[],
        checkpoint=CheckpointConfig(
            kind="memory",
            dsn="",
        ),
    )

    registry = build_chat_client_registry(config)

    assert "azure-chat" not in registry
    mock_create.assert_not_called()


@patch("src.common.di.builders.LLMChatClientFactory.create")
def test_build_chat_client_registry_azure_registered_with_env(mock_create, azure_chat_client, monkeypatch):
    """Azure クライアントは環境変数が揃っている場合に登録されることを確認."""
    monkeypatch.setenv("TEST_AZURE_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("TEST_AZURE_API_KEY", "dummy-key")
    mock_create.return_value = MagicMock()
    config = AppConfig(
        llms=LLMs(
            chat_clients=ChatClients(azure=[azure_chat_client]),
            embed_clients=EmbedClients(),
        ),
        nodes=[],
        checkpoint=CheckpointConfig(
            kind="memory",
            dsn="",
        ),
    )

    registry = build_chat_client_registry(config)

    assert "azure-chat" in registry


@patch("src.common.di.builders.LLMChatClientFactory.create")
def test_build_chat_client_registry_openai_skipped_without_env(mock_create, openai_chat_client, monkeypatch):
    """OpenAI クライアントは API キー環境変数が未設定の場合スキップされることを確認."""
    monkeypatch.delenv("TEST_OPENAI_API_KEY", raising=False)
    config = AppConfig(
        llms=LLMs(
            chat_clients=ChatClients(openai=[openai_chat_client]),
            embed_clients=EmbedClients(),
        ),
        nodes=[],
        checkpoint=CheckpointConfig(
            kind="memory",
            dsn="",
        ),
    )

    registry = build_chat_client_registry(config)

    assert "openai-chat" not in registry
    mock_create.assert_not_called()


@patch("src.common.di.builders.LLMChatClientFactory.create")
def test_build_chat_client_registry_openai_registered_with_env(mock_create, openai_chat_client, monkeypatch):
    """OpenAI クライアントは API キー環境変数が設定されている場合に登録されることを確認."""
    monkeypatch.setenv("TEST_OPENAI_API_KEY", "sk-dummy")
    mock_create.return_value = MagicMock()
    config = AppConfig(
        llms=LLMs(
            chat_clients=ChatClients(openai=[openai_chat_client]),
            embed_clients=EmbedClients(),
        ),
        nodes=[],
        checkpoint=CheckpointConfig(
            kind="memory",
            dsn="",
        ),
    )

    registry = build_chat_client_registry(config)

    assert "openai-chat" in registry


@patch("src.common.di.builders.LLMEmbedClientFactory.create")
def test_build_embed_client_registry_bedrock_always_registered(mock_create, bedrock_embed_client):
    """Bedrock 埋め込みクライアントは環境変数なしで登録されることを確認."""
    mock_create.return_value = MagicMock()
    config = AppConfig(
        llms=LLMs(
            chat_clients=ChatClients(),
            embed_clients=EmbedClients(bedrock=[bedrock_embed_client]),
        ),
        nodes=[],
        checkpoint=CheckpointConfig(
            kind="memory",
            dsn="",
        ),
    )

    registry = build_embed_client_registry(config)

    assert "bedrock-embed" in registry


@patch("src.common.di.builders.LLMEmbedClientFactory.create")
def test_build_embed_client_registry_azure_skipped_without_env(mock_create, azure_embed_client, monkeypatch):
    """Azure 埋め込みクライアントは環境変数が未設定の場合スキップされることを確認."""
    monkeypatch.delenv("TEST_AZURE_ENDPOINT", raising=False)
    monkeypatch.delenv("TEST_AZURE_API_KEY", raising=False)
    config = AppConfig(
        llms=LLMs(
            chat_clients=ChatClients(),
            embed_clients=EmbedClients(azure=[azure_embed_client]),
        ),
        nodes=[],
        checkpoint=CheckpointConfig(
            kind="memory",
            dsn="",
        ),
    )

    registry = build_embed_client_registry(config)

    assert "azure-embed" not in registry
    mock_create.assert_not_called()


@patch("src.common.di.builders.LLMEmbedClientFactory.create")
def test_build_embed_client_registry_openai_skipped_without_env(mock_create, openai_embed_client, monkeypatch):
    """OpenAI 埋め込みクライアントは API キー環境変数が未設定の場合スキップされることを確認."""
    monkeypatch.delenv("TEST_OPENAI_API_KEY", raising=False)
    config = AppConfig(
        llms=LLMs(
            chat_clients=ChatClients(),
            embed_clients=EmbedClients(openai=[openai_embed_client]),
        ),
        nodes=[],
        checkpoint=CheckpointConfig(
            kind="memory",
            dsn="",
        ),
    )

    registry = build_embed_client_registry(config)

    assert "openai-embed" not in registry
    mock_create.assert_not_called()
