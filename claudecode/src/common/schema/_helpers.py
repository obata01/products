from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.components.llms.models import LLMParams


def to_azure_params[T](model: T, field: str) -> T:
    """指定フィールドの max_tokens を max_completion_tokens に変換する."""
    params: LLMParams = getattr(model, field)
    if params.max_tokens is not None and params.max_completion_tokens is None:
        converted = params.model_copy(update={"max_completion_tokens": params.max_tokens, "max_tokens": None})
        return model.model_copy(update={field: converted})  # type: ignore[return-value]
    return model
