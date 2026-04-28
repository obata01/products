# `src/application/stream.py` 詳解

API (SSE) と A2A の両プロトコルにストリーミング配信するための **イベント変換ハブ**。LangGraph の `astream_events` が返す生イベントを、プロジェクト独自の内部表現を経由してクライアント契約まで 3 段階で翻訳する。

---

## 1. 概要

### 責務
- LangGraph `astream_events(version="v2")` の生イベントを消費する
- 本プロジェクトで扱う意味のあるイベントだけに絞り込み、内部表現 `GraphEvent` に変換する
- `GraphEvent` をクライアント向けスキーマ `StreamEvent` に変換する
- `interrupt()` でグラフが一時停止したケースを検知し、専用イベントを差し込む
- API / A2A 両プロトコルが **同じ `StreamEvent`** を共有できるようにする

### レイヤー上の位置
- `application/` 層（business/workflow 側）
- 下位レイヤーの `components/` には依存しない
- FastAPI ([src/main.py](src/main.py)) と A2A エグゼキュータ ([src/a2a_app/executor.py](src/a2a_app/executor.py)) の両方から利用される

### このファイルが解決している問題
> **「フロントエンドに LangGraph の内部スキーマを露出させたくない」**

LangGraph / LangChain は機能追加でイベント名や構造が変わる可能性がある。クライアントとの契約を守るため、この層を噛ませて **プロトコル非依存の内部表現** に翻訳する。

---

## 2. 依存関係

| 依存先 | 役割 |
| --- | --- |
| `dataclasses.dataclass` | 内部イベント `GraphEvent` を frozen/slots で定義 |
| `enum.StrEnum` | イベント種別を文字列値を持つ Enum として定義 |
| `langchain_core.messages.AIMessage` / `HumanMessage` | 入出力ステートの chat_history に積むメッセージ型 |
| `langgraph.types.Command` | `interrupt` への resume 応答コマンドの型 |
| `langgraph.graph.state.CompiledStateGraph` | 実行対象のグラフ型 (TYPE_CHECKING) |
| [src/common/defs/types.py](src/common/defs/types.py) の `NodeName` / `NODE_LABELS` | ノード名と表示ラベルの定義 |
| [src/common/lib/bases.py](src/common/lib/bases.py) の `BaseModel` | Pydantic モデルのプロジェクト共通基底 |

---

## 3. 3 層のイベントモデル（全体像）

このファイルの構造を理解する鍵は **3 つの層** を区別することにある。

```
┌───────────────────────────────────────────────────────────────┐
│ ① LangGraph 生イベント                                         │
│   graph.astream_events(..., version="v2") が返す dict          │
│   {"event": "on_custom_event",                                │
│    "name": "claude_code_token",                                │
│    "data": {"text": "Hel"},                                    │
│    "metadata": {"langgraph_node": "CLAUDE_CODE", ...}}        │
│                                                                │
│   語彙: LangChainEventType                                     │
└───────────────────────┬───────────────────────────────────────┘
                        │ _parse_raw_event
                        │ (イベント種別ごとに分岐)
                        ▼
┌───────────────────────────────────────────────────────────────┐
│ ② GraphEvent (プロジェクト内部表現 — プロトコル非依存)            │
│   GraphEvent(kind=TOKEN, node="CLAUDE_CODE", text="Hel")       │
│                                                                │
│   語彙: GraphEventKind                                          │
└───────────────────────┬───────────────────────────────────────┘
                        │ to_stream_event
                        │ (クライアント契約へ変換)
                        ▼
┌───────────────────────────────────────────────────────────────┐
│ ③ StreamEvent (SSE / A2A 共通のクライアント契約)                 │
│   StreamEvent(type=TOKEN, node="CLAUDE_CODE",                  │
│               label="Claude Code 処理中", content="Hel")       │
│                                                                │
│   語彙: StreamEventType                                         │
└───────────────────────┬───────────────────────────────────────┘
                        │ main.py が SSE 文字列 (data: {...}\n\n) にラップ
                        ▼
                 ブラウザ / A2A クライアント
```

