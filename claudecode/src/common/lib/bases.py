from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict


class BaseModel(PydanticBaseModel):
    """ベースモデル."""

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
    )
