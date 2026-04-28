import pytest
from pydantic import BaseModel

from src.common.schema._helpers import to_azure_params
from src.components.llms.models import LLMParams


class _DummyModel(BaseModel, frozen=True):
    """to_azure_params のテスト用スタブモデル."""

    params: LLMParams


@pytest.mark.parametrize(
    "max_tokens, max_completion_tokens, expect_converted",
    [
        (1000, None, True),   # max_tokens のみ設定 → max_completion_tokens へ変換
        (None, None, False),  # max_tokens 未設定 → 変換なし
        (1000, 500, False),   # 両方設定済み → 変換なし
    ],
)
def test_to_azure_params(max_tokens, max_completion_tokens, expect_converted):
    """to_azure_params が条件に応じて max_tokens を変換することを確認."""
    model = _DummyModel(params=LLMParams(max_tokens=max_tokens, max_completion_tokens=max_completion_tokens))

    result = to_azure_params(model, "params")

    if expect_converted:
        assert result.params.max_tokens is None
        assert result.params.max_completion_tokens == max_tokens
    else:
        assert result == model