### なぜ 3 層にするのか

| 層 | 安定性 | 変更の影響範囲 |
| --- | --- | --- |
| ① LangGraph 生イベント | LangGraph のバージョン依存 — **不安定** | このファイル内の `_parse_raw_event` に閉じる |
| ② GraphEvent | プロジェクト独自 — **自由に変更可能** | 主にこのファイルと各 `_parse_*` 関数 |
| ③ StreamEvent | クライアント契約 — **破壊変更は NG** | 外部（フロント / A2A 受け手）に波及 |

**中間層 `GraphEvent` を置く効果**:
- 上流 (LangGraph) の変更を `_parse_raw_event` に閉じ込められる
- 下流 (クライアント) の契約を `StreamEvent` として独立に安定させられる
- 同じ内部表現を SSE 用にも A2A 用にも使い回せる

---

## 4. 各層の Enum とデータモデル

### ① `LangChainEventType` (L278〜316)

`langchain_core` の `astream_events` が返すイベント名（`event` フィールドの文字列値）を列挙した Enum。

**なぜプロジェクト側で定義するのか**: LangChain 側が str 型のままで型を提供していないため、タイポや存在しないイベント名を書いてしまうリスクを避けるために自前で Enum 化している。

命名規則: `on_{runnable_type}_{stage}`
- runnable_type: `chain` / `chat_model` / `llm` / `prompt` / `retriever` / `tool`
- stage: `start` / `stream` / `end`（`tool` のみ `error` あり）
- 例外: `on_custom_event` （ユーザー定義イベント）

本プロジェクトで実際に分岐対象にしているのは以下 4 つのみ:
- `ON_CHAIN_START` / `ON_CHAIN_END` — ノード境界とグラフ終了
- `ON_CHAT_MODEL_STREAM` — LLM 直呼び出しの逐次トークン
- `ON_CUSTOM_EVENT` — `adispatch_custom_event` で流した独自イベント

### ② `GraphEventKind` (L135〜155) と `GraphEvent` (L158〜174)

プロジェクト独自の内部イベント語彙と、その 1 件を表す `@dataclass(frozen=True, slots=True)`。

```python
class GraphEventKind(StrEnum):
    NODE_START = "node_start"
    NODE_END = "node_end"
    TOKEN = "token"
    PROGRESS = "progress"
    GRAPH_END = "graph_end"
    INTERRUPT = "interrupt"
```

```python
@dataclass(frozen=True, slots=True)
class GraphEvent:
    kind: GraphEventKind
    node: str = ""
    text: str = ""
    output: dict | None = None
    interrupt_value: Any = None
```

各フィールドがいつセットされるか:

| kind | node | text | output | interrupt_value |
| --- | --- | --- | --- | --- |
| `NODE_START` / `NODE_END` | ノード名 | "" | None | None |
| `TOKEN` | ノード名 | 差分テキスト | None | None |
| `PROGRESS` | ノード名 | 進捗メッセージ | None | None |
| `GRAPH_END` | "" | "" | 最終 state dict | None |
| `INTERRUPT` | タスク名 | "" | None | interrupt() に渡された値 |

**設計上のポイント**: `frozen=True` でイミュータブル、`slots=True` でメモリフットプリント最小化。ストリーミングで大量に生成されるため軽い実装にしている。

### ③ `StreamEventType` (L182〜194) と `StreamEvent` (L197〜215)

クライアントに送り出す最終スキーマ。Pydantic `BaseModel` ベース。

```python
class StreamEventType(StrEnum):
    NODE_START = "node_start"
    NODE_END = "node_end"
    TOKEN = "token"
    PROGRESS = "progress"
    INPUT_REQUIRED = "input_required"
    DONE = "done"


class StreamEvent(BaseModel):
    type: StreamEventType
    node: str | None = None
    label: str | None = None
    content: str | None = None
    metadata: dict | None = None
    session_id: str | None = None
    message: str | None = None
```

### ② と ③ の対応

