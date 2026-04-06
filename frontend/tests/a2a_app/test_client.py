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
    _text_from_artifact,
    _text_from_message,
    _text_from_parts,
)


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

    assert _text_from_parts(parts) == expected


def test_text_from_message():
    """Message からテキストを正しく抽出することを確認."""
    message = Message(role=Role.agent, parts=[_make_part("hello")], message_id="m1")

    assert _text_from_message(message) == "hello"


def test_text_from_artifact():
    """Artifact からテキストを正しく抽出することを確認."""
    assert _text_from_artifact(_make_artifact("result")) == "result"


@pytest.mark.asyncio
async def test_agent_client_stream_yields_thinking():
    """stream() が thinking イベントを ('thinking', text) で yield することを確認."""
    client = _make_client_with_mock([_make_thinking_event("considering...")])

    chunks = [c async for c in client.stream("hello")]

    assert chunks == [("thinking", "considering...")]


@pytest.mark.asyncio
async def test_agent_client_stream_yields_answer_from_artifact():
    """stream() が artifact イベントを ('answer', text) で yield することを確認."""
    client = _make_client_with_mock([_make_artifact_event("final answer")])

    chunks = [c async for c in client.stream("hello")]

    assert chunks == [("answer", "final answer")]


@pytest.mark.asyncio
async def test_agent_client_stream_yields_answer_from_message():
    """stream() が Message イベントを ('answer', text) で yield することを確認."""
    message = Message(role=Role.agent, parts=[_make_part("direct reply")], message_id="m1")
    client = _make_client_with_mock([message])

    chunks = [c async for c in client.stream("hello")]

    assert chunks == [("answer", "direct reply")]


@pytest.mark.asyncio
async def test_agent_client_send_returns_last_answer():
    """send() が最後の answer チャンクのテキストを返すことを確認."""
    client = _make_client_with_mock([
        _make_thinking_event("thinking..."),
        _make_artifact_event("the answer"),
    ])

    result = await client.send("hello")

    assert result == "the answer"
