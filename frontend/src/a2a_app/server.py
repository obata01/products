"""A2A Starlette アプリのファクトリー."""

from __future__ import annotations

from typing import TYPE_CHECKING

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore

from src.a2a_app.card import build_agent_card
from src.a2a_app.executor import LangGraphAgentExecutor

if TYPE_CHECKING:
    from collections.abc import Callable

    from langgraph.graph.state import CompiledStateGraph
    from starlette.applications import Starlette


def create_a2a_app(
    graph_getter: Callable[[], CompiledStateGraph],
    base_url: str = "http://localhost:8000/a2a",
) -> Starlette:
    """A2A Starlette アプリを生成して FastAPI へマウントできる形で返す.

    Args:
        graph_getter: CompiledStateGraph を返す callable。例: ``lambda: app.state.graph``
        base_url: エージェントカードに記載する A2A サーバーの公開 URL。

    Returns:
        FastAPI の app.mount() でマウント可能な Starlette ASGI アプリ。
    """
    handler = DefaultRequestHandler(
        agent_executor=LangGraphAgentExecutor(graph_getter),
        task_store=InMemoryTaskStore(),
    )
    return A2AStarletteApplication(
        agent_card=build_agent_card(base_url),
        http_handler=handler,
    ).build()