| GraphEventKind | StreamEventType | 備考 |
| --- | --- | --- |
| `NODE_START` | `NODE_START` | そのまま |
| `NODE_END` | `NODE_END` | そのまま |
| `TOKEN` | `TOKEN` | そのまま |
| `PROGRESS` | `PROGRESS` | そのまま |
| `INTERRUPT` | `INPUT_REQUIRED` | **名前が変わる**（クライアントから見ると「入力を求められている」） |
| `GRAPH_END` | (なし) | クライアントには直接送らず、main.py が `DONE` を別途組み立てる |
| (なし) | `DONE` | main.py が最終メッセージと session_id を詰めて生成 |

この対応は `_KIND_TO_STREAM_TYPE` (L220〜226) の辞書で一元管理されている。

---

## 5. 主要関数の流れ

### `stream_graph_events()` (L417〜443) — エントリポイント

```python
async def stream_graph_events(graph, graph_input, config):
    async for raw_event in graph.astream_events(graph_input, config=config, version="v2"):
        parsed = _parse_raw_event(raw_event)
        if parsed is not None:
            yield parsed

    async for interrupt_event in _yield_interrupt_events(graph, config):
        yield interrupt_event
```

**やっていること**:
1. グラフを `astream_events(version="v2")` で実行し、生イベントを 1 件ずつ `_parse_raw_event` に通す
2. 返ってきた `GraphEvent` (None でなければ) を yield
3. グラフ走行後、**未処理 interrupt があればそれを INTERRUPT イベントとして追加 yield**

**なぜ interrupt を走行後に見るのか**: `interrupt()` は Python の例外ベースで実装されており、`astream_events` の通常イベント列からは直接拾えない。しかし `on_chain_end` (= GRAPH_END) は interrupt でも発火する。そのため走行完了後に `graph.aget_state(config)` で確認して interrupt の有無を判定する（L439〜441 のコメント参照）。

### `_parse_raw_event()` (L359〜393) — 翻訳の心臓部

生イベント → `GraphEvent` の変換本体。4 本の分岐で構成される。

```python
name: str = event.get("name", "")
metadata: _EventMetadata = event.get("metadata", {})
event_type: LangChainEventType = event["event"]

is_node_event = name in NODE_NAMES and metadata.get("langgraph_node") == name
```

#### 分岐 1: ノード境界イベント

```python
if is_node_event and event_type in (LangChainEventType.ON_CHAIN_START, LangChainEventType.ON_CHAIN_END):
    kind = GraphEventKind.NODE_START if event_type == LangChainEventType.ON_CHAIN_START else GraphEventKind.NODE_END
    return GraphEvent(kind=kind, node=name)
```

- `name` が `NodeName` Enum の値であり、かつ `metadata.langgraph_node == name` の場合のみノードイベントとして扱う
- この二重チェックの理由: LangGraph は内部で多重に `on_chain_start` / `on_chain_end` を発火させる（ノード外の runnable にも発火）。**純粋なノード単位のイベントだけ** に絞り込むために両方の条件を使う

#### 分岐 2: LLM トークン

```python
if event_type == LangChainEventType.ON_CHAT_MODEL_STREAM:
    text = extract_text(event["data"]["chunk"].content)
    if text:
        node = metadata.get("langgraph_node", "")
        return GraphEvent(kind=GraphEventKind.TOKEN, node=node, text=text)
    return None
```

- LangChain の Chat Model を直接 `astream` で呼ぶタイプのノード（本プロジェクトでは現状使っていない）が流すトークンを拾う
- Claude Code ノード（CLI / SDK 両方）は **この経路を使わない**。`adispatch_custom_event` 経由の `ON_CUSTOM_EVENT` 側で拾っている

#### 分岐 3: グラフ全体の終了

```python
if event_type == LangChainEventType.ON_CHAIN_END and name == "LangGraph":
    return GraphEvent(kind=GraphEventKind.GRAPH_END, output=event["data"].get("output"))
```

- `name == "LangGraph"` の `on_chain_end` は **グラフ全体の終了**（個々のノード終了とは別）
- `output` には最終的な state dict が入っている。API 側はここから `chat_history` を取り出して最終回答を抽出する（`extract_final_answer`）

