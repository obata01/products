# references コード修正ガイド

`references/` 配下のフロントエンド実装コードについて、
バックエンド側の仕様変更に伴い修正が必要な箇所をまとめる。

---

## 変更の背景

1. **CONFIRM ノードの追加** — ワークフローに `interrupt()` によるユーザー確認フローが追加された
2. **`input_required` イベントの追加** — `StreamEventType` / `GraphEventKind` に新しい種別が追加された
3. **ワークフロー変更** — `SAMPLE → CONFIRM → SAMPLE_STREAM` の 3 段構成になった

---

## 修正対象ファイル一覧

| # | ファイル | 修正内容 | 重要度 |
|---|---------|---------|--------|
| 1 | `references/pages/api_stream.py` | `input_required` イベントの処理追加 | **必須** |
| 2 | `references/pages/a2a_stream.py` | `input_required` ステートの処理追加 | **必須** |
| 3 | `references/chat_utils.py` | 確認待ち UI / resume フローの対応 | **必須** |

---

## 1. `references/pages/api_stream.py`

### 1-1. `_events_to_chunks`: `input_required` イベントの処理が未実装

**現状:** `node_start` と `token` のみ処理しており、`input_required` イベントを無視する。

**影響:** CONFIRM ノードで `interrupt()` が発火すると、フロントエンドは確認 UI を表示せずにストリームが終了する。ユーザーは応答を返す手段がなく、ワークフローが中断したまま放置される。

**修正方針:** `input_required` イベントを受信したら、確認に必要な情報 (metadata) をフロントエンドに伝搬する。新しい `ChunkType` を追加するか、専用のコールバック / 例外で通知する。

```python
# 修正例: _events_to_chunks に input_required の処理を追加
for event in events:
    if event.type == SSEEventType.NODE_START:
        # ... (既存のまま)

    elif event.type == SSEEventType.TOKEN:
        # ... (既存のまま)

    elif event.type == SSEEventType.INPUT_REQUIRED:
        # metadata に確認メッセージとプレビューが含まれる
        yield ChunkType.INPUT_REQUIRED, json.dumps(event.metadata or {})
```

### 1-2. `SSEEventType` に `INPUT_REQUIRED` が未定義

**現状:** `SSEEventType` (および `SSEEvent`) は `references/` から参照されているが定義が存在しない。
いずれにせよ定義時に `input_required` を含める必要がある。

**修正方針:** `SSEEventType` の定義に `INPUT_REQUIRED = "input_required"` を追加する。
`SSEEvent` モデルに `metadata: dict | None = None` フィールドを追加する。

### 1-3. `_stream_sse`: resume (再リクエスト) のフローが未実装

**現状:** `_stream_sse` は 1 回のリクエスト → ストリーム読み取り → 終了 の直列処理。
`input_required` を受けて同じ `session_id` で再リクエストする仕組みがない。

**修正方針:** `_stream_sse` またはその呼び出し元で、`input_required` を受信した場合にユーザー入力を待ち、同じ `session_id` で再リクエストするループを実装する。

---

## 2. `references/pages/a2a_stream.py`

### 2-1. `_stream_template_chunks`: `input_required` ステートの処理が未実装

**現状:** `TaskState.working` と `TaskArtifactUpdateEvent` のみ処理。
`TaskState.input_required` を受信した場合の分岐がない。

**影響:** A2A の `input_required` ステートを受信しても無視される。

**修正方針:** `TaskStatusUpdateEvent` で `status.state == TaskState.input_required` のケースを追加する。

```python
# 修正例: match 文に input_required のケースを追加
case (_, TaskStatusUpdateEvent() as ev) if (
    ev.status.state == TaskState.input_required
):
    yield ChunkType.INPUT_REQUIRED, "ユーザーの確認を待っています。"
```

### 2-2. `_stream_a2a`: resume フローが未実装

**現状:** 1 回のリクエスト → ストリーム読み取り → 終了 の直列処理。

**修正方針:** `ChunkType.INPUT_REQUIRED` チャンクを受信した場合に、
ユーザーの応答を待ってから同じ接続先に再度メッセージを送信するフローを実装する。

