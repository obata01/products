# ストリーミングチャット機能の解説

このドキュメントでは、Streamlit フロントエンドのストリーミングチャット機能を構成する 3 つのファイルについて解説します。

---

## 全体像

```
ユーザーが入力
    │
    ▼
┌──────────────────────────────────────────────────┐
│  run_streaming_chat()  (chat_utils.py)           │
│  - タイトル表示                                    │
│  - メッセージ履歴の描画                              │
│  - ユーザー入力の受付                                │
│  - stream_fn を呼んでストリーミング表示               │
│  - セッションへの保存                                │
└──────────┬───────────────────────────┬────────────┘
           │                           │
     stream_fn に                stream_fn に
     _stream_sse を渡す           _stream_a2a を渡す
           │                           │
           ▼                           ▼
   ┌───────────────┐          ┌────────────────┐
   │ api_stream.py │          │ a2a_stream.py  │
   │ SSE で通信     │          │ A2A で通信      │
   └───────┬───────┘          └───────┬────────┘
           │                           │
           ▼                           ▼
      Template サーバー (8101)    A2A サーバー (8101)
```

各ページは**通信の方法だけが異なり**、画面の表示ロジックはすべて `chat_utils.py` に共通化されています。

---

## 1. chat_utils.py — 共通表示ロジック

このファイルには 4 つの関数があります。順番に見ていきましょう。

### 1-1. `_accumulate_thinking()` — 思考テキストの蓄積

```python
def _accumulate_thinking(segments: list[str], new_chunk: str) -> None:
```

サーバーから届く思考テキスト（thinking）を蓄積する関数です。

サーバーによって、テキストの届き方が 2 パターンあります:

**パターン A: 累積値** — 毎回「最初からの全文」が届く

```
1回目: "▶ START : "
2回目: "▶ START : \n\n▶ SAMPLE : {"
3回目: "▶ START : \n\n▶ SAMPLE : {"message"}"
```

**パターン B: デルタ** — 毎回「今回の差分だけ」が届く

```
1回目: "[START] 開始"
2回目: "[START] 完了"
3回目: "[SAMPLE] 開始"
```

この関数は**自動で判定**します:

```
新しいチャンクが、直前セグメントで始まっている？
  → はい: 累積値だ → 直前セグメントを上書き（置換）
  → いいえ: デルタだ → 新しいセグメントとして追加
```

例（累積値のケース）:

```python
segments = ["▶ START : "]
new_chunk = "▶ START : tok1"
# "▶ START : tok1" は "▶ START : " で始まる → 置換
# segments = ["▶ START : tok1"]
```

例（デルタのケース）:

```python
segments = ["思考中..."]
new_chunk = "[START] 開始"
# "[START] 開始" は "思考中..." で始まらない → 追加
# segments = ["思考中...", "[START] 開始"]
```

### 1-2. `_render_message_history()` — 過去メッセージの描画

```python
def _render_message_history(messages: list[dict]) -> None:
```

ページを開いたとき（またはリロード時）に、過去のやりとりを画面に表示します。

```
各メッセージについて:
  1. チャット吹き出しを作る (user or assistant)
  2. thinking があれば折りたたみ (expander) で表示
  3. 回答テキストを表示
```

### 1-3. `_write_streaming_response()` — リアルタイム表示

```python
def _write_streaming_response(chunks) -> tuple[str, str]:
```

これがストリーミング表示の中心です。チャンクが届くたびに画面を更新します。

3 種類のチャンクを処理します:

| チャンク種別 | 意味 | 画面の動作 |
|---|---|---|
| `"thinking"` | 思考過程のテキスト | 「思考中…」expander 内に表示 |
| `"answer_start"` | 新しいノードの回答開始 | 回答エリアをクリア |
| `"answer"` | 回答テキストの断片 | 回答エリアに追記 |

表示の流れを時系列で見ると:

```
チャンク受信          画面の状態
─────────────────────────────────────────────
thinking "▶ START"   [思考中…(展開)] ▶ START▌
                     [回答エリア: 空]

thinking "▶ SAMPLE"  [思考中…(展開)] ▶ START → ▶ SAMPLE▌
                     [回答エリア: 空]

answer_start         [思考中…(展開)] ...
                     [回答エリア: ▌]  ← クリアされた

answer "こん"        [思考過程(折畳)] ...  ← 折りたたまれた
                     [回答エリア: こん▌]

answer "にちは"      [思考過程(折畳)] ...
                     [回答エリア: こんにちは▌]

── ストリーム終了 ──
                     [思考過程(折畳)] ▶ START → ▶ SAMPLE → ...
                     [回答エリア: こんにちは]  ← ▌カーソル消去
```

ポイント:
- `st.empty()` で**プレースホルダー**を作り、そこを何度も上書きする（画面がちらつかない）
- 回答が始まったら thinking の expander を自動的に折りたたむ
- 最後に `▌`（カーソル）を消して確定表示にする

### 1-4. `run_streaming_chat()` — ページの骨格

```python
def run_streaming_chat(*, title, session_key, stream_fn) -> None:
```

ストリーミングチャットページの**全体フロー**を担当します。各ページはこの関数を呼ぶだけです。