#### 分岐 4: カスタムイベント

```python
if event_type == LangChainEventType.ON_CUSTOM_EVENT:
    return _parse_custom_event(name, event.get("data", {}), metadata.get("langgraph_node", ""))
```

- `adispatch_custom_event` で流されたものを `_parse_custom_event` に委譲
- **Claude Code ノードの TOKEN / PROGRESS はここから来る**

上記いずれにも該当しないイベント（`on_chain_start/end` のノード外イベント、`on_tool_*`、`on_prompt_*` など）は `None` を返し、結果として捨てられる。

### `_parse_custom_event()` (L341〜356) — ノードとの接続点

```python
_CUSTOM_EVENT_PARSERS: dict[str, GraphEventKind] = {
    CLAUDE_CODE_TOKEN_EVENT: GraphEventKind.TOKEN,
    CLAUDE_CODE_PROGRESS_EVENT: GraphEventKind.PROGRESS,
}

_CUSTOM_EVENT_TEXT_KEYS: dict[GraphEventKind, str] = {
    GraphEventKind.TOKEN: "text",
    GraphEventKind.PROGRESS: "message",
}


def _parse_custom_event(name: str, data: dict, node: str) -> GraphEvent | None:
    kind = _CUSTOM_EVENT_PARSERS.get(name)
    if kind is None:
        return None
    text_key = _CUSTOM_EVENT_TEXT_KEYS.get(kind, "text")
    return GraphEvent(kind=kind, node=node, text=data.get(text_key, ""))
```

**2 つの辞書による二段階マッピング**:
1. **カスタムイベント名 → GraphEventKind**: `"claude_code_token"` → `TOKEN`
2. **GraphEventKind → data 内のテキストキー名**: `TOKEN` → `"text"` / `PROGRESS` → `"message"`

これがノード側との「契約」を 1 箇所に集約している部分。新しいカスタムイベントを追加したいときも、この 2 つの辞書にエントリを足すだけで済む。

### `to_stream_event()` (L237〜270) — 外部契約への変換

```python
def to_stream_event(
    ev: GraphEvent,
    *,
    include_node_progress: bool | frozenset[str] = True,
) -> StreamEvent | None:
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
```

**3 段の処理**:

1. **ノード進捗フィルタ** (L256〜260):
   `include_node_progress` で `NODE_START` / `NODE_END` の送信可否を制御。
   - `True` → 全ノード送信
   - `False` → 全ノード抑制
   - `frozenset[str]` → 指定ノードのみ送信

2. **GRAPH_END を除外** (L261〜263):
   `_KIND_TO_STREAM_TYPE` に `GRAPH_END` は含まれていないため `None` が返り、捨てられる。最終結果は main.py 側で別途 `DONE` イベントに組み立てる。

3. **StreamEvent 構築** (L264〜270):
   - `label`: `NODE_LABELS`（[types.py](src/common/defs/types.py)）で **ノード名 → 表示用日本語ラベル** に変換
   - `content`: TOKEN / PROGRESS のテキスト本文
   - `metadata`: INTERRUPT の場合のみ `interrupt_value` を詰める

### `_yield_interrupt_events()` (L396〜414) — 一時停止の検知

```python
async def _yield_interrupt_events(graph, config):
    state = await graph.aget_state(config)
    if state.tasks:
        for task in state.tasks:
            for intr in task.interrupts:
                yield GraphEvent(
                    kind=GraphEventKind.INTERRUPT,
                    node=task.name,
                    interrupt_value=intr.value,
                )
```

- `graph.aget_state(config)` で現在のグラフ state を読む
- 各 task の `interrupts` リストを走査して INTERRUPT イベントを yield
- **正常完了時は `state.tasks` が空 or interrupts が空なので何も yield しない**（冪等）

---

## 6. 補助関数

本体のストリーミング処理以外に、state 操作系のヘルパーも同居している。

### `extract_text()` (L37〜50)

`AIMessageChunk.content` が `str` で来る場合と `list[dict]` で来る場合の両対応。後者は Anthropic / Claude 系モデルのマルチパート content 形式。

