"""A2A プロトコル経由で Template サービスと通信し、ストリーミング表示するページ.

Template A2A サーバー固有の仕様:
    - TaskStatusUpdateEvent (working + message): 思考過程テキスト（累積値）
    - TaskStatusUpdateEvent (input_required): ユーザー確認待ち
    - TaskArtifactUpdateEvent: 最終回答テキスト
    - Message: 最終回答テキスト（非ストリーミング時）
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from collections.abc import Generator

from a2a.types import (
    Message,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatusUpdateEvent,
)

import streamlit as st

from a2a_app.client import AgentClient, text_from_artifact, text_from_message
from chat_utils import StreamingChatPage
from common.defs.types import ChunkType
from common.settings.app import settings

_SENTINEL = object()


async def _stream_template_chunks(
    client: AgentClient,
    text: str,
    *,
    context_id: str | None = None,
) -> None:
    """Template A2A サーバーの生イベントを表示用チャンクに変換して queue に詰める.

    working イベントの message に含まれる StreamEvent JSON をパースし、
    ノードごとの進捗を ``label : content`` 形式にフォーマットして
    累積的な THINKING チャンクとして yield する。

    Args:
        client: 接続済みの AgentClient.
        text: ユーザーの入力テキスト.
        context_id: 既存の会話を継続する場合のコンテキスト ID.

    Yields:
        (ChunkType, text) のタプル.
    """
    thinking_lines: list[str] = []
    current_label = ""

    async for event in client.stream_events(text, context_id=context_id):
        match event:
            case (_, TaskStatusUpdateEvent() as ev) if (
                ev.status.state == TaskState.input_required
            ):
                metadata = {}
                if ev.status.message:
                    msg_text = text_from_message(ev.status.message)
                    if msg_text:
                        try:
                            metadata = json.loads(msg_text)
                        except json.JSONDecodeError:
                            metadata = {"message": msg_text}
                metadata["context_id"] = ev.context_id
                yield ChunkType.INPUT_REQUIRED, json.dumps(metadata)

            case (_, TaskStatusUpdateEvent() as ev) if (
                ev.status.state == TaskState.working
            ):
                if not ev.status.message:
                    continue
                raw = text_from_message(ev.status.message)
                if not raw:
                    continue

                try:
                    se = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    se = None

                if not isinstance(se, dict):
                    continue

                se_type = se.get("type")

                if se_type == "input_required":
                    ir_metadata = se.get("metadata", {})
                    ir_metadata["context_id"] = ev.context_id
                    yield ChunkType.INPUT_REQUIRED, json.dumps(ir_metadata)

                elif se_type == "node_start":
                    current_label = se.get("label") or se.get("node", "")
                    thinking_lines.append(f"**{current_label}**")
                    yield ChunkType.THINKING, "\n\n".join(thinking_lines)

                elif se_type == "token":
                    content = se.get("content", "")
                    if content and thinking_lines:
                        thinking_lines[-1] = f"**{current_label}** : {content}"
                        yield ChunkType.THINKING, "\n\n".join(thinking_lines)

            case (_, TaskArtifactUpdateEvent() as ev):
                answer = text_from_artifact(ev.artifact)
                if answer:
                    yield ChunkType.ANSWER, answer

            case Message() as msg:
                answer = text_from_message(msg)
                if answer:
                    yield ChunkType.ANSWER, answer


def _do_stream_a2a(prompt: str) -> Generator[tuple[ChunkType, str], None, None]:
    """Template A2A サーバーの async ストリームを同期ジェネレータに変換する.

    セッションに context_id が保存されている場合は、
    同じ会話コンテキストを継続して resume リクエストを送信する。

    Args:
        prompt: ユーザーが入力したテキスト.

    Yields:
        (ChunkType, text) のタプル.
    """
    context_id = st.session_state.pop("a2a_context_id", None)
    q: queue.Queue = queue.Queue()

    async def _run() -> None:
        async with AgentClient(settings.sample_agent_a2a_url) as client:
            async for chunk in _stream_template_chunks(client, prompt, context_id=context_id):
                q.put(chunk)
        q.put(_SENTINEL)

    thread = threading.Thread(target=lambda: asyncio.run(_run()), daemon=True)
    thread.start()

    while True:
        item = q.get()
        if item is _SENTINEL:
            break
        yield item

    thread.join()


_stream_a2a = _do_stream_a2a


StreamingChatPage(
    title="A2A ストリーミング",
    session_key="a2a_messages",
    stream_fn=_stream_a2a,
).run()
