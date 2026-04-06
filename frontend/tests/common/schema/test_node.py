import pytest

from src.common.schema.node import ChatPromptConfig, NodeChatClientRef, NodeConfig
from src.components.llms.models import LLMParams


def _make_node_config(provider: str, max_tokens: int | None = None, max_completion_tokens: int | None = None) -> NodeConfig:
    return NodeConfig(
        name="sample",
        chat_client=NodeChatClientRef(provider=provider, client_name="client"),
        chat_params=LLMParams(max_tokens=max_tokens, max_completion_tokens=max_completion_tokens),
        chat_prompt=ChatPromptConfig(template_file="nodes/sample.lc.tpl"),
    )


@pytest.mark.parametrize(
    "provider, max_tokens, max_completion_tokens, expected_max_tokens, expected_max_completion_tokens",
    [
        ("azure", 1000, None, None, 1000),   # Azure + max_tokens → max_completion_tokens へ変換
        ("bedrock", 1000, None, 1000, None), # Azure 以外 → 変換なし
        ("azure", None, None, None, None),   # Azure だが max_tokens 未設定 → 変換なし
        ("azure", 500, 200, 500, 200),       # Azure だが max_completion_tokens 設定済み → 変換なし
    ],
)
def test_node_config_azure_param_conversion(
    provider,
    max_tokens,
    max_completion_tokens,
    expected_max_tokens,
    expected_max_completion_tokens,
):
    """NodeConfig がプロバイダーに応じて max_tokens を変換することを確認."""
    config = _make_node_config(provider, max_tokens, max_completion_tokens)

    assert config.chat_params.max_tokens == expected_max_tokens
    assert config.chat_params.max_completion_tokens == expected_max_completion_tokens