### `extract_final_answer()` (L53〜68)

グラフの最終 state から **最後の AIMessage** を取り出してテキスト化。SSE の DONE イベントや非ストリーミングレスポンスで使う。

### `build_graph_input()` (L71〜85)

```python
return {
    "last_user_message": message,
    "chat_history": [HumanMessage(content=message)],
}
```

State の初期構築。`chat_history` に `add_messages` reducer が効くため、ここで積んだ `HumanMessage` はノードの返す `AIMessage` と一緒に末尾追記される。

### `build_graph_config()` (L88〜97)

```python
return {"configurable": {"thread_id": thread_id}}
```

LangGraph の `configurable` dict を作る。**`thread_id` は Claude Code の session_id も兼ねる**（今回の設計では main.py が UUID を 1 つ生成して両方に流す）。

### `has_pending_interrupt()` (L104〜115)

グラフ state に未処理 interrupt が残っているかを真偽値で返す。A2A エグゼキュータが `resume` すべきか `新規実行` すべきかを判断するのに使う。

### `build_resume_input()` (L118〜127)

interrupt に対するユーザー応答を `Command(resume=...)` に変換する。承認語彙（`yes`, `はい`, `ok`, `approve`, `承認`）に含まれるかで `approved` を True/False にする。

---

## 7. `claude_code.py` / `claude_code_sdk.py` との関係

### 両者を結ぶ唯一の契約: 共有定数

stream.py の L33-34 で定義される 2 つの文字列定数が、ノードとストリーム変換層を結ぶ **唯一のインターフェース** になっている。

```python
CLAUDE_CODE_TOKEN_EVENT = "claude_code_token"
CLAUDE_CODE_PROGRESS_EVENT = "claude_code_progress"
```

両方ともノード側 ([_claude_code_shared.py](src/application/nodes/_claude_code_shared.py)) が import して使う。契約は:

| イベント名 | data キー | 意味 |
| --- | --- | --- |
| `CLAUDE_CODE_TOKEN_EVENT` | `"text"` | 生成テキストの差分 |
| `CLAUDE_CODE_PROGRESS_EVENT` | `"message"` | 進捗メッセージ |

### 発行→受信の完全フロー

Claude Code ノードが 1 つのトークンを流した場合の、ファイル間を跨ぐ経路:

```
[claude_code.py / claude_code_sdk.py]
  ↓ ノードが呼ぶ
dispatch_token("Hel", config)
  ↓ (_claude_code_shared.py)
adispatch_custom_event("claude_code_token", {"text": "Hel"}, config=config)
  ↓ LangChain のコールバック機構
  ↓ LangGraph が metadata.langgraph_node = "CLAUDE_CODE" を自動注入
[stream.py]
  ↓ astream_events が生イベントとして出力
  {"event": "on_custom_event",
   "name": "claude_code_token",
   "data": {"text": "Hel"},
   "metadata": {"langgraph_node": "CLAUDE_CODE"}}
  ↓ _parse_raw_event が ON_CUSTOM_EVENT 分岐に入る
  ↓
_parse_custom_event("claude_code_token", {"text": "Hel"}, "CLAUDE_CODE")
  ↓ _CUSTOM_EVENT_PARSERS["claude_code_token"] → TOKEN
  ↓ _CUSTOM_EVENT_TEXT_KEYS[TOKEN] → "text"
GraphEvent(kind=TOKEN, node="CLAUDE_CODE", text="Hel")
  ↓ stream_graph_events が yield
[main.py]
  ↓ to_stream_event(ev)
StreamEvent(type=TOKEN, node="CLAUDE_CODE", label="Claude Code 処理中", content="Hel")
  ↓ _sse_line で SSE 形式にラップ
data: {"type":"token","node":"CLAUDE_CODE","label":"Claude Code 処理中","content":"Hel"}\n\n
  ↓ StreamingResponse
[ブラウザ]
```

### CLI / SDK 切替がなぜ成立するか

CLI 版 ([claude_code.py](src/application/nodes/claude_code.py)) と SDK 版 ([claude_code_sdk.py](src/application/nodes/claude_code_sdk.py)) は、**同じ共有定数と同じデータキー** で dispatch している。

