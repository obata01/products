# API インターフェース仕様

HTTP API (SSE) のリクエスト・レスポンス仕様。

---

## エンドポイント一覧

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/health` | ヘルスチェック |
| POST | `/test` | チャット (JSON / SSE) |

---

## GET /health

### レスポンス

```json
{"status": "ok"}
```

---

## POST /test

### リクエスト

Content-Type: `application/json`

```json
{
  "session_id": "string (必須)",
  "message": "string (必須)",
  "stream": false
}
```

| フィールド | 型 | デフォルト | 説明 |
|-----------|-----|----------|------|
| `session_id` | string | — | セッションを一意に識別する ID。同一 ID で会話を継続できる。 |
| `message` | string | — | ユーザーからの入力メッセージ。 |
| `stream` | boolean | `false` | `true` で SSE ストリーミング、`false` で JSON レスポンス。 |

---

### レスポンス: 非ストリーミング (`stream=false`)

Content-Type: `application/json`

```json
{
  "session_id": "abc123",
  "message": "最終回答テキスト"
}
```

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `session_id` | string | リクエストと対応するセッション ID。 |
| `message` | string | アシスタントからの返答メッセージ。 |

#### エラーレスポンス (500)

```json
{
  "message": "リクエストの処理中にエラーが発生しました。"
}
```

---

### レスポンス: ストリーミング (`stream=true`)

Content-Type: `text/event-stream`

SSE 形式で `StreamEvent` JSON が逐次配信される。各イベントは `data: ` プレフィクス付き。

```
data: {"type":"node_start","node":"SAMPLE","label":"分析中"}

data: {"type":"token","node":"SAMPLE","label":"分析中","content":"{\"message"}

data: {"type":"token","node":"SAMPLE","label":"分析中","content":"{\"message\":\"...\"}"}

data: {"type":"node_end","node":"SAMPLE","label":"分析中"}

data: {"type":"node_start","node":"SAMPLE_STREAM","label":"回答生成中"}

data: {"type":"token","node":"SAMPLE_STREAM","label":"回答生成中","content":"こんにちは"}

data: {"type":"token","node":"SAMPLE_STREAM","label":"回答生成中","content":"こんにちは！"}

data: {"type":"node_end","node":"SAMPLE_STREAM","label":"回答生成中"}

data: {"type":"done","session_id":"abc123","message":"最終回答テキスト"}

```

---

## StreamEvent スキーマ

SSE の各行に含まれる JSON オブジェクト。定義元: `src/application/stream.py`

| フィールド | 型 | 出現するイベント | 説明 |
|-----------|-----|----------------|------|
| `type` | string | 全イベント | イベント種別。下表参照。 |
| `node` | string \| null | node_start / node_end / token | 対象ノード名 (`SAMPLE`, `SAMPLE_STREAM` 等)。 |
| `label` | string \| null | node_start / node_end / token | ノードの表示用ラベル (`分析中`, `回答生成中` 等)。 |
| `content` | string \| null | token | LLM トークン本文。ノード単位で累積される。 |
| `metadata` | object \| null | input_required | interrupt に渡された値。`message` (確認メッセージ) と `preview` (プレビュー) を含む。 |
| `session_id` | string \| null | done | セッション ID。 |
| `message` | string \| null | done | 最終回答全文。interrupt 時は空文字。 |

### イベント種別 (type)

| type | 説明 | タイミング |
|------|------|----------|
| `node_start` | ノードの処理開始 | 各ノードの実行開始時 |
| `node_end` | ノードの処理完了 | 各ノードの実行完了時 |
| `token` | LLM のトークン出力 | LLM がトークンを生成するたび |
| `input_required` | ユーザー確認待ち | `interrupt()` 発火時 |
| `done` | ストリーム完了 | 最後に 1 回。interrupt 時も送信される (message は空) |

### イベントの流れ (シーケンス例)

CONFIRM ノード (ユーザー確認) を含むフロー。初回リクエストで interrupt が発生し、
ユーザーの承認後に同じ `session_id` で再リクエストして処理を継続する。

```
── 初回リクエスト ──────────────────────
node_start (SAMPLE)
  token (SAMPLE) × N           ← 構造化出力のトークン
node_end (SAMPLE)
node_start (CONFIRM)
input_required                  ← metadata に確認メッセージ + プレビュー
done (message="")               ← interrupt 時は空

── 再リクエスト (同じ session_id, message="yes") ──
node_start (CONFIRM)
node_end (CONFIRM)
node_start (SAMPLE_STREAM)
  token (SAMPLE_STREAM) × N    ← 生テキストのトークン
node_end (SAMPLE_STREAM)
done (message="最終回答テキスト")
```

詳細は [confirm-flow-guide.md](confirm-flow-guide.md) を参照。

---

## 関連ファイル

| ファイル | 役割 |
|---------|------|
| `src/main.py` | エンドポイント定義、SSE 変換 |
| `src/common/schema/chat.py` | `ChatRequest` / `ChatResponse` スキーマ |
| `src/application/stream.py` | `StreamEvent` / `StreamEventType` スキーマ、共通ストリーミング処理 |
