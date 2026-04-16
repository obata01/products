"""a2a_stream ページの Template サーバー固有変換ロジックのテスト."""

import json

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


def _se_json(se: dict) -> str:
    """StreamEvent dict を JSON 文字列に変換する."""
    return json.dumps(se, ensure_ascii=False)


def _make_working_event(text: str) -> tuple:
    """working 状態の TaskStatusUpdateEvent を作成する."""
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
async def test_node_start_yields_thinking_with_label():
    """node_start StreamEvent が label 付きの THINKING チャンクに変換されることを確認."""
    client = _make_client_with_mock([
        _make_working_event(_se_json({"type": "node_start", "node": "SAMPLE", "label": "分析中"})),
    ])

    chunks = [c async for c in _stream_template_chunks(client, "hello")]

    assert chunks == [(ChunkType.THINKING, "**分析中**")]


@pytest.mark.asyncio
async def test_token_yields_thinking_with_content():
    """node_start + token で label : content 形式の THINKING になることを確認."""
    client = _make_client_with_mock([
        _make_working_event(_se_json({"type": "node_start", "node": "SAMPLE", "label": "分析中"})),
        _make_working_event(_se_json({"type": "token", "node": "SAMPLE", "content": "hello"})),
    ])

    chunks = [c async for c in _stream_template_chunks(client, "hello")]

    assert chunks == [
        (ChunkType.THINKING, "**分析中**"),
        (ChunkType.THINKING, "**分析中** : hello"),
    ]


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
        _make_working_event(_se_json({"type": "node_start", "node": "SAMPLE", "label": "分析中"})),
        _make_working_event(_se_json({"type": "token", "node": "SAMPLE", "content": "分析結果"})),
        _make_working_event(_se_json({"type": "node_end", "node": "SAMPLE"})),
        _make_artifact_event("the answer"),
    ])

    chunks = [c async for c in _stream_template_chunks(client, "hello")]

    assert chunks == [
        (ChunkType.THINKING, "**分析中**"),
        (ChunkType.THINKING, "**分析中** : 分析結果"),
        (ChunkType.ANSWER, "the answer"),
    ]


@pytest.mark.asyncio
async def test_input_required_in_working_event():
    """working イベント内の input_required StreamEvent が INPUT_REQUIRED チャンクになることを確認."""
    ir_se = {"type": "input_required", "metadata": {"message": "確認", "preview": "内容"}}
    client = _make_client_with_mock([
        _make_working_event(_se_json(ir_se)),
    ])

    chunks = [c async for c in _stream_template_chunks(client, "hello")]

    assert len(chunks) == 1
    assert chunks[0][0] == ChunkType.INPUT_REQUIRED
    metadata = json.loads(chunks[0][1])
    assert metadata["message"] == "確認"
    assert metadata["preview"] == "内容"
    assert metadata["context_id"] == "c1"


@pytest.mark.asyncio
async def test_empty_text_events_are_skipped():
    """テキストが空のイベントはスキップされることを確認."""
    client = _make_client_with_mock([
        _make_working_event(""),
        _make_artifact_event(""),
    ])

    chunks = [c async for c in _stream_template_chunks(client, "hello")]

    assert chunks == []


@pytest.mark.asyncio
async def test_multiple_nodes_cumulative_thinking():
    """複数ノードの thinking が累積的にフォーマットされることを確認."""
    client = _make_client_with_mock([
        _make_working_event(_se_json({"type": "node_start", "node": "SAMPLE", "label": "分析中"})),
        _make_working_event(_se_json({"type": "token", "node": "SAMPLE", "content": "結果A"})),
        _make_working_event(_se_json({"type": "node_end", "node": "SAMPLE"})),
        _make_working_event(_se_json({"type": "node_start", "node": "CONFIRM", "label": "確認待ち"})),
    ])

    chunks = [c async for c in _stream_template_chunks(client, "hello")]

    assert chunks[-1] == (ChunkType.THINKING, "**分析中** : 結果A\n\n**確認待ち**")
