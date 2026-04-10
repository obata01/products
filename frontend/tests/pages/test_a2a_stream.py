"""a2a_stream ページの Template サーバー固有変換ロジックのテスト."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from a2a.types import (
    Artifact,
    Message,
    Part,
    Role,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)
from a2a.utils import new_agent_text_message

from src.a2a_app.client import AgentClient
from src.common.defs.types import ChunkType
from src.pages.a2a_stream import _stream_template_chunks


def _make_part(text: str) -> Part:
    return Part(root=TextPart(text=text))


def _make_artifact(text: str) -> Artifact:
    return Artifact(artifact_id="art1", parts=[_make_part(text)])


def _make_thinking_event(text: str) -> tuple:
    return (
        MagicMock(),
        TaskStatusUpdateEvent(
            status=TaskStatus(state=TaskState.working, message=new_agent_text_message(text)),
            final=False,
            task_id="t1",
            context_id="c1",
        ),
    )


def _make_artifact_event(text: str) -> tuple:
    return (
        MagicMock(),
        TaskArtifactUpdateEvent(
            artifact=_make_artifact(text),
            task_id="t1",
            context_id="c1",
        ),
    )


def _make_client_with_mock(events: list) -> AgentClient:
    """モックイベントを返す AgentClient を作成する."""
    async def fake_send_message(*args, **kwargs):
        for e in events:
            yield e

    mock_inner = MagicMock()
    mock_inner.send_message = fake_send_message

    client = AgentClient("http://example.com/a2a")
    client._resolve_client = AsyncMock(return_value=mock_inner)
    return client


@pytest.mark.asyncio
async def test_thinking_event_yields_thinking_chunk():
    """TaskStatusUpdateEvent (working) が THINKING チャンクに変換されることを確認."""
    client = _make_client_with_mock([_make_thinking_event("considering...")])

    chunks = [c async for c in _stream_template_chunks(client, "hello")]

    assert chunks == [(ChunkType.THINKING, "considering...")]


@pytest.mark.asyncio
async def test_artifact_event_yields_answer_chunk():
    """TaskArtifactUpdateEvent が ANSWER チャンクに変換されることを確認."""
    client = _make_client_with_mock([_make_artifact_event("final answer")])

    chunks = [c async for c in _stream_template_chunks(client, "hello")]

    assert chunks == [(ChunkType.ANSWER, "final answer")]


@pytest.mark.asyncio
async def test_message_event_yields_answer_chunk():
    """Message が ANSWER チャンクに変換されることを確認."""
    message = Message(role=Role.agent, parts=[_make_part("direct reply")], message_id="m1")
    client = _make_client_with_mock([message])

    chunks = [c async for c in _stream_template_chunks(client, "hello")]

    assert chunks == [(ChunkType.ANSWER, "direct reply")]


@pytest.mark.asyncio
async def test_full_flow_thinking_then_answer():
    """thinking → answer の完全なフローを確認."""
    client = _make_client_with_mock([
        _make_thinking_event("thinking..."),
        _make_artifact_event("the answer"),
    ])

    chunks = [c async for c in _stream_template_chunks(client, "hello")]

    assert chunks == [
        (ChunkType.THINKING, "thinking..."),
        (ChunkType.ANSWER, "the answer"),
    ]


@pytest.mark.asyncio
async def test_empty_text_events_are_skipped():
    """テキストが空のイベントはスキップされることを確認."""
    client = _make_client_with_mock([
        _make_thinking_event(""),
        _make_artifact_event(""),
    ])

    chunks = [c async for c in _stream_template_chunks(client, "hello")]

    assert chunks == []
