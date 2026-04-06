from enum import StrEnum
from typing import NewType

ClientName = NewType("ClientName", str)


class NodeName(StrEnum):
    """ノード名一覧."""

    START_GATE = "START_GATE"
    SAMPLE = "SAMPLE"
    END_GATE = "END_GATE"
