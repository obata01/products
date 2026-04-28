from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph

from src.application.states import State
from src.common.defs.types import NodeName as N

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.graph.state import CompiledStateGraph

    ClaudeCodeNode = Callable[[State, RunnableConfig], Awaitable[dict]]


class ClaudeCodeWorkflow:
    """Claude Code を利用した単一ノードワークフロー."""

    def build(
        self,
        node: ClaudeCodeNode,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> CompiledStateGraph:
        """ワークフローグラフをコンパイルして返す.

        Args:
            node: CLAUDE_CODE ノードに登録する関数 (CLI 版 / SDK 版を切替可能).
            checkpointer: チェックポインター (省略可).

        Returns:
            コンパイル済みのステートグラフ.
        """
        g = StateGraph(State)
        g.add_node(N.CLAUDE_CODE, node)
        g.add_edge(START, N.CLAUDE_CODE)
        g.add_edge(N.CLAUDE_CODE, END)
        return g.compile(checkpointer=checkpointer)
