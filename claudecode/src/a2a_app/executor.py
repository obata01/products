"""LangGraph ワークフローを A2A プロトコルで公開するエグゼキューター.

ストリーミングの中核ロジックは ``src.application.stream.run_graph_stream`` に集約されており、
本モジュールはそこから流れてくる ``StreamEvent`` を A2A プロトコルのイベントへ翻訳する
責務だけを持つ. HTTP SSE 経路 (src.main._stream_graph) と完全に同じイベントストリームを
受け取るため、両経路の動作は本質的に揃う.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue  # noqa: TC002
from a2a.types import (
    Artifact,
    Part,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)
from a2a.utils import new_agent_text_message

from src.application.stream import (
    StreamEvent,
    StreamEventType,
    build_graph_config,
    build_graph_input,
    build_resume_input,
    has_pending_interrupt,
    run_graph_stream,
)
from src.common.lib import logging

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from langgraph.graph.state import CompiledStateGraph
    from langgraph.types import Command

    A2AEvent = TaskStatusUpdateEvent | TaskArtifactUpdateEvent

logger = logging.getLogger(__name__)


def _working_event(text: str, task_id: str | None, context_id: str | None) -> TaskStatusUpdateEvent:
    """思考中を表す TaskStatusUpdateEvent を生成する.

    Args:
        text: 思考テキスト.
        task_id: タスク ID.
        context_id: コンテキスト ID.

    Returns:
        final=False の working ステータスイベント.
    """
    return TaskStatusUpdateEvent(
        status=TaskStatus(
            state=TaskState.working,
            message=new_agent_text_message(text),
        ),
        final=False,
        task_id=task_id or "",
        context_id=context_id or "",
    )


def _input_required_event(task_id: str | None, context_id: str | None) -> TaskStatusUpdateEvent:
    """入力待ちを表す TaskStatusUpdateEvent を生成する.

    Args:
        task_id: タスク ID.
        context_id: コンテキスト ID.

    Returns:
        final=False の input_required ステータスイベント.
    """
    return TaskStatusUpdateEvent(
        status=TaskStatus(
            state=TaskState.input_required,
            message=new_agent_text_message("ユーザーの確認を待っています。"),
        ),
        final=False,
        task_id=task_id or "",
        context_id=context_id or "",
    )


def _completed_event(task_id: str | None, context_id: str | None) -> TaskStatusUpdateEvent:
    """完了を表す TaskStatusUpdateEvent を生成する.

    Args:
        task_id: タスク ID.
        context_id: コンテキスト ID.

    Returns:
        final=True の completed ステータスイベント.
    """
    return TaskStatusUpdateEvent(
        status=TaskStatus(
            state=TaskState.completed,
        ),
        final=True,
        task_id=task_id or "",
        context_id=context_id or "",
    )


def _failed_event(error_text: str, task_id: str | None, context_id: str | None) -> TaskStatusUpdateEvent:
    """失敗を表す TaskStatusUpdateEvent を生成する.

    Args:
        error_text: クライアントに見せるエラーメッセージ.
        task_id: タスク ID.
        context_id: コンテキスト ID.

    Returns:
        final=True の failed ステータスイベント.
    """
    return TaskStatusUpdateEvent(
        status=TaskStatus(
            state=TaskState.failed,
            message=new_agent_text_message(error_text),
        ),
        final=True,
        task_id=task_id or "",
        context_id=context_id or "",
    )


def _artifact_event(text: str, task_id: str | None, context_id: str | None) -> TaskArtifactUpdateEvent:
    """最終回答を格納した TaskArtifactUpdateEvent を生成する.

    Args:
        text: 最終回答テキスト.
        task_id: タスク ID.
        context_id: コンテキスト ID.

    Returns:
        テキストパーツを含む Artifact イベント.
    """
    return TaskArtifactUpdateEvent(
        artifact=Artifact(
            artifact_id=str(uuid4()),
            parts=[Part(root=TextPart(text=text))],
        ),
        task_id=task_id or "",
        context_id=context_id or "",
    )


def _stream_event_to_a2a(
    event: StreamEvent,
    *,
    task_id: str | None,
    context_id: str | None,
) -> Iterable[A2AEvent]:
    """1 件の StreamEvent を 1 つ以上の A2A イベントへ翻訳する.

    終端イベント (DONE / INPUT_REQUIRED / ERROR) は A2A のライフサイクル完了系
    (artifact + completed / input_required / failed) へ展開する.
    中間イベント (TOKEN / PROGRESS / NODE_START / NODE_END) は working ステータスに
    JSON ペイロードを載せて配信する.

    Args:
        event: 共通イベント.
        task_id: タスク ID.
        context_id: コンテキスト ID.

    Returns:
        A2A イベントの順序付き列.
    """
    if event.type == StreamEventType.DONE:
        return (
            _artifact_event(event.message or "", task_id, context_id),
            _completed_event(task_id, context_id),
        )
    if event.type == StreamEventType.INPUT_REQUIRED:
        return (_input_required_event(task_id, context_id),)
    if event.type == StreamEventType.ERROR:
        return (_failed_event(event.error or "Unknown error", task_id, context_id),)
    return (_working_event(event.model_dump_json(exclude_none=True), task_id, context_id),)


class LangGraphAgentExecutor(AgentExecutor):
    """LangGraph ワークフローを A2A プロトコルで公開するエグゼキューター.

    FastAPI の lifespan でグラフが初期化されるため、graph_getter で遅延取得する.
    """

    def __init__(self, graph_getter: Callable[[], CompiledStateGraph]) -> None:
        """LangGraphAgentExecutor を初期化する.

        Args:
            graph_getter: CompiledStateGraph を返す callable。例: ``lambda: app.state.graph``
        """
        self._get_graph = graph_getter

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """A2A タスクを実行し、結果をイベントキューに送信する.

        ``run_graph_stream`` から流れる共通 StreamEvent を A2A イベントへ翻訳する.
        終端処理 (artifact + completed / input_required / failed) は StreamEvent の
        終端タイプに応じて自動的に発火するため、本メソッドは終端判定を持たない.

        Args:
            context: A2A リクエストコンテキスト. メッセージ、タスク ID 等を保持する.
            event_queue: A2A イベントの送信先キュー.
        """
        user_text = " ".join(part.root.text for part in context.message.parts if hasattr(part.root, "text"))
        task_id, context_id = context.task_id, context.context_id
        thread_id = context_id or task_id or "default"
        config = build_graph_config(thread_id)
        graph = self._get_graph()

        graph_input = await self._resolve_input(graph, config, user_text)

        logger.info("A2A task started: task_id=%s, thread_id=%s", task_id, thread_id)
        async for event in run_graph_stream(graph, graph_input, config, thread_id):
            for a2a_event in _stream_event_to_a2a(event, task_id=task_id, context_id=context_id):
                await event_queue.enqueue_event(a2a_event)
            self._log_terminal(event, task_id)

    async def _resolve_input(
        self,
        graph: CompiledStateGraph,
        config: dict,
        user_text: str,
    ) -> dict | Command:
        """Pending interrupt の有無に応じてグラフ入力を構築する.

        pending interrupt がある場合は build_resume_input で resume 用 Command を返し、
        ない場合は build_graph_input で新規実行用の入力 dict を返す.

        Args:
            graph: コンパイル済みステートグラフ. ステート確認に使用する.
            config: LangGraph の configurable 設定.
            user_text: ユーザーからの入力テキスト.

        Returns:
            新規実行時は入力 dict、resume 時は Command.
        """
        if await has_pending_interrupt(graph, config):
            return build_resume_input(user_text)
        return build_graph_input(user_text)

    @staticmethod
    def _log_terminal(event: StreamEvent, task_id: str | None) -> None:
        """終端イベントだけ INFO ログに残す.

        Args:
            event: 共通イベント.
            task_id: タスク ID.
        """
        if event.type == StreamEventType.DONE:
            logger.info("A2A task completed: task_id=%s", task_id)
        elif event.type == StreamEventType.INPUT_REQUIRED:
            logger.info("A2A task waiting for input: task_id=%s", task_id)
        elif event.type == StreamEventType.ERROR:
            logger.warning("A2A task failed: task_id=%s, code=%s, error=%s", task_id, event.code, event.error)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """キャンセルは未サポート.

        Raises:
            NotImplementedError: 常に送出する.
        """
        raise NotImplementedError("This agent does not support task cancellation.")
