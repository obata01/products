"""A2A プロトコル経由で Template サービスと通信し、ストリーミング表示するページ.

Template A2A サーバー固有の仕様:
    - TaskStatusUpdateEvent (working + message): 思考過程テキスト（累積値）
    - TaskArtifactUpdateEvent: 最終回答テキスト
    - Message: 最終回答テキスト（非ストリーミング時）
"""

from __future__ import annotations

import asyncio
import queue
import threading
from collections.abc import Generator

from a2a.types import (
    Message,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatusUpdateEvent,
)

from a2a_app.client import AgentClient, text_from_artifact, text_from_message
from chat_utils import StreamingChatPage
from common.defs.types import ChunkType

A2A_BASE_URL = "http://host.docker.internal:8101/a2a"

_SENTINEL = object()


async def _stream_template_chunks(
    client: AgentClient, text: str,
) -> None:
    """Template A2A サーバーの生イベントを表示用チャンクに変換して queue に詰める.

    Args:
        client: 接続済みの AgentClient.
        text: ユーザーの入力テキスト.

    Yields:
        (ChunkType.THINKING, text) または (ChunkType.ANSWER, text) のタプル.
    """
    async for event in client.stream_events(text):
        match event:
            case (_, TaskStatusUpdateEvent() as ev) if (
                ev.status.state == TaskState.working and ev.status.message
            ):
                thinking = text_from_message(ev.status.message)
                if thinking:
                    yield ChunkType.THINKING, thinking

            case (_, TaskArtifactUpdateEvent() as ev):
                answer = text_from_artifact(ev.artifact)
                if answer:
                    yield ChunkType.ANSWER, answer

            case Message() as msg:
                answer = text_from_message(msg)
                if answer:
                    yield ChunkType.ANSWER, answer


def _stream_a2a(prompt: str) -> Generator[tuple[ChunkType, str], None, None]:
    """Template A2A サーバーの async ストリームを同期ジェネレータに変換する.

    Args:
        prompt: ユーザーが入力したテキスト.

    Yields:
        (ChunkType, text) のタプル.
    """
    q: queue.Queue = queue.Queue()

    async def _run() -> None:
        async with AgentClient(A2A_BASE_URL) as client:
            async for chunk in _stream_template_chunks(client, prompt):
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


StreamingChatPage(
    title="A2A ストリーミング",
    session_key="a2a_messages",
    stream_fn=_stream_a2a,
).run()
