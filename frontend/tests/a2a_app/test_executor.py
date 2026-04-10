import pytest
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from a2a.types import (
    Message,
    Part,
    Role,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatusUpdateEvent,
    TextPart,
)

from src.a2a_app.executor import (
    LangGraphAgentExecutor,
    _artifact_event,
    _completed_event,
    _extract_final_answer,
    _extract_text,
    _working_event,
)


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
    assert _extract_text(content) == expected


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
    assert _extract_final_answer(graph_output) == expected


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


@pytest.mark.asyncio
async def test_stream_thinking_enqueues_working_event_per_token():
    """on_chat_model_stream イベントごとに working イベントがキューに追加されることを確認."""
    graph_events = [
        {"event": "on_chat_model_stream", "data": {"chunk": AIMessageChunk(content="Hello")}},
        {"event": "on_chat_model_stream", "data": {"chunk": AIMessageChunk(content=" world")}},
        {"event": "on_chain_end", "name": "LangGraph", "data": {"output": {"chat_history": [AIMessage("Hello world")]}}},
    ]

    async def fake_astream_events(*args, **kwargs):
        for e in graph_events:
            yield e

    mock_graph = MagicMock()
    mock_graph.astream_events = fake_astream_events
    mock_queue = AsyncMock()

    executor = LangGraphAgentExecutor(lambda: mock_graph)
    await executor._stream_thinking({}, {}, "t1", "c1", mock_queue)

    assert mock_queue.enqueue_event.call_count == 2




@pytest.mark.asyncio
async def test_stream_thinking_returns_final_output():
    """on_chain_end LangGraph イベントの output が返されることを確認."""
    final_state = {"chat_history": [AIMessage("done")]}
    graph_events = [
        {"event": "on_chain_end", "name": "LangGraph", "data": {"output": final_state}},
    ]

    async def fake_astream_events(*args, **kwargs):
        for e in graph_events:
            yield e

    mock_graph = MagicMock()
    mock_graph.astream_events = fake_astream_events

    executor = LangGraphAgentExecutor(lambda: mock_graph)
    result = await executor._stream_thinking({}, {}, "t1", "c1", AsyncMock())

    assert result == final_state


@pytest.mark.asyncio
async def test_execute_enqueues_events_in_order():
    """execute() が initial-working → thinking → artifact → completed の順でイベントを送信することを確認."""
    final_state = {"chat_history": [AIMessage("final answer")]}
    graph_events = [
        {"event": "on_chat_model_stream", "data": {"chunk": AIMessageChunk(content="thinking")}},
        {"event": "on_chain_end", "name": "LangGraph", "data": {"output": final_state}},
    ]

    async def fake_astream_events(*args, **kwargs):
        for e in graph_events:
            yield e

    mock_graph = MagicMock()
    mock_graph.astream_events = fake_astream_events
    mock_queue = AsyncMock()

    executor = LangGraphAgentExecutor(lambda: mock_graph)
    await executor.execute(_make_context("hello"), mock_queue)

    calls = mock_queue.enqueue_event.call_args_list
    assert len(calls) == 4  # initial-working + thinking + artifact + completed

    initial, thinking, artifact, completed = (c.args[0] for c in calls)

    assert isinstance(initial, TaskStatusUpdateEvent) and initial.status.state == TaskState.working
    assert isinstance(thinking, TaskStatusUpdateEvent) and thinking.status.state == TaskState.working
    assert isinstance(artifact, TaskArtifactUpdateEvent)
    assert isinstance(completed, TaskStatusUpdateEvent) and completed.status.state == TaskState.completed
    assert completed.final is True


@pytest.mark.asyncio
async def test_execute_artifact_contains_final_answer():
    """execute() が AIMessage の内容を Artifact テキストとして送信することを確認."""
    final_state = {"chat_history": [AIMessage("correct answer")]}
    graph_events = [
        {"event": "on_chain_end", "name": "LangGraph", "data": {"output": final_state}},
    ]

    async def fake_astream_events(*args, **kwargs):
        for e in graph_events:
            yield e

    mock_graph = MagicMock()
    mock_graph.astream_events = fake_astream_events
    mock_queue = AsyncMock()

    executor = LangGraphAgentExecutor(lambda: mock_graph)
    await executor.execute(_make_context("hello"), mock_queue)

    artifact_call = mock_queue.enqueue_event.call_args_list[-2]
    artifact_event: TaskArtifactUpdateEvent = artifact_call.args[0]
    text = "".join(p.root.text for p in artifact_event.artifact.parts if hasattr(p.root, "text"))

    assert text == "correct answer"
