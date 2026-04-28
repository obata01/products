# API インターフェース仕様

HTTP API (SSE) のリクエスト・レスポンス仕様。

---

## エンドポイント一覧

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/health` | ヘルスチェック |
| POST | `/claude-code` | Claude Code テキスト生成 (JSON / SSE) |

---

## GET /health

### レスポンス

```json
{"status": "ok"}
```

---

## POST /claude-code

Claude Code CLI を利用したテキスト生成エンドポイント。
ファイル I/O は行わず、すべてメモリ上で完結する。
LangGraph ワークフローは単一の `CLAUDE_CODE` ノードで構成される。

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
  "message": "Claude Code の処理中にエラーが発生しました。"
}
```

---

### レスポンス: ストリーミング (`stream=true`)

Content-Type: `text/event-stream`

SSE 形式で `StreamEvent` JSON が逐次配信される。各イベントは `data: ` プレフィクス付き。

```
data: {"type":"node_start","node":"CLAUDE_CODE","label":"Claude Code 処理中"}

data: {"type":"progress","node":"CLAUDE_CODE","label":"Claude Code 処理中","content":"Claude Code セッション開始"}

data: {"type":"progress","node":"CLAUDE_CODE","label":"Claude Code 処理中","content":"ツール実行中: Read"}

data: {"type":"token","node":"CLAUDE_CODE","label":"Claude Code 処理中","content":"生成テキスト"}

data: {"type":"token","node":"CLAUDE_CODE","label":"Claude Code 処理中","content":"生成テキストの続き"}

data: {"type":"node_end","node":"CLAUDE_CODE","label":"Claude Code 処理中"}

data: {"type":"done","session_id":"abc123","message":"最終回答テキスト全文"}

```

---

## StreamEvent スキーマ

SSE の各行に含まれる JSON オブジェクト。定義元: `src/application/stream.py`

| フィールド | 型 | 出現するイベント | 説明 |
|-----------|-----|----------------|------|
| `type` | string | 全イベント | イベント種別。下表参照。 |
| `node` | string \| null | node_start / node_end / token / progress | 対象ノード名 (`CLAUDE_CODE` 等)。 |
| `label` | string \| null | node_start / node_end / token / progress | ノードの表示用ラベル (`Claude Code 処理中` 等)。 |
| `content` | string \| null | token / progress | LLM トークン本文 (token)、または進捗メッセージ (progress)。 |
| `session_id` | string \| null | done | セッション ID。 |
| `message` | string \| null | done | 最終回答全文。 |

### イベント種別 (type)

| type | 説明 | タイミング |
|------|------|----------|
| `node_start` | ノードの処理開始 | 各ノードの実行開始時 |
| `node_end` | ノードの処理完了 | 各ノードの実行完了時 |
| `token` | LLM のトークン出力 | LLM がトークンを生成するたび |
| `progress` | 処理の進捗通知 | Claude Code のセッション開始時やツール実行時 |
| `done` | ストリーム完了 | 最後に 1 回 |

### イベントの流れ (シーケンス例)

```
── リクエスト ──────────────────────
node_start (CLAUDE_CODE)
  progress (CLAUDE_CODE)         ← "Claude Code セッション開始"
  progress (CLAUDE_CODE)         ← "ツール実行中: ..." (ツール使用時のみ)
  token (CLAUDE_CODE) × N       ← テキストトークン
node_end (CLAUDE_CODE)
done (message="最終回答テキスト")
```

### A2A プロトコル

A2A エンドポイントは `/a2a` にマウントされる。
エージェントカードは `GET /a2a/.well-known/agent.json` で取得可能。
イベント形式は SSE と同一の `StreamEvent` スキーマ (progress イベントを含む)。

---

## 関連ファイル

| ファイル | 役割 |
|---------|------|
| `src/main.py` | エンドポイント定義、SSE 変換 |
| `src/common/schema/chat.py` | `ChatRequest` / `ChatResponse` スキーマ |
| `src/application/stream.py` | `StreamEvent` / `StreamEventType` スキーマ、共通ストリーミング処理 |
| `src/application/nodes/claude_code.py` | Claude Code CLI 呼び出しノード |
| `src/application/workflows/claude_code.py` | Claude Code 単一ノードワークフロー |
