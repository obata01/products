from enum import StrEnum
from typing import NewType

ClientName = NewType("ClientName", str)


class NodeName(StrEnum):
    """ノード名一覧."""

    CLAUDE_CODE = "CLAUDE_CODE"


# ノードごとのクライアント向け表示ラベル.
# クライアントはこのラベルを使って思考過程の表示をカスタマイズできる。
# ノード追加時はここにもラベルを追加すること。
NODE_LABELS: dict[str, str] = {
    NodeName.CLAUDE_CODE: "Claude Code 処理中",
}
