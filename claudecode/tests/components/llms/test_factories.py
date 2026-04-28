from unittest.mock import MagicMock, patch

import pytest

from src.components.llms.factories import LLMChatClientFactory, LLMEmbedClientFactory
from src.components.llms.models import (
    AzureChatConfig,
    AzureEmbedConfig,
    BedrockChatConfig,
    BedrockEmbedConfig,
    LLMParams,
    OpenAIChatConfig,
    OpenAiEmbedConfig,
)


# --- LLMChatClientFactory ---


@pytest.mark.parametrize(
    "config, patch_target",
    [
        (
            AzureChatConfig(
                model="gpt-4",
                azure_endpoint="https://example.openai.azure.com/",
                azure_deployment="gpt-4-deploy",
                openai_api_version="2024-01-01",
                api_key="dummy-key",
            ),
            "src.components.llms.factories.AzureChatOpenAI",
        ),
        (
            BedrockChatConfig(
                model_id="anthropic.claude-3",
                region_name="us-east-1",
            ),
            "src.components.llms.factories.ChatBedrockConverse",
        ),
        (
            OpenAIChatConfig(
                model="gpt-4o",
                api_key="sk-dummy",
            ),
            "src.components.llms.factories.ChatOpenAI",
        ),
    ],
)
def test_chat_factory_dispatches_by_config_type(config, patch_target):
    """config の型に応じた LangChain クライアントが呼び出されることを確認."""
    with patch(patch_target) as mock_cls:
        mock_cls.return_value = MagicMock()
        LLMChatClientFactory.create(config=config, params=LLMParams())
        mock_cls.assert_called_once()


def test_chat_factory_passes_params_to_client():
    """LLMParams のフィールドがクライアントコンストラクタに渡されることを確認."""
    config = OpenAIChatConfig(
        model="gpt-4o",
        api_key="sk-dummy",
    )
    params = LLMParams(temperature=0.5, max_tokens=1000)

    with patch("src.components.llms.factories.ChatOpenAI") as mock_cls:
        mock_cls.return_value = MagicMock()
        LLMChatClientFactory.create(config=config, params=params)

        _, kwargs = mock_cls.call_args
        assert kwargs["temperature"] == 0.5
        assert kwargs["max_tokens"] == 1000


# --- LLMEmbedClientFactory ---


@pytest.mark.parametrize(
    "config, patch_target",
    [
        (
            AzureEmbedConfig(
                model="text-embedding-3-small",
                azure_endpoint="https://example.openai.azure.com/",
                azure_deployment="embed-deploy",
                openai_api_version="2024-01-01",
                api_key="dummy-key",
            ),
            "src.components.llms.factories.AzureOpenAIEmbeddings",
        ),
        (
            BedrockEmbedConfig(
                model_id="amazon.titan-embed-v1",
                region_name="us-east-1",
            ),
            "src.components.llms.factories.BedrockEmbeddings",
        ),
        (
            OpenAiEmbedConfig(
                model="text-embedding-3-small",
                api_key="sk-dummy",
            ),
            "src.components.llms.factories.OpenAIEmbeddings",
        ),
    ],
)
def test_embed_factory_dispatches_by_config_type(config, patch_target):
    """config の型に応じた LangChain 埋め込みクライアントが呼び出されることを確認."""
    with patch(patch_target) as mock_cls:
        mock_cls.return_value = MagicMock()
        LLMEmbedClientFactory.create(config=config)
        mock_cls.assert_called_once()
