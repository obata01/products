# プロトコルレイヤーの解説

このドキュメントでは、ストリーミングチャット機能で使われている通信の「層（レイヤー）」を解説します。
「どこが標準規格で変えられないのか」「どこがサーバー開発者が自由に決めた部分なのか」を理解することが目的です。

---

## なぜレイヤーを理解する必要があるのか

サーバー側の仕様が変わったとき、**どこを直せばいいか**がわからないと大変です。

例えば、サーバー開発者が「`node_start` を `node_begin` に変えたい」と言ったとします。
これが SSE の仕様なのか、サーバー独自の仕様なのかがわかっていないと、
「SSE の仕様だから変えられないのでは？」と誤解してしまうかもしれません。

実際には `node_start` はサーバー独自の文字列なので、自由に変更できます。
ただし変更した場合、クライアント側の `server_contracts.py` も合わせて更新が必要です。

---

## 全体像

このアプリケーションには 2 つの通信経路があります。

```
                  ┌──────────────┐
  API ストリーミング │  SSE で通信   │  HTTP → SSE → 独自JSON
                  └──────┬───────┘
                         │
  ユーザー ◀─────────────┤
                         │
                  ┌──────┴───────┐
  A2A ストリーミング │  A2A で通信   │  HTTP → JSON-RPC → A2A プロトコル → 独自テキスト
                  └──────────────┘
```

どちらも HTTP の上に複数の「層」が積み重なっています。
下の層ほど標準規格で固定されており、上の層ほどサーバー開発者が自由に決められます。

---

## API ストリーミング側のレイヤー

### レイヤー構造

```
レイヤー1: HTTP          ← 標準規格（変えられない）
レイヤー2: SSE           ← 標準規格（変えられない）
レイヤー3: 独自JSON       ← サーバー開発者が自由に決めた
```

### レイヤー1: HTTP（標準規格）

```
POST /test HTTP/1.1
Content-Type: application/json

{"session_id": "abc", "message": "こんにちは", "stream": true}
```

HTTP はインターネットの基本プロトコルです。`POST` でリクエストを送り、サーバーがレスポンスを返します。
ここは世界共通の規格なので、勝手に変えることはできません。

**変えられないもの:**
- `POST` / `GET` などのメソッド名
- ステータスコード（200, 404, 307 など）
- ヘッダーの形式

**サーバー開発者が決められるもの:**
- エンドポイントのパス（`/test`）
- リクエストボディの形式（`session_id`, `message`, `stream` というフィールド名）

### レイヤー2: SSE — Server-Sent Events（標準規格）

サーバーからクライアントに**一方向でイベントを送り続ける**仕組みです。
HTML の標準仕様で定められています。

```
data: {"type": "node_start", "node": "SAMPLE"}

data: {"type": "token", "content": "こんにちは"}

data: {"type": "done"}

```

**SSE が決めているルール:**
- 各イベントは `data: ` で始まる行で送る（この `data: ` というプレフィックスは SSE の仕様）
- イベント間は空行で区切る
- 他に `event:`, `id:`, `retry:` というフィールドも使える（今回は使っていない）

**SSE が決めていないこと:**
- `data: ` の後ろに何を入れるか → **完全に自由**

つまり、`data: ` の後ろの JSON の中身は SSE とは無関係で、サーバー開発者が自由に決めたものです。

### レイヤー3: 独自 JSON（サーバー開発者が自由に決めた）

```json
{"type": "node_start", "node": "SAMPLE"}
{"type": "token", "content": "こんにちは"}
{"type": "node_end", "node": "SAMPLE"}
{"type": "done"}
```

ここが**全部サーバー独自の仕様**です。

| フィールド | 値の例 | 誰が決めた？ |
|---|---|---|
| `type` というフィールド名 | — | サーバー開発者 |
| `type` の値 `node_start` | — | サーバー開発者 |
| `type` の値 `token` | — | サーバー開発者 |
| `type` の値 `node_end` | — | サーバー開発者 |
| `type` の値 `done` | — | サーバー開発者 |
| `node` というフィールド名 | `"SAMPLE"` | サーバー開発者 |
| `content` というフィールド名 | `"こんにちは"` | サーバー開発者 |

サーバー開発者がこれらを自由に変更できる代わりに、
クライアント側で対応するスキーマ定義が必要になります。
それが `server_contracts.py` の `SSEEventType` と `SSEEvent` です。

```python
# server_contracts.py — サーバー仕様が変わったらここを更新

class SSEEventType(StrEnum):
    NODE_START = "node_start"   # ← サーバーが "node_begin" に変えたらここを直す
    TOKEN = "token"
    ...

class SSEEvent(BaseModel):
    type: SSEEventType
    node: str = ""              # ← サーバーが "node_name" に変えたらここを直す
    content: str = ""           # ← サーバーが "text" に変えたらここを直す
```

### 具体例: サーバーが仕様を変えた場合

**変更前:**
```json
{"type": "token", "content": "こんにちは"}
```

**変更後:** サーバー開発者が `content` を `text` に変えた
```json
{"type": "token", "text": "こんにちは"}
```

**クライアント側の対応:**

```python
# server_contracts.py だけ修正すれば OK
class SSEEvent(BaseModel):
    type: SSEEventType
    node: str = ""
    text: str = ""    # content → text に変更
```

```python
# api_stream.py の _events_to_chunks() も修正
yield ChunkType.ANSWER, event.text    # event.content → event.text
```

