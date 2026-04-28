import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from a2a.types import (
    Message,
    Part,
    Role,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatusUpdateEvent,
    TextPart,
)
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from src.a2a_app.executor import (
    LangGraphAgentExecutor,
    _artifact_event,
    _completed_event,
    _failed_event,
    _input_required_event,
    _stream_event_to_a2a,
    _working_event,
)
from src.application.stream import StreamEvent, StreamEventType, extract_final_answer, extract_text


def _mock_no_interrupt_state():
    """pending interrupt がない StateSnapshot の mock を返す."""
    state = MagicMock()
    state.tasks = ()
    return state


def _make_context(text: str, task_id: str = "task1", context_id: str = "ctx1") -> MagicMock:
    ctx = MagicMock()
    ctx.task_id = task_id
    ctx.context_id = context_id
    ctx.message = Message(
        role=Role.user,
        parts=[Part(root=TextPart(text=text))],
        message_id="msg1",
    )
    return ctx


@pytest.mark.parametrize(
    "content, expected",
    [
        ("hello world", "hello world"),
        ([{"text": "foo"}, {"text": "bar"}], "foobar"),
        ([{"text": "a"}, {"other": "b"}, {"text": "c"}], "ac"),
        ([{"type": "tool_use", "input": {}}], ""),
        ([], ""),
        (42, ""),
    ],
)
def test_extract_text(content, expected):
    """様々な content 形式からテキストを正しく抽出することを確認."""
    assert extract_text(content) == expected


@pytest.mark.parametrize(
    "graph_output, expected",
    [
        (None, ""),
        ({}, ""),
        ({"chat_history": []}, ""),
        ({"chat_history": [HumanMessage("hi")]}, ""),
        ({"chat_history": [AIMessage("answer")]}, "answer"),
        ({"chat_history": [HumanMessage("q"), AIMessage("response")]}, "response"),
    ],
)
def test_extract_final_answer(graph_output, expected):
    """グラフ出力から最終 AIMessage のテキストを正しく抽出することを確認."""
    assert extract_final_answer(graph_output) == expected


@pytest.mark.parametrize("task_id, context_id, expected_task_id, expected_context_id", [
    ("t1", "c1", "t1", "c1"),
    (None, None, "", ""),
])
def test_working_event_state_and_flags(task_id, context_id, expected_task_id, expected_context_id):
    """_working_event が working ステートと final=False を返し、None は空文字にフォールバックすることを確認."""
    event = _working_event("thinking...", task_id, context_id)

    assert event.status.state == TaskState.working
    assert event.final is False
    assert event.task_id == expected_task_id
    assert event.context_id == expected_context_id


@pytest.mark.parametrize("task_id, context_id, expected_task_id", [
    ("t1", "c1", "t1"),
    (None, None, ""),
])
def test_completed_event_state_and_flags(task_id, context_id, expected_task_id):
    """_completed_event が completed ステートと final=True を返し、None は空文字にフォールバックすることを確認."""
    event = _completed_event(task_id, context_id)

    assert event.status.state == TaskState.completed
    assert event.final is True
    assert event.task_id == expected_task_id


@pytest.mark.parametrize("text", ["final answer", ""])
def test_artifact_event_contains_text(text):
    """_artifact_event が正しいテキストを含む Artifact を持つことを確認."""
    event = _artifact_event(text, "t1", "c1")
    extracted = "".join(p.root.text for p in event.artifact.parts if hasattr(p.root, "text"))

    assert extracted == text


def test_failed_event_state_and_flags():
    """_failed_event が failed ステートと final=True を返すことを確認."""
    event = _failed_event("something broke", "t1", "c1")

    assert event.status.state == TaskState.failed
    assert event.final is True


class TestStreamEventToA2A:
    """StreamEvent → A2A イベント翻訳のテスト."""

    def test_token_becomes_working_with_json_payload(self):
        se = StreamEvent(type=StreamEventType.TOKEN, node="CLAUDE_CODE", content="hi")
        events = list(_stream_event_to_a2a(se, task_id="t1", context_id="c1"))

        assert len(events) == 1
        assert isinstance(events[0], TaskStatusUpdateEvent)
        assert events[0].status.state == TaskState.working
        payload = json.loads(events[0].status.message.parts[0].root.text)
        assert payload["type"] == "token"
        assert payload["content"] == "hi"

    def test_done_becomes_artifact_then_completed(self):
        se = StreamEvent(type=StreamEventType.DONE, session_id="s1", message="bye")
        events = list(_stream_event_to_a2a(se, task_id="t1", context_id="c1"))

        assert len(events) == 2
        assert isinstance(events[0], TaskArtifactUpdateEvent)
        text = "".join(p.root.text for p in events[0].artifact.parts if hasattr(p.root, "text"))
        assert text == "bye"
        assert isinstance(events[1], TaskStatusUpdateEvent)
        assert events[1].status.state == TaskState.completed

    def test_input_required_becomes_input_required_event(self):
        se = StreamEvent(type=StreamEventType.INPUT_REQUIRED, metadata={"prompt": "?"})
        events = list(_stream_event_to_a2a(se, task_id="t1", context_id="c1"))

        assert len(events) == 1
        assert isinstance(events[0], TaskStatusUpdateEvent)
        assert events[0].status.state == TaskState.input_required

    def test_error_becomes_failed_event_with_message(self):
        se = StreamEvent(type=StreamEventType.ERROR, error="boom", code="claude_code_error")
        events = list(_stream_event_to_a2a(se, task_id="t1", context_id="c1"))

        assert len(events) == 1
        assert isinstance(events[0], TaskStatusUpdateEvent)
        assert events[0].status.state == TaskState.failed
        text = events[0].status.message.parts[0].root.text
        assert "boom" in text


