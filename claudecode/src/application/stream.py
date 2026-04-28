"""グラフストリーミングの共通ユーティリティ.

API (SSE) と A2A の両パスで使う、統一されたイベントストリームを提供する。

型の関係:
    LangGraph astream_events
        ↓  (stream_graph_events で変換)
    GraphEvent  (内部表現 — プロトコル非依存)
        ↓  (to_stream_event で変換)
    StreamEvent (クライアント向け — SSE / A2A 共通)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from src.common.defs.types import NODE_LABELS, NodeName
from src.common.exceptions import AppError
from src.common.lib import logging
from src.common.lib.bases import BaseModel

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from langgraph.graph.state import CompiledStateGraph

logger = logging.getLogger(__name__)

NODE_NAMES: frozenset[str] = frozenset(n.value for n in NodeName)

# Claude Code ノードが dispatch するカスタムイベント名.
CLAUDE_CODE_TOKEN_EVENT = "claude_code_token"  # noqa: S105
CLAUDE_CODE_PROGRESS_EVENT = "claude_code_progress"


def extract_text(content: str | list) -> str:
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


def extract_final_answer(graph_output: dict | None) -> str:
    """グラフの最終出力ステートから AIMessage のテキストを取り出す.

    Args:
        graph_output: LangGraph の最終ステート辞書.

    Returns:
        最終回答テキスト. 取得できなかった場合は空文字列.
    """
    if not graph_output:
        return ""
    history = graph_output.get("chat_history", [])
    last_ai = next((m for m in reversed(history) if isinstance(m, AIMessage)), None)
    if not last_ai:
        return ""
    return last_ai.content if isinstance(last_ai.content, str) else str(last_ai.content)


def build_graph_input(message: str) -> dict:
    """グラフへの入力ステートを構築する.

    ユーザーメッセージを HumanMessage として chat_history にも追加する。

    Args:
        message: ユーザーからの入力メッセージ.

    Returns:
        LangGraph に渡す入力 dict.
    """
    return {
        "last_user_message": message,
        "chat_history": [HumanMessage(content=message)],
    }


def build_graph_config(thread_id: str) -> dict:
    """LangGraph の configurable 設定を構築する.

    Args:
        thread_id: スレッド (セッション) を識別する ID.

    Returns:
        LangGraph に渡す config dict.
    """
    return {"configurable": {"thread_id": thread_id}}


# 承認と見なすユーザー応答の一覧.
_APPROVE_WORDS: frozenset[str] = frozenset({"yes", "approve", "ok", "はい", "承認"})


async def has_pending_interrupt(graph: CompiledStateGraph, config: dict) -> bool:
    """グラフに未処理の interrupt があるかを判定する.

    Args:
        graph: コンパイル済みステートグラフ.
        config: LangGraph の configurable 設定.

    Returns:
        未処理の interrupt がある場合 True.
    """
    state = await graph.aget_state(config)
    return bool(state.tasks and any(t.interrupts for t in state.tasks))


def build_resume_input(user_message: str) -> Command:
    """Interrupt に対するユーザー応答から resume 用の Command を構築する.

    Args:
        user_message: ユーザーの応答メッセージ.

    Returns:
        resume 用の Command.
    """
    return Command(resume={"approved": user_message.strip().lower() in _APPROVE_WORDS})


# ---------------------------------------------------------------------------
# 内部イベント — LangGraph astream_events の抽象化
# ---------------------------------------------------------------------------


class GraphEventKind(StrEnum):
    """GraphEvent の種別.

    LangGraph の ``astream_events(version="v2")`` が返すイベントを
    本プロジェクト用に抽象化したもの。LangGraph 側の仕様ではなく
    プロジェクト独自の定義のため、必要に応じて変更可能。

    対応する LangGraph イベント:
        NODE_START  ← on_chain_start  (ノードレベル)
        NODE_END    ← on_chain_end    (ノードレベル)
        TOKEN       ← on_chat_model_stream
        GRAPH_END   ← on_chain_end    (name="LangGraph")
        INTERRUPT   ← GraphInterrupt 例外 (interrupt() 呼び出し)
    """

    NODE_START = "node_start"
    NODE_END = "node_end"
    TOKEN = "token"  # noqa: S105
    PROGRESS = "progress"
    GRAPH_END = "graph_end"
    INTERRUPT = "interrupt"


@dataclass(frozen=True, slots=True)
class GraphEvent:
    """グラフストリーミングの統一イベント.

    Attributes:
        kind: イベント種別.
        node: 対象ノード名.
        text: トークンテキスト (TOKEN イベントのみ).
        output: グラフ最終出力 (GRAPH_END イベントのみ).
        interrupt_value: interrupt() に渡された値 (INTERRUPT イベントのみ).
    """

    kind: GraphEventKind
    node: str = ""
    text: str = ""
    output: dict | None = None
    interrupt_value: Any = None


# ---------------------------------------------------------------------------
# クライアント向けイベント — SSE / A2A 共通
# ---------------------------------------------------------------------------


class StreamEventType(StrEnum):
    """クライアントへ送信するストリーミングイベントの種別.

    GraphEventKind (内部) → StreamEventType (外部) のマッピングは
    ``to_stream_event()`` で一元管理する。
    """

    NODE_START = "node_start"
    NODE_END = "node_end"
    TOKEN = "token"  # noqa: S105
    PROGRESS = "progress"
    INPUT_REQUIRED = "input_required"
    DONE = "done"
    ERROR = "error"


class StreamEvent(BaseModel):
    """SSE / A2A 共通のクライアント向けイベントスキーマ.

    Attributes:
        type: イベント種別.
        node: 対象ノード名 (NODE_START / NODE_END / TOKEN).
        label: ノードの表示用ラベル (NODE_START / NODE_END / TOKEN).
        content: LLM トークン本文 (TOKEN のみ).
        session_id: セッション ID (DONE / ERROR のみ).
        message: 最終回答全文 (DONE のみ).
        error: エラー詳細メッセージ (ERROR のみ).
        code: エラーコード (ERROR のみ).
    """

    type: StreamEventType
    node: str | None = None
    label: str | None = None
    content: str | None = None
    metadata: dict | None = None
    session_id: str | None = None
    message: str | None = None
    error: str | None = None
    code: str | None = None


# GraphEventKind → StreamEventType の対応表.
# GRAPH_END はクライアントに直接送信しないため含まない.
_KIND_TO_STREAM_TYPE: dict[GraphEventKind, StreamEventType] = {
    GraphEventKind.NODE_START: StreamEventType.NODE_START,
    GraphEventKind.NODE_END: StreamEventType.NODE_END,
    GraphEventKind.TOKEN: StreamEventType.TOKEN,
    GraphEventKind.PROGRESS: StreamEventType.PROGRESS,
    GraphEventKind.INTERRUPT: StreamEventType.INPUT_REQUIRED,
}

# ノード進捗イベント (node_start / node_end) に該当する GraphEventKind.
_NODE_PROGRESS_KINDS: frozenset[GraphEventKind] = frozenset(
    {
        GraphEventKind.NODE_START,
        GraphEventKind.NODE_END,
    }
)


def to_stream_event(
    ev: GraphEvent,
    *,
    include_node_progress: bool | frozenset[str] = True,
) -> StreamEvent | None:
    """GraphEvent をクライアント向け StreamEvent に変換する.

    GRAPH_END など対応する StreamEventType がない場合は None を返す。

    Args:
        ev: 内部グラフイベント.
        include_node_progress: ノード進捗イベント (node_start / node_end) の送信制御。
            True — 全ノードの進捗を送信 (デフォルト).
            False — 全ノードの進捗を抑制.
            frozenset[str] — 指定したノード名のみ進捗を送信し、それ以外は抑制.

    Returns:
        変換後の StreamEvent。変換対象外の場合は None.
    """
    if ev.kind in _NODE_PROGRESS_KINDS:
        if include_node_progress is False:
            return None
        if isinstance(include_node_progress, frozenset) and ev.node not in include_node_progress:
            return None
    stream_type = _KIND_TO_STREAM_TYPE.get(ev.kind)
    if stream_type is None:
        return None
    return StreamEvent(
        type=stream_type,
        node=ev.node or None,
        label=NODE_LABELS.get(ev.node) if ev.node else None,
        content=ev.text or None,
        metadata=ev.interrupt_value if ev.kind == GraphEventKind.INTERRUPT else None,
    )


_UNEXPECTED_ERROR_DETAIL = "内部エラーが発生しました。"
_UNEXPECTED_ERROR_CODE = "internal_error"


def build_error_event(exc: BaseException, *, session_id: str | None = None) -> StreamEvent:
    """例外からクライアント向けの ERROR StreamEvent を構築する.

    AppError サブクラスはその detail / code をそのまま採用し、
    それ以外の例外は汎用メッセージに丸めてクライアントへの内部情報漏洩を防ぐ.

    Args:
        exc: 発生した例外.
        session_id: 対応するセッション ID.

    Returns:
        ERROR 種別の StreamEvent.
    """
    if isinstance(exc, AppError):
        return StreamEvent(
            type=StreamEventType.ERROR,
            session_id=session_id,
            error=exc.detail,
            code=exc.code,
        )
    return StreamEvent(
        type=StreamEventType.ERROR,
        session_id=session_id,
        error=_UNEXPECTED_ERROR_DETAIL,
        code=_UNEXPECTED_ERROR_CODE,
    )


# ---------------------------------------------------------------------------
# ストリーミング本体
# ---------------------------------------------------------------------------


class LangChainEventType(StrEnum):
    """langchain_core の astream_events が返すイベント種別.

    langchain_core.runnables.schema.BaseStreamEvent の event フィールドに対応する。
    ライブラリ側では str 型のみで型定義が提供されていないため、本プロジェクトで定義する。

    パターン: on_{runnable_type}_{stage}
        runnable_type: chain | chat_model | llm | prompt | retriever | tool
        stage: start | stream | end  (tool のみ error もあり)
    例外: on_custom_event (ユーザー定義イベント)
    """

    # chain
    ON_CHAIN_START = "on_chain_start"
    ON_CHAIN_STREAM = "on_chain_stream"
    ON_CHAIN_END = "on_chain_end"
    # chat_model
    ON_CHAT_MODEL_START = "on_chat_model_start"
    ON_CHAT_MODEL_STREAM = "on_chat_model_stream"
    ON_CHAT_MODEL_END = "on_chat_model_end"
    # llm
    ON_LLM_START = "on_llm_start"
    ON_LLM_STREAM = "on_llm_stream"
    ON_LLM_END = "on_llm_end"
    # prompt
    ON_PROMPT_START = "on_prompt_start"
    ON_PROMPT_STREAM = "on_prompt_stream"
    ON_PROMPT_END = "on_prompt_end"
    # retriever
    ON_RETRIEVER_START = "on_retriever_start"
    ON_RETRIEVER_STREAM = "on_retriever_stream"
    ON_RETRIEVER_END = "on_retriever_end"
    # tool
    ON_TOOL_START = "on_tool_start"
    ON_TOOL_STREAM = "on_tool_stream"
    ON_TOOL_END = "on_tool_end"
    ON_TOOL_ERROR = "on_tool_error"
    # custom
    ON_CUSTOM_EVENT = "on_custom_event"


class _EventMetadata(TypedDict, total=False):
    """LangGraph がノード実行時に自動注入するメタデータのうち、本モジュールで参照するキー.

    LangGraph の astream_events(version="v2") が返す各イベントの metadata フィールドに
    自動で設定される。キー名は LangGraph 内部の規約による。
    """

    langgraph_node: str


_CUSTOM_EVENT_PARSERS: dict[str, GraphEventKind] = {
    CLAUDE_CODE_TOKEN_EVENT: GraphEventKind.TOKEN,
    CLAUDE_CODE_PROGRESS_EVENT: GraphEventKind.PROGRESS,
}

# カスタムイベント種別ごとの data キー名.
_CUSTOM_EVENT_TEXT_KEYS: dict[GraphEventKind, str] = {
    GraphEventKind.TOKEN: "text",
    GraphEventKind.PROGRESS: "message",
}


def _parse_custom_event(name: str, data: dict, node: str) -> GraphEvent | None:
    """ON_CUSTOM_EVENT を GraphEvent に変換する.

    Args:
        name: カスタムイベント名.
        data: イベントデータ.
        node: 発行元ノード名.

    Returns:
        変換後の GraphEvent。対象外の場合は None.
    """
    kind = _CUSTOM_EVENT_PARSERS.get(name)
    if kind is None:
        return None
    text_key = _CUSTOM_EVENT_TEXT_KEYS.get(kind, "text")
    return GraphEvent(kind=kind, node=node, text=data.get(text_key, ""))


def _parse_raw_event(event: dict[str, Any]) -> GraphEvent | None:
    """LangGraph の生イベント 1 件を GraphEvent に変換する.

    対応するイベント種別でない場合は None を返す。

    Args:
        event: astream_events(version="v2") が返す生イベント dict.

    Returns:
        変換後の GraphEvent。対象外の場合は None.
    """
    name: str = event.get("name", "")
    metadata: _EventMetadata = event.get("metadata", {})
    event_type: LangChainEventType = event["event"]

    is_node_event = name in NODE_NAMES and metadata.get("langgraph_node") == name

    if is_node_event and event_type in (LangChainEventType.ON_CHAIN_START, LangChainEventType.ON_CHAIN_END):
        kind = GraphEventKind.NODE_START if event_type == LangChainEventType.ON_CHAIN_START else GraphEventKind.NODE_END
        return GraphEvent(kind=kind, node=name)

    if event_type == LangChainEventType.ON_CHAT_MODEL_STREAM:
        text = extract_text(event["data"]["chunk"].content)
        if text:
            node = metadata.get("langgraph_node", "")
            return GraphEvent(kind=GraphEventKind.TOKEN, node=node, text=text)
        return None

    if event_type == LangChainEventType.ON_CHAIN_END and name == "LangGraph":
        return GraphEvent(kind=GraphEventKind.GRAPH_END, output=event["data"].get("output"))

    if event_type == LangChainEventType.ON_CUSTOM_EVENT:
        return _parse_custom_event(name, event.get("data", {}), metadata.get("langgraph_node", ""))

    return None


async def _yield_interrupt_events(graph: CompiledStateGraph, config: dict) -> AsyncIterator[GraphEvent]:
    """グラフステートから未処理の interrupt を INTERRUPT イベントとして yield する.

    Args:
        graph: コンパイル済みステートグラフ.
        config: LangGraph の configurable 設定.

    Yields:
        GraphEvent: 各 interrupt に対応する INTERRUPT イベント.
    """
    state = await graph.aget_state(config)
    if state.tasks:
        for task in state.tasks:
            for intr in task.interrupts:
                yield GraphEvent(
                    kind=GraphEventKind.INTERRUPT,
                    node=task.name,
                    interrupt_value=intr.value,
                )


async def stream_graph_events(
    graph: CompiledStateGraph,
    graph_input: dict,
    config: dict,
) -> AsyncIterator[GraphEvent]:
    """グラフを astream_events で実行し、統一されたイベントストリームを yield する.

    interrupt() によるグラフ一時停止を検知した場合は INTERRUPT イベントを yield する。

    Args:
        graph: コンパイル済みステートグラフ.
        graph_input: グラフへの入力ステート.
        config: LangGraph の configurable 設定.

    Yields:
        GraphEvent: ノード開始/終了、トークン、グラフ終了、割り込みの各イベント.
    """
    async for raw_event in graph.astream_events(graph_input, config=config, version="v2"):
        parsed = _parse_raw_event(raw_event)
        if parsed is not None:
            yield parsed

    # interrupt() でグラフが一時停止した場合でも on_chain_end (GRAPH_END) は発火するため、
    # got_graph_end フラグではなく常にステートを確認して INTERRUPT イベントを yield する。
    # 正常完了時は pending interrupt がないため何も yield されない。
    async for interrupt_event in _yield_interrupt_events(graph, config):
        yield interrupt_event


# ---------------------------------------------------------------------------
# プロトコル非依存の高レベル API — HTTP SSE / A2A から共通利用
# ---------------------------------------------------------------------------


_TERMINAL_STREAM_EVENT_TYPES: frozenset[StreamEventType] = frozenset(
    {StreamEventType.DONE, StreamEventType.INPUT_REQUIRED, StreamEventType.ERROR}
)


def is_terminal_stream_event(event: StreamEvent) -> bool:
    """ストリームの終端イベントかを判定する.

    終端イベントは ``run_graph_stream`` の最後に必ず 1 回だけ yield される.
    プロトコル変換側 (HTTP SSE / A2A) はこれを境にライフサイクル完了処理を行う.

    Args:
        event: 判定対象の StreamEvent.

    Returns:
        ``DONE`` / ``INPUT_REQUIRED`` / ``ERROR`` のいずれかなら True.
    """
    return event.type in _TERMINAL_STREAM_EVENT_TYPES


async def run_graph_stream(
    graph: CompiledStateGraph,
    graph_input: dict | Command,
    config: dict,
    session_id: str,
    *,
    include_node_progress: bool | frozenset[str] = True,
) -> AsyncIterator[StreamEvent]:
    """グラフを実行し、プロトコル非依存の StreamEvent ストリームを yield する.

    HTTP SSE / A2A など複数プロトコルから共通利用できる高レベル API.
    最後に必ず 1 件の終端イベント (``DONE`` / ``INPUT_REQUIRED`` / ``ERROR``) を
    yield してから終了する.

    例外ハンドリングと終端イベント発行をここで一元化することで、各プロトコル側は
    "受け取った StreamEvent を自プロトコルのイベントへ翻訳する" ことだけに集中できる.

    Args:
        graph: コンパイル済みステートグラフ.
        graph_input: グラフへの入力ステート (新規実行時は dict、resume 時は Command).
        config: LangGraph の configurable 設定.
        session_id: 終端イベントに含めるセッション ID.
        include_node_progress: ノード進捗イベント (node_start / node_end) の送信制御.

    Yields:
        中間イベント (TOKEN / PROGRESS / NODE_START / NODE_END / INPUT_REQUIRED) と
        終端イベント (DONE / INPUT_REQUIRED / ERROR).
        ``INPUT_REQUIRED`` は中間として 1 度 yield された場合は終端も兼ねる.
    """
    final_message = ""
    interrupted = False

    try:
        async for ev in stream_graph_events(graph, graph_input, config):
            se = to_stream_event(ev, include_node_progress=include_node_progress)
            if se is not None:
                if se.type == StreamEventType.INPUT_REQUIRED:
                    interrupted = True
                yield se
                continue
            if ev.kind == GraphEventKind.GRAPH_END:
                final_message = extract_final_answer(ev.output)
    except AppError as e:
        logger.warning("Graph stream aborted: session_id=%s, code=%s, detail=%s", session_id, e.code, e.detail)
        yield build_error_event(e, session_id=session_id)
        return
    except Exception as e:
        logger.exception("Unexpected graph stream error: session_id=%s", session_id)
        yield build_error_event(e, session_id=session_id)
        return

    if not interrupted:
        yield StreamEvent(
            type=StreamEventType.DONE,
            session_id=session_id,
            message=final_message,
        )