```
1. タイトルを表示
2. セッションにメッセージ履歴がなければ空リストを作成
3. 過去メッセージを描画
4. ユーザーが入力したら:
   a. ユーザーメッセージを表示 & セッションに保存
   b. stream_fn(prompt) を呼んでチャンクを受け取る
   c. _write_streaming_response() でストリーミング表示
   d. アシスタントの回答をセッションに保存
```

`stream_fn` には通信方法ごとに異なる関数を渡します:
- API ページ → `_stream_sse`
- A2A ページ → `_stream_a2a`

---

## 2. api_stream.py — SSE 直接通信ページ

### 通信方式

Template サーバーに HTTP POST を送り、**SSE (Server-Sent Events)** でレスポンスを受け取ります。

```
Streamlit ──HTTP POST──▶ Template サーバー (:8101/test)
         ◀──SSE ストリーム──
```

SSE とは、サーバーがクライアントに**一方向でイベントを送り続ける**仕組みです。
各行は `data: {"type": "...", ...}` という形式で届きます。

### `_stream_sse()` の処理フロー

```python
def _stream_sse(prompt: str) -> Generator[tuple[str, str], None, None]:
```

```
1. httpx で POST リクエストをストリーミングモードで送信
2. 届いた各行を処理:
   ├─ "data: " で始まらない行 → 無視
   └─ "data: " で始まる行 → JSON パース
       ├─ type == "node_start"
       │   → thinking に "▶ ノード名 : " を追加して yield
       │   → pending_reset = True (次のトークンで回答リセット)
       │
       └─ type == "token"
           → thinking にトークンを追加して yield
           → pending_reset なら answer_start を yield (回答リセット)
           → answer としてトークンを yield
```

#### `answer_start` の仕組み

グラフには複数のノードがあり、途中のノード（SAMPLE）も LLM 出力を返します。
でも最終回答は**最後のノード**（SAMPLE_STREAM）の出力だけにしたい。

```
▶ START_GATE : (トークンなし)
▶ SAMPLE : {"message":"..."}     ← これは最終回答ではない
▶ SAMPLE_STREAM : こんにちは！    ← これが最終回答
▶ END_GATE : (トークンなし)
```

そこで、新しいノードが始まるたびに `pending_reset = True` にし、
そのノードで最初のトークンが届いたときに `answer_start` を yield します。
`answer_start` を受け取った `_write_streaming_response()` は回答バッファをクリアするので、
**常に最後にトークンを出力したノードの内容だけが最終回答に残ります**。

---

## 3. a2a_stream.py — A2A プロトコル通信ページ

### 通信方式

A2A (Agent-to-Agent) プロトコルを使って、別の AI エージェントと通信します。

```
Streamlit ──A2A プロトコル──▶ A2A サーバー (:8101/a2a)
         ◀──ストリーミング────
```

### async から sync への変換

Streamlit は**同期的**に動きますが、A2A クライアントは **async** (非同期) です。
この 2 つの世界をつなぐのが `_stream_a2a()` の仕事です。

```python
def _stream_a2a(prompt: str) -> Generator[tuple[str, str], None, None]:
```

```
メインスレッド (Streamlit, 同期)          サブスレッド (async)
─────────────────────────────          ──────────────────────
                                       asyncio.run() で
                                       A2A クライアント起動
                                            │
                                       チャンク受信 → queue に put
queue.get() でチャンクを取り出し ◀────
yield でチャンクを返す                 チャンク受信 → queue に put
queue.get() でチャンクを取り出し ◀────
yield でチャンクを返す                      ...
      ...                              完了 → _SENTINEL を put
queue.get() で _SENTINEL を取得 ◀────
ループ終了
```

ポイント:
- **`queue.Queue`** — スレッド間で安全にデータを受け渡す仕組み
- **`_SENTINEL`** — 「もうデータはない」を伝える特別な目印（番兵）。`object()` で作るので、どんなデータとも衝突しない
- **`daemon=True`** — メインスレッドが終了したらサブスレッドも自動終了

### A2A の場合 answer_start は不要

A2A プロトコルでは、サーバーが最終回答を `TaskArtifactUpdateEvent` として明確に分けて送ります。
thinking（`TaskStatusUpdateEvent`）と answer（`TaskArtifactUpdateEvent`）が**プロトコルレベルで分離**されているため、
API 側のように `answer_start` でリセットする必要がありません。

---

## まとめ: 2 つのページの対比

| 項目 | api_stream.py | a2a_stream.py |
|---|---|---|
| 通信プロトコル | HTTP + SSE | A2A (JSONRPC) |
| 同期/非同期 | 同期 (httpx) | 非同期 → thread+queue で同期に変換 |
| thinking の出し方 | クライアントでノード名を付加 | サーバーが累積テキストを送信 |
| answer の出し方 | 全トークンを yield + answer_start でリセット | サーバーが最終回答だけを Artifact で送信 |
| 表示ロジック | `run_streaming_chat()` (共通) | `run_streaming_chat()` (共通) |

通信方法は異なりますが、**最終的に `("thinking", text)` / `("answer", text)` のチャンクに変換する**点は同じです。
この統一インターフェースのおかげで、表示ロジックを完全に共通化できています。