### 2-3. `_stream_template_chunks` 内の thinking の扱い

**現状 (影響度: 低):**
```python
case (_, TaskStatusUpdateEvent() as ev) if (
    ev.status.state == TaskState.working and ev.status.message
):
```
A2A の `working` イベントの `status.message` 内 JSON に `input_required` 型の StreamEvent が含まれうるようになった。
ただし CONFIRM ノードは LLM トークンを出力しないため、実際には `input_required` の StreamEvent が `working` イベントとして配信される可能性がある。

**修正方針:** `working` イベント内の StreamEvent JSON をパースし、`type` が `input_required` の場合は thinking ではなく確認待ちとして処理することを検討する。

---

## 3. `references/chat_utils.py`

### 3-1. `ChunkType` に `INPUT_REQUIRED` が未定義

**現状:** `ChunkType` は `THINKING`, `ANSWER_START`, `ANSWER` の 3 種。

**修正方針:** `INPUT_REQUIRED` を追加する。

```python
class ChunkType(StrEnum):
    THINKING = "thinking"
    ANSWER_START = "answer_start"
    ANSWER = "answer"
    INPUT_REQUIRED = "input_required"
```

### 3-2. `StreamingChatPage._write_stream`: `INPUT_REQUIRED` チャンクの処理が未実装

**現状:** `THINKING`, `ANSWER_START`, `ANSWER` の 3 種のみ処理。

**修正方針:** `INPUT_REQUIRED` チャンクを受信した場合に:
1. 現在のストリーム表示を一旦確定する
2. 確認 UI (ボタン等) を表示する
3. ユーザーの選択を待つ

```python
# 修正例: _write_stream 内
elif chunk_type == ChunkType.INPUT_REQUIRED:
    # metadata をパースして確認 UI を表示
    metadata = json.loads(chunk_text) if chunk_text else {}
    # ... 確認ダイアログの表示と応答取得
```

### 3-3. `StreamingChatPage.run`: 確認 → 再リクエストのループが未実装

**現状:** `run()` は 1 回のユーザー入力 → 1 回のストリーミング表示で完結する。
`input_required` 後の再リクエストフローがない。

**修正方針:** 以下のいずれかのパターンで対応する。

**パターン A: セッションステートで状態管理**
```
Streamlit のセッションステートに「確認待ち」フラグを持ち、
ページ再描画時に確認 UI → 再リクエストのフローを実行する。
```

**パターン B: stream_fn の責務を拡張**
```
stream_fn 内で input_required を検知した場合に、
コールバック経由でユーザー応答を取得し、再リクエストまで行う。
stream_fn が 2 回のリクエスト分のチャンクを yield する。
```

---

## 修正の優先順位

1. **`ChunkType` に `INPUT_REQUIRED` を追加** — 全コンポーネントの前提
2. **`SSEEvent` / `SSEEventType` に `input_required` と `metadata` を追加** — SSE パースの前提
3. **`api_stream.py` の `_events_to_chunks`** — `input_required` イベントの検知
4. **`a2a_stream.py` の `_stream_template_chunks`** — `input_required` ステートの検知
5. **`chat_utils.py` の `_write_stream` / `run`** — 確認 UI と再リクエストのフロー実装

---

## 参考: 現在の SSE イベント種別一覧

| type | 説明 | 備考 |
|------|------|------|
| `node_start` | ノード処理開始 | 既存 (対応済み) |
| `node_end` | ノード処理完了 | 既存 (未処理だが影響なし) |
| `token` | LLM トークン出力 | 既存 (対応済み) |
| `input_required` | ユーザー確認待ち | **新規 (要対応)** |
| `done` | ストリーム完了 | 既存 (未処理だが影響なし) |

## 参考: `input_required` イベントのフォーマット

```json
{
  "type": "input_required",
  "metadata": {
    "message": "この内容で回答を生成してよろしいですか？",
    "preview": "SAMPLE ノードの分析結果テキスト"
  }
}
```

詳細は [confirm-flow-guide.md](confirm-flow-guide.md) を参照。
