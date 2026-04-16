# A2A インターフェース仕様

A2A (Agent-to-Agent) プロトコルのインターフェース仕様。
マウントパス: `/a2a`

---

## プロトコル概要

A2A は Google が策定したエージェント間通信プロトコル。
本システムでは `a2a` ライブラリの `A2AStarletteApplication` を使い、以下の 2 つのメソッドに対応する。

| メソッド | 説明 |
|---------|------|
| `message/send` | 非ストリーミング。最終結果のみ返す。 |
| `message/stream` | ストリーミング。思考イベントを逐次配信する。 |

A2A フレームワークが `message/send` と `message/stream` のルーティングを行い、
どちらも `LangGraphAgentExecutor.execute()` を呼び出す。
Executor は常に `astream_events` でストリーミング実行し、全イベントを `EventQueue` に送信する。
フレームワーク側が `message/send` の場合は全イベントを集約して最終結果を返し、
`message/stream` の場合はイベントを逐次ストリーミングする。

---

## エージェントカード

`GET /a2a/.well-known/agent.json` で取得可能。定義元: `src/a2a_app/card.py`

```json
{
  "name": "LangGraph Agent",
  "description": "LangGraph ベースのエージェント。思考過程をストリーミング配信します。",
  "url": "<base_url>",
  "version": "1.0.0",
  "capabilities": {
    "streaming": true
  },
  "skills": [
    {
      "id": "chat",
      "name": "チャット",
      "description": "ユーザーのメッセージに応答します。",
      "tags": [],
      "input_modes": ["text/plain"],
      "output_modes": ["text/plain"]
    }
  ],
  "default_input_modes": ["text/plain"],
  "default_output_modes": ["text/plain"]
}
```

---

## リクエスト

A2A プロトコルの `MessageSendParams` に準拠。テキストメッセージを `TextPart` として送信する。

```json
{
  "message": {
    "role": "user",
    "parts": [
      {"type": "text", "text": "ユーザーの入力メッセージ"}
    ],
    "message_id": "msg-xxx"
  },
  "configuration": {
    "blocking": true
  }
}
```

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `message.parts[].text` | string | ユーザーからの入力テキスト。複数パーツはスペース結合される。 |
| `configuration.blocking` | boolean \| null | A2A フレームワークが使用するフラグ。Executor の実行パスには影響しない。 |

---

## レスポンス

### ストリーミング (`message/stream`)

`TaskStatusUpdateEvent` と `TaskArtifactUpdateEvent` が逐次配信される。

#### 1. 思考イベント (`TaskStatusUpdateEvent`, state=working)

各イベントの `status.message.parts[0].text` に `StreamEvent` 互換の JSON が入る。
API (SSE) と同一のスキーマ。

```json
{
  "status": {
    "state": "working",
    "message": {
      "role": "agent",
      "parts": [
        {"type": "text", "text": "{\"type\":\"node_start\",\"node\":\"SAMPLE\",\"label\":\"分析中\"}"}
      ]
    }
  },
  "final": false,
  "taskId": "task-xxx",
  "contextId": "ctx-xxx"
}
```

#### 2. 最終回答 (`TaskArtifactUpdateEvent`)

最終回答テキストが `Artifact` の `TextPart` として送信される。

```json
{
  "artifact": {
    "artifact_id": "uuid",
    "parts": [
      {"type": "text", "text": "最終回答テキスト"}
    ]
  },
  "taskId": "task-xxx",
  "contextId": "ctx-xxx"
}
```

#### 3. 入力待ち (`TaskStatusUpdateEvent`, state=input_required)

ワークフロー内で `interrupt()` が呼ばれた場合に送信される。
クライアントはユーザーの応答を同じ `contextId` で再送信する必要がある。

```json
{
  "status": {
    "state": "input_required",
    "message": {
      "role": "agent",
      "parts": [
        {"type": "text", "text": "ユーザーの確認を待っています。"}
      ]
    }
  },
  "final": false,
  "taskId": "task-xxx",
  "contextId": "ctx-xxx"
}
```

#### 4. 完了 (`TaskStatusUpdateEvent`, state=completed)

```json
{
  "status": {
    "state": "completed"
  },
  "final": true,
  "taskId": "task-xxx",
  "contextId": "ctx-xxx"
}
```

### 非ストリーミング (`message/send`)

フレームワークが全イベントを集約し、最終的な `Task` オブジェクトを返す。
思考イベントはクライアントには配信されず、artifact と completed のみが結果に反映される。

