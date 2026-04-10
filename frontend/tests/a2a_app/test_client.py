"""汎用 A2A クライアントのテスト."""

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

from src.a2a_app.client import (
    AgentClient,
    text_from_artifact,
    text_from_message,
    text_from_parts,
)


def _make_part(text: str) -> Part:
    return Part(root=TextPart(text=text))


def _make_artifact(text: str) -> Artifact:
    return Artifact(artifact_id="art1", parts=[_make_part(text)])


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


@pytest.mark.parametrize(
    "texts, expected",
    [
        ([], ""),
        (["hello"], "hello"),
        (["a", "b"], "ab"),
        (["", "text"], "text"),
    ],
)
def test_text_from_parts(texts, expected):
    """Part リストからテキストを正しく結合することを確認."""
    parts = [_make_part(t) for t in texts]

    assert text_from_parts(parts) == expected


def test_text_from_message():
    """Message からテキストを正しく抽出することを確認."""
    message = Message(role=Role.agent, parts=[_make_part("hello")], message_id="m1")

    assert text_from_message(message) == "hello"


def test_text_from_artifact():
    """Artifact からテキストを正しく抽出することを確認."""
    assert text_from_artifact(_make_artifact("result")) == "result"


@pytest.mark.asyncio
async def test_stream_events_yields_raw_events():
    """stream_events() が A2A の生イベントをそのまま yield することを確認."""
    thinking_event = (
        MagicMock(),
        TaskStatusUpdateEvent(
            status=TaskStatus(state=TaskState.working, message=new_agent_text_message("thinking")),
            final=False,
            task_id="t1",
            context_id="c1",
        ),
    )
    artifact_event = (
        MagicMock(),
        TaskArtifactUpdateEvent(
            artifact=_make_artifact("answer"),
            task_id="t1",
            context_id="c1",
        ),
    )
    client = _make_client_with_mock([thinking_event, artifact_event])

    events = [e async for e in client.stream_events("hello")]

    assert len(events) == 2
    assert events[0] is thinking_event
    assert events[1] is artifact_event


@pytest.mark.asyncio
async def test_stream_events_yields_message():
    """stream_events() が Message をそのまま yield することを確認."""
    message = Message(role=Role.agent, parts=[_make_part("reply")], message_id="m1")
    client = _make_client_with_mock([message])

    events = [e async for e in client.stream_events("hello")]

    assert len(events) == 1
    assert events[0] is message