そのため stream.py から見ると **どちらのノード実装か区別がつかないし、区別する必要もない**。これが main.py の辞書 1 個だけで実装切替を成立させている設計上の基盤。

```python
# 共通部分 (_claude_code_shared.py)
async def dispatch_token(delta: str, config: RunnableConfig) -> None:
    await adispatch_custom_event(CLAUDE_CODE_TOKEN_EVENT, {"text": delta}, config=config)
```

CLI 版と SDK 版のノードはどちらもこの関数を呼ぶだけ。ソースイベントが CLI の stream-json であろうと SDK の `content_block_delta` であろうと、**この関数に入った時点で差異は消える**。

---

## 8. データの具体例

### 例 1: Claude Code がトークン "Hel" を生成

**① LangGraph 生イベント**:
```python
{
    "event": "on_custom_event",
    "name": "claude_code_token",
    "data": {"text": "Hel"},
    "metadata": {"langgraph_node": "CLAUDE_CODE", ...},
    "run_id": "...",
    "tags": [...],
}
```

**② GraphEvent**:
```python
GraphEvent(kind=GraphEventKind.TOKEN, node="CLAUDE_CODE", text="Hel")
```

**③ StreamEvent**:
```python
StreamEvent(
    type=StreamEventType.TOKEN,
    node="CLAUDE_CODE",
    label="Claude Code 処理中",
    content="Hel",
)
```

**SSE 行（main.py で組み立て）**:
```
data: {"type":"token","node":"CLAUDE_CODE","label":"Claude Code 処理中","content":"Hel"}

```

### 例 2: ノードが interrupt で一時停止

**① 最初は通常の生イベントとして何も来ない**（例外ベースなので `astream_events` では拾えない）

**② `_yield_interrupt_events` で検知**:
```python
GraphEvent(
    kind=GraphEventKind.INTERRUPT,
    node="APPROVAL_NODE",
    interrupt_value={"question": "この変更を承認しますか？"},
)
```

**③ StreamEvent**:
```python
StreamEvent(
    type=StreamEventType.INPUT_REQUIRED,  # ← 名前が変わる
    node="APPROVAL_NODE",
    label="承認待ち",
    metadata={"question": "この変更を承認しますか？"},
)
```

### 例 3: グラフ終了（GRAPH_END）

**① LangGraph 生イベント**:
```python
{
    "event": "on_chain_end",
    "name": "LangGraph",
    "data": {"output": {"last_user_message": "...", "chat_history": [...]}},
    ...
}
```

**② GraphEvent**:
```python
GraphEvent(kind=GraphEventKind.GRAPH_END, output={"chat_history": [...], ...})
```

**③ StreamEvent**: **生成されない**（`_KIND_TO_STREAM_TYPE` に `GRAPH_END` がないため `to_stream_event` が `None` を返す）

**代わりに main.py が DONE を組み立てる**:
```python
final_message = extract_final_answer(ev.output)
yield _sse_line(StreamEvent(type=DONE, session_id=session_id, message=final_message))
```

---

## 9. 設計上のポイント

### なぜ 3 層か — まとめ
- **① LangGraph 生イベント**: ライブラリ由来、不安定。`_parse_raw_event` 内に封じ込め
- **② GraphEvent**: プロジェクト独自、自由に進化可能。「内部モデル」
- **③ StreamEvent**: 外部契約、破壊変更 NG。「公開 API」

この切り分けにより、上流 (LangGraph) / 下流 (クライアント) のどちらか片側の変化が他方に波及しない。

### なぜカスタムイベント経由にするのか
- Claude Code ノードの生成源は **サブプロセスの JSONL** や **SDK の async iterator** で、LangChain の LLM 直接呼び出しとは構造が違う
- `adispatch_custom_event` で統一すれば、LangChain が本来サポートしないイベント源も **`astream_events` の同じ口から流れてくる** ようにできる
- 結果、このファイル (stream.py) は「ノード内部の事情」を知らずに済む