---

## StreamEvent スキーマ (思考イベント内 JSON)

思考イベントの `status.message.parts[0].text` に含まれる JSON。
API (SSE) の `StreamEvent` と同一スキーマ。定義元: `src/application/stream.py`

| フィールド | 型 | 出現するイベント | 説明 |
|-----------|-----|----------------|------|
| `type` | string | 全イベント | イベント種別。 |
| `node` | string \| null | node_start / node_end / token | 対象ノード名 (`SAMPLE`, `SAMPLE_STREAM` 等)。 |
| `label` | string \| null | node_start / node_end / token | ノードの表示用ラベル (`分析中`, `回答生成中` 等)。 |
| `content` | string \| null | token | LLM トークン本文。ノード単位で累積される。 |
| `metadata` | object \| null | input_required | interrupt に渡された値。`message` (確認メッセージ) と `preview` (プレビュー) を含む。 |

※ `done` イベントは A2A では送信されない。完了は `TaskStatusUpdateEvent` (state=completed) で判定する。

### イベント種別 (type)

| type | 説明 |
|------|------|
| `node_start` | ノードの処理開始 |
| `node_end` | ノードの処理完了 |
| `token` | LLM のトークン出力 |
| `input_required` | ユーザー確認待ち (`interrupt()` 発火時) |

### イベントの流れ (シーケンス例)

CONFIRM ノード (ユーザー確認) を含むフロー。初回リクエストで interrupt が発生し、
ユーザーの承認後に同じ `contextId` で再リクエストして処理を継続する。

```
── 初回リクエスト ──────────────────────
TaskStatusUpdateEvent (working): {"type":"node_start","node":"SAMPLE","label":"分析中"}
TaskStatusUpdateEvent (working): {"type":"token","node":"SAMPLE",...,"content":"..."}
TaskStatusUpdateEvent (working): {"type":"node_end","node":"SAMPLE","label":"分析中"}
TaskStatusUpdateEvent (working): {"type":"node_start","node":"CONFIRM","label":"確認待ち"}
TaskStatusUpdateEvent (working): {"type":"input_required","metadata":{"message":"...","preview":"..."}}
TaskStatusUpdateEvent (input_required): "ユーザーの確認を待っています。"

── 再リクエスト (同じ contextId, message="yes") ──
TaskStatusUpdateEvent (working): {"type":"node_start","node":"CONFIRM","label":"確認待ち"}
TaskStatusUpdateEvent (working): {"type":"node_end","node":"CONFIRM","label":"確認待ち"}
TaskStatusUpdateEvent (working): {"type":"node_start","node":"SAMPLE_STREAM","label":"回答生成中"}
TaskStatusUpdateEvent (working): {"type":"token","node":"SAMPLE_STREAM",...,"content":"こんにちは"}
TaskStatusUpdateEvent (working): {"type":"node_end","node":"SAMPLE_STREAM","label":"回答生成中"}
TaskArtifactUpdateEvent: "最終回答テキスト"
TaskStatusUpdateEvent (completed, final=true)
```

詳細は [confirm-flow-guide.md](confirm-flow-guide.md) を参照。

---

## API (SSE) との差異

| 項目 | API (SSE) | A2A |
|------|-----------|-----|
| トランスポート | HTTP SSE (`text/event-stream`) | A2A プロトコル (JSON-RPC / REST) |
| 思考イベントの形式 | `data: {StreamEvent JSON}` | `TaskStatusUpdateEvent.status.message` 内に StreamEvent JSON |
| 完了の通知 | `done` イベント (StreamEvent) | `TaskStatusUpdateEvent` (state=completed, final=true) |
| 最終回答 | `done` イベントの `message` フィールド | `TaskArtifactUpdateEvent` の `TextPart` |
| StreamEvent の内容 | 同一スキーマ | 同一スキーマ (`done` を除く) |

---

## 関連ファイル

| ファイル | 役割 |
|---------|------|
| `src/a2a_app/executor.py` | `LangGraphAgentExecutor` — A2A タスク実行 |
| `src/a2a_app/server.py` | A2A Starlette アプリのファクトリー |
| `src/a2a_app/card.py` | エージェントカード定義 |
| `src/a2a_app/client.py` | A2A クライアント (`AgentClient`) |
| `src/application/stream.py` | `StreamEvent` スキーマ、共通ストリーミング処理 |
