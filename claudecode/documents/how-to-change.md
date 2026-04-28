# 変更ガイド（逆引きリファレンス）

ストリーミング仕様やイベント構造を変更したい場合のガイド。
やりたいことから逆引きで該当箇所を特定できるようにしている。

---

## 目次

- [レスポンス仕様を変えたい](#レスポンス仕様を変えたい)
  - [クライアントへ返す JSON のフィールドを追加・変更したい](#クライアントへ返す-json-のフィールドを追加変更したい)
  - [イベントの種別 (type) を追加したい](#イベントの種別-type-を追加したい)
  - [ノード進捗イベント (node_start / node_end) を返す／返さないを切り替えたい](#ノード進捗イベント-node_start--node_end-を返す返さないを切り替えたい)
  - [トークンの内容を加工してから返したい](#トークンの内容を加工してから返したい)
- [ノードを変えたい](#ノードを変えたい)
  - [ノードを追加したい](#ノードを追加したい)
  - [ノードの表示ラベルを変えたい](#ノードの表示ラベルを変えたい)
  - [特定のノードだけトークンを返したくない](#特定のノードだけトークンを返したくない)
- [プロトコル固有の変更をしたい](#プロトコル固有の変更をしたい)
  - [SSE 側だけ挙動を変えたい](#sse-側だけ挙動を変えたい)
  - [A2A 側だけ挙動を変えたい](#a2a-側だけ挙動を変えたい)
  - [A2A のストリーミング／非ストリーミングの分岐条件を変えたい](#a2a-のストリーミング非ストリーミングの分岐条件を変えたい)
- [内部イベントの構造を変えたい](#内部イベントの構造を変えたい)
  - [LangGraph のイベントから新しい情報を取り出したい](#langgraph-のイベントから新しい情報を取り出したい)
  - [GraphEvent → StreamEvent のマッピングを変えたい](#graphevent--streamevent-のマッピングを変えたい)

---

## レスポンス仕様を変えたい

### クライアントへ返す JSON のフィールドを追加・変更したい

クライアントに返るイベント JSON は `StreamEvent` で定義されている。

**変更対象:**
- `src/application/stream.py` — `StreamEvent` クラスにフィールドを追加
- `src/application/stream.py` — `to_stream_event()` で新フィールドの値をセット

**例: `timestamp` フィールドを追加する場合:**

```python
# stream.py - StreamEvent
class StreamEvent(BaseModel):
    type: StreamEventType
    node: str | None = None
    label: str | None = None
    content: str | None = None
    timestamp: float | None = None   # 追加
    ...

# stream.py - to_stream_event()
import time
def to_stream_event(ev: GraphEvent, ...) -> StreamEvent | None:
    ...
    return StreamEvent(
        type=stream_type,
        ...,
        timestamp=time.time(),   # 追加
    )
```

`to_stream_event()` は SSE / A2A 両方から呼ばれるため、1 箇所の変更で両プロトコルに反映される。

---

### イベントの種別 (type) を追加したい

例えば `error` イベントを新設する場合。

**変更対象:**
1. `src/application/stream.py` — `GraphEventKind` に新しい種別を追加
2. `src/application/stream.py` — `StreamEventType` に対応する種別を追加
3. `src/application/stream.py` — `_KIND_TO_STREAM_TYPE` マッピングテーブルに対応を追加
4. `src/application/stream.py` — `_parse_raw_event()` で新種別の `GraphEvent` を返す条件を追加

**注意:** `_KIND_TO_STREAM_TYPE` に含まれない `GraphEventKind` は `to_stream_event()` が `None` を返し、クライアントには送信されない。内部用イベント（`GRAPH_END` のように）はマッピングに含めない。

---

### ノード進捗イベント (node_start / node_end) を返す／返さないを切り替えたい

`to_stream_event()` の `include_node_progress` パラメータで制御する。
3 パターンの指定が可能:

| 値 | 挙動 |
|----|------|
| `True` (デフォルト) | 全ノードの進捗を送信 |
| `False` | 全ノードの進捗を抑制 |
| `frozenset({"SAMPLE"})` | 指定したノード名のみ送信、それ以外は抑制 |

**全ノードの進捗を無効化:**
```python
# SSE 側
_stream_graph(graph, graph_input, config, session_id, include_node_progress=False)

# A2A 側
await self._execute_stream(..., tc=tc, include_node_progress=False)
```

**特定ノードだけ進捗を送信:**
```python
# SAMPLE_STREAM だけ node_start / node_end を送信し、SAMPLE は抑制
_stream_graph(..., include_node_progress=frozenset({"SAMPLE_STREAM"}))
```

**特定ノードだけ進捗を抑制 (それ以外は送信):**
```python
# NODE_NAMES から除外したいノードを引く
from src.application.stream import NODE_NAMES
_stream_graph(..., include_node_progress=frozenset(NODE_NAMES - {"SAMPLE"}))
```

**両方まとめて変えたい場合:**

`to_stream_event()` の `include_node_progress` のデフォルト値を変更すれば、SSE / A2A 両方で一括適用できる。

---

### トークンの内容を加工してから返したい

**変更対象:**
- `src/application/stream.py` — `to_stream_event()` 内で `ev.text` を加工

```python
def to_stream_event(ev: GraphEvent, ...) -> StreamEvent | None:
    ...
    content = ev.text or None
    if content and ev.node == "SOME_NODE":
        content = content.strip()  # 加工例
    return StreamEvent(
        type=stream_type,
        ...,
        content=content,
    )
```

---

## ノードを変えたい

### ノードを追加したい

以下の箇所を順に更新する。

| # | ファイル | 変更内容 |
|---|---------|---------|
| 1 | `src/common/defs/types.py` | `NodeName` に新ノード名を追加 |
| 2 | `src/common/defs/types.py` | `NODE_LABELS` に表示ラベルを追加 |
| 3 | `src/application/nodes/` | ノード関数を新規作成 |
| 4 | `src/application/workflows/main.py` | `_add_nodes` でノードを追加、`_add_edges` でエッジを定義 |
| 5 | `config/app.yaml` | 新ノード用の設定を追加（LLM を使う場合） |

ストリーミング側は `NodeName` に追加するだけで自動的に `NODE_NAMES` に含まれ、`node_start` / `node_end` / `token` イベントが配信される。

---

### ノードの表示ラベルを変えたい

**変更対象:**
- `src/common/defs/types.py` — `NODE_LABELS` の値を変更

```python
NODE_LABELS: dict[str, str] = {
    NodeName.SAMPLE: "分析中",           # ← ここを変更
    NodeName.SAMPLE_STREAM: "回答生成中",
}
```

`to_stream_event()` が `NODE_LABELS` を参照して `StreamEvent.label` に自動付与するため、この 1 箇所の変更で SSE / A2A 両方に反映される。

---

### 特定のノードだけトークンを返したくない

**変更対象:**
- `src/application/stream.py` — `to_stream_event()` にフィルタ条件を追加

```python
# 例: SAMPLE ノードのトークンを除外
_SILENT_NODES: frozenset[str] = frozenset({"SAMPLE"})

def to_stream_event(ev: GraphEvent, ...) -> StreamEvent | None:
    ...
    if ev.kind == GraphEventKind.TOKEN and ev.node in _SILENT_NODES:
        return None
    ...
```

---

## プロトコル固有の変更をしたい

### SSE 側だけ挙動を変えたい

**変更対象:**
- `src/main.py` — `_stream_graph()` 内のイベント処理

`to_stream_event()` が返す `StreamEvent` を `_sse_line()` で SSE フォーマットに変換している。
SSE 固有のフィルタや加工はこの関数内で行う。

```python
async for ev in stream_graph_events(graph, graph_input, config):
    se = to_stream_event(ev, include_node_progress=include_node_progress)
    if se is not None:
        # ここで SSE 固有のフィルタ・加工が可能
        yield _sse_line(se)
```

---

### A2A 側だけ挙動を変えたい

**変更対象:**
- `src/a2a_app/executor.py` — `_execute_stream()` 内のイベント処理

```python
async for ev in stream_graph_events(self._get_graph(), graph_input, config):
    se = to_stream_event(ev, include_node_progress=include_node_progress)
    if se is not None:
        # ここで A2A 固有のフィルタ・加工が可能
        await tc.event_queue.enqueue_event(
            _working_event(se.model_dump_json(exclude_none=True), tc.task_id, tc.context_id)
        )
```

---

### A2A のストリーミング／非ストリーミングについて

Executor は常に `_execute_stream` でストリーミング実行し、全イベントを `EventQueue` に送信する。
ストリーミング (`message/stream`) と非ストリーミング (`message/send`) の振り分けは A2A フレームワークが自動的に行うため、
Executor 側で分岐する必要はない。

---

## 内部イベントの構造を変えたい

### LangGraph のイベントから新しい情報を取り出したい

**変更対象:**
1. `src/application/stream.py` — `GraphEvent` にフィールドを追加
2. `src/application/stream.py` — `_parse_raw_event()` で新フィールドを取得・セット
3. 必要に応じて `_EventMetadata` に新しいキーを追加

```python
# 例: 実行ステップ番号を取り出す
class _EventMetadata(TypedDict, total=False):
    langgraph_node: str
    langgraph_step: int   # 追加

@dataclass(frozen=True, slots=True)
class GraphEvent:
    kind: GraphEventKind
    node: str = ""
    text: str = ""
    step: int = 0         # 追加
    output: dict | None = None
```

---

### GraphEvent → StreamEvent のマッピングを変えたい

**変更対象:**
- `src/application/stream.py` — `_KIND_TO_STREAM_TYPE` および `to_stream_event()`

`_KIND_TO_STREAM_TYPE` はマッピングテーブル:

```python
_KIND_TO_STREAM_TYPE: dict[GraphEventKind, StreamEventType] = {
    GraphEventKind.NODE_START: StreamEventType.NODE_START,
    GraphEventKind.NODE_END: StreamEventType.NODE_END,
    GraphEventKind.TOKEN: StreamEventType.TOKEN,
}
```

- エントリを削除 → そのイベントはクライアントに送信されなくなる
- エントリを追加 → 新しいマッピングが有効になる
- `to_stream_event()` 内のフィールド設定ロジックを変更 → 変換内容をカスタマイズ

---

## 変更の影響範囲チェックリスト

変更後に確認すべきポイント:

- [ ] `python -m pytest tests/` が通るか
- [ ] SSE (`POST /test?stream=true`) でイベントが期待通り届くか
- [ ] A2A (`message/stream`) でイベントが期待通り届くか
- [ ] A2A (`message/send`) で最終結果が正しく返るか
- [ ] クラス図ドキュメント (`documents/class-diagram.md`) の更新が必要か
