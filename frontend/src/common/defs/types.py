from enum import StrEnum
from typing import NewType

ClientName = NewType("ClientName", str)


class ChunkType(StrEnum):
    """ストリーミングチャンクの種別.

    クライアント内部で統一的に使用する表示用チャンクの種別。
    サーバーの通信プロトコル（SSE / A2A）に依存しない。
    """

    THINKING = "thinking"
    ANSWER = "answer"
    ANSWER_START = "answer_start"
    INPUT_REQUIRED = "input_required"
