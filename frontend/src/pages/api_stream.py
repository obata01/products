"""Template サービスへ直接 API リクエストを送り、SSE ストリーミングで結果を表示するページ."""

from __future__ import annotations

import json
from collections.abc import Generator

import httpx
import streamlit as st
from pydantic import ValidationError

from chat_utils import StreamingChatPage
from common.defs.server_contracts import SSEEvent, SSEEventType
from common.defs.types import ChunkType
from common.settings.app import settings

StreamChunks = Generator[tuple[ChunkType, str], None, None]


def _parse_sse_events(lines: Generator[str, None, None]) -> Generator[SSEEvent, None, None]:
    """SSE の生テキスト行ストリームから SSEEvent を抽出する.

    ``data: `` プレフィックスを持たない行、JSON パースに失敗した行、
    スキーマに合わない行は無視する。

    Args:
        lines: SSE の生テキスト行を yield するジェネレータ.

    Yields:
        パース・バリデーション済みの SSEEvent.
    """
    for line in lines:
        if not line.startswith("data: "):
            continue
        try:
            raw = json.loads(line[len("data: "):])
        except json.JSONDecodeError:
            continue
        try:
            yield SSEEvent.model_validate(raw)
        except ValidationError:
            continue


def _events_to_chunks(
    events: Generator[SSEEvent, None, None],
) -> Generator[tuple[ChunkType, str], None, None]:
    """SSE イベント列を表示用の (ChunkType, text) に変換する.

    thinking はノード名 + トークンを累積した全文を毎回 yield する。
    answer はノードが切り替わるたびにリセットされる。

    Args:
        events: _parse_sse_events() が返す SSEEvent のジェネレータ.

    Yields:
        (ChunkType.THINKING, text), (ChunkType.ANSWER_START, ""),
        (ChunkType.ANSWER, text) のいずれか.
    """
    thinking_buf: list[str] = []
    pending_reset = False

    for event in events:
        if event.type == SSEEventType.NODE_START:
            thinking_buf.append(f"\n\n▶ {event.node} : ")
            yield ChunkType.THINKING, "".join(thinking_buf)
            pending_reset = True

        elif event.type == SSEEventType.TOKEN:
            if not event.content:
                continue
            thinking_buf.append(event.content)
            yield ChunkType.THINKING, "".join(thinking_buf)
            if pending_reset:
                yield ChunkType.ANSWER_START, ""
                pending_reset = False
            yield ChunkType.ANSWER, event.content

        elif event.type == SSEEventType.INPUT_REQUIRED:
            yield ChunkType.INPUT_REQUIRED, json.dumps(event.metadata or {})


def _do_stream_sse(prompt: str) -> StreamChunks:
    """Template サービスへ 1 回の SSE リクエストを送り、表示用チャンクを yield する.

    Args:
        prompt: ユーザーが入力したテキスト.

    Yields:
        (ChunkType, text) のタプル.

    Raises:
        httpx.HTTPStatusError: サーバーがエラーレスポンスを返した場合.
        httpx.ConnectError: サーバーに接続できなかった場合.
    """
    session_id = st.session_state.get("api_session_id", "streamlit-api")
    payload = {"session_id": session_id, "message": prompt, "stream": True}

    with httpx.Client(timeout=120) as client:
        with client.stream(
            "POST",
            settings.sample_agent_api_url,
            json=payload,
            headers={"Content-Type": "application/json"},
        ) as response:
            response.raise_for_status()
            events = _parse_sse_events(response.iter_lines())
            yield from _events_to_chunks(events)


_stream_sse = _do_stream_sse


StreamingChatPage(
    title="API ストリーミング",
    session_key="api_messages",
    stream_fn=_stream_sse,
).run()
