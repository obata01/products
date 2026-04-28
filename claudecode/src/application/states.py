from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class State(TypedDict):
    """LangGraph ワークフロー全体で共有するステート定義."""

    last_user_message: str
    chat_history: Annotated[list[BaseMessage], add_messages]
    aborted: bool
    claude_code_session_initialized: bool