表示ロジック（`chat_utils.py`）は `ChunkType.ANSWER` しか見ないので変更不要です。

---

## A2A ストリーミング側のレイヤー

### レイヤー構造

```
レイヤー1: HTTP                ← 標準規格（変えられない）
レイヤー2: JSON-RPC            ← 標準規格（変えられない）
レイヤー3: A2A プロトコル       ← A2A 仕様（基本変えられない）
レイヤー4: 独自テキスト         ← サーバー開発者が自由に決めた
```

API 側より 1 層多いのがポイントです。

### レイヤー1: HTTP（標準規格）

API 側と同じです。

```
POST /a2a/ HTTP/1.1
Content-Type: application/json
```

### レイヤー2: JSON-RPC（標準規格）

A2A プロトコルは内部で JSON-RPC 2.0 を使っています。
JSON-RPC はリモートプロシージャコール（遠隔手続き呼び出し）の標準規格です。

```json
{
    "jsonrpc": "2.0",
    "method": "message/send",
    "params": { ... },
    "id": "req-123"
}
```

**JSON-RPC が決めているルール:**
- `jsonrpc`, `method`, `params`, `id` というフィールド構造
- エラー時のレスポンス形式

**サーバー開発者が決めること:** なし（A2A ライブラリが自動処理）

### レイヤー3: A2A プロトコル（A2A 仕様）

Google が策定した Agent-to-Agent 通信の仕様です。
JSON-RPC の上に、AI エージェント同士の通信に特化したルールを追加しています。

```
A2A が決めている型・ルール:

TaskStatusUpdateEvent     ← 「タスクの状態が変わった」ことを通知するイベント
  └─ status:
      ├─ state: TaskState.working     ← 「処理中」
      └─ message: Message             ← 状態に付随するメッセージ

TaskArtifactUpdateEvent   ← 「成果物（最終回答）ができた」ことを通知するイベント
  └─ artifact:
      └─ parts: [TextPart, ...]       ← テキストパーツのリスト

TaskState                 ← タスクの状態
  ├─ working              ← 処理中
  ├─ completed            ← 完了
  └─ failed               ← 失敗
```

**A2A 仕様で決まっていること:**
- イベントの型名（`TaskStatusUpdateEvent` など）
- 状態の種類（`working`, `completed` など）
- `Artifact` の構造（`parts` リストに `TextPart` を入れる）
- エージェントカード（`.well-known/agent.json`）のスキーマ
- ストリーミング時のイベント配信方式

**サーバー開発者が決められること:**
- どのタイミングで `working` / `completed` を送るか
- `message` や `artifact` の**テキストの中身**

これらの型は `a2a` ライブラリが提供しているので、クライアント側で定義する必要がありません。

### レイヤー4: 独自テキスト（サーバー開発者が自由に決めた）

A2A のイベント型は決まっていますが、その中の**テキストの内容**はサーバーが自由に決めます。

```
TaskStatusUpdateEvent (A2A 仕様が決めた型)
  └─ status.message のテキスト:
     "▶ SAMPLE : こんにちは"           ← サーバー開発者が自由に決めた形式
```

サーバーがこのテキストを `[SAMPLE] こんにちは` に変えることも自由にできます。

現在のクライアントはこのテキストを**そのまま表示しているだけ**（パースしていない）なので、
形式が変わっても**クライアント側の修正は不要**です。
もし将来このテキストをパースしてノード名を抽出するような処理を入れるなら、
そのフォーマットも `server_contracts.py` に定義すべきです。

---

## 2 つの経路の対比

| 層 | API (SSE) | A2A |
|---|---|---|
| レイヤー1 | HTTP POST | HTTP POST |
| レイヤー2 | SSE（`data: ...`） | JSON-RPC 2.0 |
| レイヤー3 | **独自 JSON**（`SSEEvent`） | **A2A プロトコル**（`TaskStatusUpdateEvent` 等） |
| レイヤー4 | — | **独自テキスト**（thinking の中身） |

### 大きな違い

**API 側**はレイヤー 3 が**独自仕様**なので、`server_contracts.py` で自前で型を定義して守る必要があります。

**A2A 側**はレイヤー 3 が**標準プロトコル**なので、`a2a` ライブラリの型がそのまま使えます。
サーバー独自の部分はレイヤー 4（テキストの中身）だけで、現在は透過的に扱っているため影響が小さいです。

---

## コードとの対応関係

```
API 側:

  HTTP          → httpx が処理          ← 標準規格
  SSE           → _parse_sse_events()   ← 標準規格（"data: " の処理）
  独自 JSON     → SSEEvent で型保証      ← server_contracts.py で定義
  表示用チャンク → _events_to_chunks()   ← ChunkType に変換（境界層）


A2A 側:

  HTTP          → httpx が処理                    ← 標準規格
  JSON-RPC      → a2a ライブラリが処理              ← 標準規格
  A2A プロトコル → a2a ライブラリの型                ← A2A 仕様
  独自テキスト   → AgentClient.stream() で透過的に返す
  表示用チャンク → ChunkType に変換（境界層）


共通:

  ChunkType     → StreamingChatPage が処理  ← サーバー仕様を知らない
```

サーバー仕様が変わった場合の影響範囲:
- **API 側**: `server_contracts.py` → `_parse_sse_events()` / `_events_to_chunks()`
- **A2A 側**: thinking テキスト形式が変わった場合のみ、表示に影響（現在はパースしていないので影響なし）
- **表示ロジック**: どちらの場合も `StreamingChatPage` は変更不要
