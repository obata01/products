"""A2A Starlette アプリのファクトリー."""

from __future__ import annotations

from typing import TYPE_CHECKING

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore

from src.a2a_app.executor import LangGraphAgentExecutor

if TYPE_CHECKING:
    from collections.abc import Callable

    from a2a.types import AgentCard
    from langgraph.graph.state import CompiledStateGraph
    from starlette.applications import Starlette


def create_a2a_app(
    graph_getter: Callable[[], CompiledStateGraph],
    *,
    agent_card: AgentCard,
) -> Starlette:
    """A2A Starlette アプリを生成して FastAPI へマウントできる形で返す.

    Args:
        graph_getter: CompiledStateGraph を返す callable。例: ``lambda: app.state.graph``
        agent_card: A2A プロトコルに準拠した AgentCard.

    Returns:
        FastAPI の app.mount() でマウント可能な Starlette ASGI アプリ.
    """
    handler = DefaultRequestHandler(
        agent_executor=LangGraphAgentExecutor(graph_getter),
        task_store=InMemoryTaskStore(),
    )
    return A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=handler,
    ).build()
