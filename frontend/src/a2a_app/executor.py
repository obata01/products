"""LangGraph ワークフローを A2A プロトコルで公開するエグゼキューター."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from a2a.server.agent_execution import AgentExecutor, RequestContext
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
from langchain_core.messages import AIMessage

from src.common.lib import logging

if TYPE_CHECKING:
    from collections.abc import Callable

    from a2a.server.events import EventQueue
    from langgraph.graph.state import CompiledStateGraph

logger = logging.getLogger(__name__)


def _extract_text(content: str | list) -> str:
    """AIMessageChunk の content からテキストを抽出する.

    Args:
        content: str または list[dict] 形式のチャンクコンテンツ.

    Returns:
        抽出されたテキスト文字列.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(item.get("text", "") for item in content if isinstance(item, dict))
    return ""


def _extract_final_answer(graph_output: dict | None) -> str:
    """グラフの最終出力ステートから AIMessage のテキストを取り出す.

    Args:
        graph_output: LangGraph の最終ステート辞書.

    Returns:
        最終回答テキスト.
    """
    if not graph_output:
        return ""
    history = graph_output.get("chat_history", [])
    last_ai = next((m for m in reversed(history) if isinstance(m, AIMessage)), None)
    if not last_ai:
        return ""
    return last_ai.content if isinstance(last_ai.content, str) else str(last_ai.content)


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
        status=TaskStatus(state=TaskState.working, message=new_agent_text_message(text)),
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
        status=TaskStatus(state=TaskState.completed),
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
        artifact=Artifact(artifact_id=str(uuid4()), parts=[Part(root=TextPart(text=text))]),
        task_id=task_id or "",
        context_id=context_id or "",
    )


class LangGraphAgentExecutor(AgentExecutor):
    """LangGraph ワークフローを A2A プロトコルで公開するエグゼキューター.

    FastAPI の lifespan でグラフが初期化されるため、graph_getter で遅延取得する。
    """

    def __init__(self, graph_getter: Callable[[], CompiledStateGraph]) -> None:
        """LangGraphAgentExecutor を初期化する.

        Args:
            graph_getter: CompiledStateGraph を返す callable。例: ``lambda: app.state.graph``
        """
        self._get_graph = graph_getter

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """A2A タスクを実行し、思考と最終回答をストリーミングする."""
        user_text = " ".join(
            part.root.text for part in context.message.parts if hasattr(part.root, "text")
        )
        task_id, context_id = context.task_id, context.context_id
        thread_id = context_id or task_id or "default"

        await event_queue.enqueue_event(_working_event("思考中...", task_id, context_id))

        graph_input = {"last_user_message": user_text, "chat_history": []}
        config = {"configurable": {"thread_id": thread_id}}
        final_output = await self._stream_thinking(graph_input, config, task_id, context_id, event_queue)

        await event_queue.enqueue_event(_artifact_event(_extract_final_answer(final_output), task_id, context_id))
        await event_queue.enqueue_event(_completed_event(task_id, context_id))
        logger.info("A2A task completed: task_id=%s", task_id)

    async def _stream_thinking(
        self,
        graph_input: dict,
        config: dict,
        task_id: str | None,
        context_id: str | None,
        event_queue: EventQueue,
    ) -> dict | None:
        """グラフを実行しながら LLM のストリーミングトークンを思考として配信する.

        Args:
            graph_input: LangGraph への入力ステート.
            config: LangGraph の configurable 設定.
            task_id: タスク ID.
            context_id: コンテキスト ID.
            event_queue: イベントキュー.

        Returns:
            グラフの最終出力ステート. 取得できなかった場合は None.
        """
        thinking_buf: list[str] = []
        final_output: dict | None = None

        async for event in self._get_graph().astream_events(graph_input, config=config, version="v2"):
            match event["event"]:
                case "on_chat_model_stream":
                    text = _extract_text(event["data"]["chunk"].content)
                    if text:
                        thinking_buf.append(text)
                        await event_queue.enqueue_event(
                            _working_event("".join(thinking_buf), task_id, context_id)
                        )
                case "on_chain_end" if event.get("name") == "LangGraph":
                    final_output = event["data"].get("output")

        return final_output

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """キャンセルは未サポート.

        Raises:
            NotImplementedError: 常に送出する.
        """
        raise NotImplementedError("This agent does not support task cancellation.")