### なぜ interrupt を別経路で検知するか
- LangGraph の `interrupt()` は例外ベースで、通常の `astream_events` では `NODE_END` の前に例外で中断される
- しかし `on_chain_end` (= GRAPH_END) 自体は発火する
- そのため「グラフ走行完了後にステートを確認」するのが確実。L439〜441 のコメントで明記されている

### SRP / 疎結合の観点
| モジュール | 知っていること | 知らないこと |
| --- | --- | --- |
| claude_code.py / claude_code_sdk.py | 共有定数 (`CLAUDE_CODE_*_EVENT`)、data キー規約 | SSE プロトコル、StreamEvent の形 |
| stream.py | LangGraph の生イベント形、GraphEvent、StreamEvent | Claude Code のソース（CLI/SDK/何か）、SSE フォーマット |
| main.py | StreamEvent、SSE フォーマット、session_id 発行 | LangGraph の生イベント形、ノードの実装 |

**それぞれが 1 つ隣の層とだけ話す構造**になっている。

---

## 10. 拡張するときのポイント

### 新しいカスタムイベントを追加したい
1. 定数をこのファイルに追加: `FOO_EVENT = "foo"`
2. `_CUSTOM_EVENT_PARSERS` に `FOO_EVENT: GraphEventKind.XXX` を追加
3. 必要なら `_CUSTOM_EVENT_TEXT_KEYS[GraphEventKind.XXX] = "key_name"` を追加
4. ノード側で `await adispatch_custom_event(FOO_EVENT, {"key_name": "..."}, config=config)` を呼ぶ

### 新しい StreamEventType を追加したい
1. `StreamEventType` に Enum 値を追加
2. `GraphEventKind` にも対応する kind を追加（必要なら）
3. `_KIND_TO_STREAM_TYPE` に対応エントリを追加

### 別プロトコル（WebSocket など）を追加したい
- `StreamEvent` は変えずに、main.py の `_sse_line` に相当する **プロトコル側ラッパー** だけ書けばよい
- `stream.py` 本体は無改修で流用できる（これがこの設計の最大の恩恵）

### LangGraph のバージョンアップで破壊変更があった
- 影響範囲は `_parse_raw_event` と `LangChainEventType` に限定される
- `GraphEvent` / `StreamEvent` を触る必要はない（= ノードやクライアントは無影響）

---

## 11. 関連ファイル

| ファイル | 関係 |
| --- | --- |
| [src/application/nodes/claude_code.py](src/application/nodes/claude_code.py) | CLI 版ノード。`adispatch_custom_event` でイベントを流す |
| [src/application/nodes/claude_code_sdk.py](src/application/nodes/claude_code_sdk.py) | SDK 版ノード。同上 |
| [src/application/nodes/_claude_code_shared.py](src/application/nodes/_claude_code_shared.py) | `dispatch_token` / `dispatch_progress` の実体。stream.py の定数を参照 |
| [src/application/states.py](src/application/states.py) | `State` TypedDict。`chat_history` の `add_messages` reducer |
| [src/application/workflows/claude_code.py](src/application/workflows/claude_code.py) | グラフの組み立て |
| [src/main.py](src/main.py) | FastAPI エンドポイント。`stream_graph_events` → `to_stream_event` → SSE 文字列の最終組み立て |
| [src/a2a_app/executor.py](src/a2a_app/executor.py) | A2A 側エグゼキュータ。同じ `stream_graph_events` を使う |
| [src/common/defs/types.py](src/common/defs/types.py) | `NodeName` Enum と `NODE_LABELS` マップ |

---

## 12. 一言まとめ

> **stream.py は「LangGraph の雑多な生イベント」を「クライアントが安心して受け取れる StreamEvent」に翻訳する 3 段変換器**。

中間に置いた `GraphEvent` という独自語彙が、上流 (LangGraph) と下流 (クライアント/別プロトコル) の変化を互いに隔離する。ノード (CLI/SDK 問わず) とは **2 つの共有定数だけ** で契約しており、ノード実装の切替も、配信プロトコルの追加も、このファイルに一切手を入れずに可能。