@pytest.mark.asyncio
async def test_execute_streaming_enqueues_events_in_order():
    """execute() ストリーミング時に thinking → artifact → completed の順でイベントを送信することを確認."""
    final_state = {"chat_history": [AIMessage("final answer")]}
    _meta = {"langgraph_node": "CLAUDE_CODE"}
    graph_events = [
        {"event": "on_chat_model_stream", "name": "ChatModel", "metadata": _meta, "data": {"chunk": AIMessageChunk(content="thinking")}},
        {"event": "on_chain_end", "name": "LangGraph", "metadata": {}, "data": {"output": final_state}},
    ]

    async def fake_astream_events(*args, **kwargs):
        for e in graph_events:
            yield e

    mock_graph = MagicMock()
    mock_graph.astream_events = fake_astream_events
    mock_graph.aget_state = AsyncMock(return_value=_mock_no_interrupt_state())
    mock_queue = AsyncMock()

    ctx = _make_context("hello")
    ctx.configuration = MagicMock(blocking=False)
    executor = LangGraphAgentExecutor(lambda: mock_graph)
    await executor.execute(ctx, mock_queue)

    calls = mock_queue.enqueue_event.call_args_list
    assert len(calls) == 3  # thinking + artifact + completed

    thinking, artifact, completed = (c.args[0] for c in calls)

    assert isinstance(thinking, TaskStatusUpdateEvent) and thinking.status.state == TaskState.working
    assert isinstance(artifact, TaskArtifactUpdateEvent)
    assert isinstance(completed, TaskStatusUpdateEvent) and completed.status.state == TaskState.completed
    assert completed.final is True


@pytest.mark.asyncio
async def test_execute_artifact_contains_final_answer():
    """execute() が AIMessage の内容を Artifact テキストとして送信することを確認."""
    final_state = {"chat_history": [AIMessage("correct answer")]}
    graph_events = [
        {"event": "on_chain_end", "name": "LangGraph", "metadata": {}, "data": {"output": final_state}},
    ]

    async def fake_astream_events(*args, **kwargs):
        for e in graph_events:
            yield e

    mock_graph = MagicMock()
    mock_graph.astream_events = fake_astream_events
    mock_graph.aget_state = AsyncMock(return_value=_mock_no_interrupt_state())
    mock_queue = AsyncMock()

    executor = LangGraphAgentExecutor(lambda: mock_graph)
    await executor.execute(_make_context("hello"), mock_queue)

    artifact_call = mock_queue.enqueue_event.call_args_list[-2]
    artifact_event: TaskArtifactUpdateEvent = artifact_call.args[0]
    text = "".join(p.root.text for p in artifact_event.artifact.parts if hasattr(p.root, "text"))

    assert text == "correct answer"


@pytest.mark.asyncio
async def test_execute_emits_failed_event_when_node_raises_app_error():
    """ノード由来の AppError 発生時、execute() が failed イベントを送信することを確認."""
    from src.common.exceptions import ClaudeCodeError

    async def failing_astream_events(*args, **kwargs):
        if False:
            yield
        raise ClaudeCodeError("upstream failure")

    mock_graph = MagicMock()
    mock_graph.astream_events = failing_astream_events
    mock_graph.aget_state = AsyncMock(return_value=_mock_no_interrupt_state())
    mock_queue = AsyncMock()

    executor = LangGraphAgentExecutor(lambda: mock_graph)
    await executor.execute(_make_context("hello"), mock_queue)

    last_event = mock_queue.enqueue_event.call_args_list[-1].args[0]
    assert isinstance(last_event, TaskStatusUpdateEvent)
    assert last_event.status.state == TaskState.failed
    assert "upstream failure" in last_event.status.message.parts[0].root.text
