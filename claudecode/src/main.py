from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from src.a2a_app.card import build_claude_code_agent_card
from src.a2a_app.server import create_a2a_app
from src.application.nodes.claude_code import claude_code as claude_code_cli_node
from src.application.nodes.claude_code_sdk import claude_code_sdk as claude_code_sdk_node
from src.application.stream import (
    StreamEvent,
    build_graph_config,
    build_graph_input,
    extract_final_answer,
    run_graph_stream,
)
from src.application.workflows.claude_code import ClaudeCodeWorkflow
from src.common.di.containers import Container
from src.common.exceptions import AppError
from src.common.lib import logging
from src.common.schema.chat import ChatRequest, ChatResponse
from src.common.settings.app import settings

logger = logging.getLogger(__name__)

# Claude Code ノード実装の切替表 (settings.claude_code_backend で選択).
_CLAUDE_CODE_NODE_BY_BACKEND = {
    "cli": claude_code_cli_node,
    "sdk": claude_code_sdk_node,
}

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from langgraph.graph.state import CompiledStateGraph


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """アプリケーションのライフサイクルを管理する."""
    container = Container()
    checkpoint_config = container.app_config().checkpoint
    async with AsyncSqliteSaver.from_conn_string(checkpoint_config.dsn) as checkpointer:
        node = _CLAUDE_CODE_NODE_BY_BACKEND[settings.claude_code_backend]
        app.state.graph = ClaudeCodeWorkflow().build(node=node, checkpointer=checkpointer)
        yield


app = FastAPI(lifespan=lifespan)
app.mount(
    "/a2a",
    create_a2a_app(
        lambda: app.state.graph,
        agent_card=build_claude_code_agent_card(settings.a2a_base_url),
    ),
)


@app.exception_handler(AppError)
async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    """AppError を構造化 JSON レスポンスに整形する.

    ノード層や上位ミドルウェアから伝播する AppError を共通形式で返し、
    クライアントが ``code`` で分岐できるようにする.
    """
    logger.warning("AppError: code=%s, detail=%s", exc.code, exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "detail": exc.detail},
    )


def _sse_line(event: StreamEvent) -> str:
    """StreamEvent を SSE フォーマットの文字列に変換する."""
    return f"data: {json.dumps(event.model_dump(exclude_none=True), ensure_ascii=False)}\n\n"


async def _stream_graph(
    graph: CompiledStateGraph,
    graph_input: dict,
    config: dict,
    session_id: str,
    *,
    include_node_progress: bool | frozenset[str] = True,
) -> AsyncGenerator[str]:
    """``run_graph_stream`` の出力を SSE 文字列に整形して yield する.

    例外捕捉・終端イベント発行 (``done`` / ``error`` / ``input_required``) は
    ``run_graph_stream`` 側で行われるため、ここはトランスポート整形だけに専念する.
    """
    async for event in run_graph_stream(
        graph,
        graph_input,
        config,
        session_id,
        include_node_progress=include_node_progress,
    ):
        yield _sse_line(event)


@app.get("/health")
async def health() -> dict[str, str]:
    """ヘルスチェック用エンドポイント."""
    return {"status": "ok"}


@app.post("/claude-code", response_model=None)
async def claude_code_endpoint(request: ChatRequest) -> StreamingResponse | ChatResponse | JSONResponse:
    """Claude Code を利用したテキスト生成エンドポイント.

    Claude Code CLI にユーザーメッセージを渡し、ストリーミングで結果を返す。
    ファイル I/O は行わず、すべてメモリ上で完結する。

    request.stream=false (デフォルト): JSON レスポンスを返す.
    request.stream=true: SSE ストリーミングレスポンスを返す.

    SSE イベント形式:
        {"type": "node_start", "node": "CLAUDE_CODE", "label": "Claude Code 処理中"}
        {"type": "token",      "node": "CLAUDE_CODE", "content": "<text>"}
        {"type": "progress",   "node": "CLAUDE_CODE", "content": "<status>"}
        {"type": "node_end",   "node": "CLAUDE_CODE"}
        {"type": "done",       "session_id": "<id>",  "message": "<full_text>"}
    """
    session_id = request.session_id or str(uuid.uuid4())
    config = build_graph_config(session_id)
    graph_input = build_graph_input(request.message)

    if request.stream:
        return StreamingResponse(
            _stream_graph(app.state.graph, graph_input, config, session_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # AppError は _handle_app_error で共通整形される。想定外例外のみここで握る.
    try:
        result = await app.state.graph.ainvoke(graph_input, config=config)
    except AppError:
        raise
    except Exception:
        logger.exception("Unexpected error in /claude-code: session_id=%s", session_id)
        return JSONResponse(
            status_code=500,
            content={"code": "internal_error", "detail": "内部エラーが発生しました。"},
        )
    return ChatResponse(session_id=session_id, message=extract_final_answer(result))
