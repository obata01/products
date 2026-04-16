"""サーバー側レスポンスフォーマットの定義.

API サーバー (SSE) および A2A サーバーが返すレスポンスのスキーマを定義する。
サーバー側の仕様変更時はこのファイルを更新し、影響範囲を確認すること。

影響を受けるモジュール:
    - src/pages/api_stream.py: _parse_sse_events(), _events_to_chunks()
    - src/a2a_app/client.py: AgentClient.stream()
"""

from __future__ import annotations

from enum import StrEnum

from common.lib.bases import BaseModel


class SSEEventType(StrEnum):
    """API サーバーが送信する SSE イベントの種別.

    対応サーバー仕様:
        各イベントは ``data: {JSON}`` 形式の SSE 行として送信される。
    """

    NODE_START = "node_start"
    NODE_END = "node_end"
    TOKEN = "token"
    INPUT_REQUIRED = "input_required"
    DONE = "done"


class SSEEvent(BaseModel):
    """API サーバーが送信する SSE イベントのスキーマ.

    対応サーバー仕様:
        data: {"type": "node_start", "node": "SAMPLE"}
        data: {"type": "token", "content": "こんにちは"}
        data: {"type": "node_end", "node": "SAMPLE"}
        data: {"type": "input_required", "metadata": {"message": "...", "preview": "..."}}
        data: {"type": "done"}

    Attributes:
        type: イベント種別.
        node: ノード名. node_start / node_end 時に設定される.
        content: トークンテキスト. token 時に設定される.
        metadata: 付加情報. input_required 時に確認メッセージ等が含まれる.
    """

    type: SSEEventType
    node: str = ""
    content: str = ""
    metadata: dict | None = None
