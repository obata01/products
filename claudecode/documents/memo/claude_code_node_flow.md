# `claude_code.py` 処理フロー解説

[src/application/nodes/claude_code.py](src/application/nodes/claude_code.py) の `claude_code()` 関数を起点に、**呼ばれてから戻るまでの時間軸に沿って** 処理の流れを追う。

## 全体像（10 秒で掴む）

```
┌────────────────────────────────────────────────────────────┐
│ claude_code(state, config)                                 │
│                                                            │
│  1. state からユーザー入力を取り出す                         │
│  2. CLI コマンドを組み立てる (_build_command)                │
│  3. サブプロセス起動 (create_subprocess_exec)                │
│  4. stderr 吸い出しタスクを裏で走らせる (create_task)         │
│  5. stdout を 1 行ずつ読む (_process_stream)                 │
│     └ 行が届くたびに dispatch → フロントへストリーミング        │
│  6. プロセス終了を待つ (proc.wait)                           │
│  7. AIMessage を chat_history に積んで返す                   │
└────────────────────────────────────────────────────────────┘
```

---

## ステップごとの詳細

### Step 1: 入力の取り出し（L193〜196）

```python
message = state["last_user_message"]
cmd = _build_command(message)
logger.info("Claude Code CLI 実行開始: prompt=%s", message[:100])
```

LangGraph の `State` TypedDict（[states.py](src/application/states.py)）から、ユーザーの最新メッセージを取り出す。コマンドを組み立てたあと、最初の 100 文字だけをログに残す（長文プロンプトでログが爆発しないように）。

### Step 2: コマンド構築（`_build_command`）

`_build_command` が返すリストは、例えばこうなる:

```python
[
    "claude",                       # settings.claude_code_cli_path
    "-p", "<ユーザー入力>",          # 非対話モード（print mode）
    "--output-format", "stream-json", # JSONL でイベントを吐かせる
    "--verbose",                    # stream-json と併用必須
    "--include-partial-messages",   # 生成途中の assistant イベントも流す
    "--max-turns", "3",             # settings.claude_code_max_turns > 0 のときのみ
]
```

オプションの意味:

| オプション | 役割 |
| --- | --- |
| `-p <msg>` | プロンプトを引数で渡し、結果を stdout に吐いて終了する非対話モード |
| `--output-format stream-json` | 1 行 1 JSON（JSONL）でイベントを吐かせる |
| `--verbose` | stream-json モードの必須オプション。省略するとメタイベントが欠落 |
| `--include-partial-messages` | 生成途中の `assistant` イベントを逐次出力 → **これがあるからストリーミング可能** |
| `--max-turns N` | エージェントの自律ターン上限。`0` 以下は付けない（CLI デフォルトに委譲） |

L78 のコメント `# NOTE: --bare は OAuth 認証と併用すると認証エラーになるため除外` は過去に踏んだ落とし穴の記録。

### Step 3: サブプロセス起動（L198〜206）

```python
try:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
except FileNotFoundError:
    logger.exception("Claude Code CLI が見つかりません: path=%s", settings.claude_code_cli_path)
    return {"chat_history": [AIMessage(content=_ERROR_MESSAGE)]}
```

3 つの要点:

1. **`create_subprocess_exec` はシェルを介さない**: 引数リストを直接 `claude` に渡す。`create_subprocess_shell` と違い `;` や `|` などのシェル文法が解釈されないため、ユーザー入力がどんな文字列でも **シェルインジェクションは起こらない**
2. **`*cmd` はアンパック**: リストを位置引数に展開する構文。`create_subprocess_exec("claude", "-p", "...", ..., stdout=..., stderr=...)` と書いたのと等価
3. **`PIPE` は Python とつながる管**: CLI の stdout / stderr を Python が `proc.stdout` / `proc.stderr` から読めるようにする指示。指定しなければ親プロセスのターミナルに直出力される

`FileNotFoundError` は CLI バイナリが存在しないとき専用の例外。ここだけ握って穏便にエラーメッセージを返す。

### Step 4: stderr を裏で吸い出すタスクを走らせる（L208〜209）

```python
# stdout と stderr を並行して読み取り、パイプバッファのデッドロックを防止する
stderr_task = asyncio.create_task(_drain_stderr(proc))
```

ここがこの実装で一番「**知らないと死ぬ**」ポイント。

#### なぜ必要か — パイプバッファのデッドロック

OS のパイプには容量（Linux では通常 64KB 程度）がある。stdout を読んでいる裏で、もし stderr を **読まずに放置** すると、次のような詰まりが起きる:

```
1. CLI は stderr にもログを吐き続ける
2. stderr のパイプバッファが 64KB で満杯に
3. CLI の write() がブロック → CLI 全体が止まる
4. CLI が止まるので stdout にも何も来なくなる
5. Python の async for は永遠に次の行を待つ
6. デッドロック完成
```

対策は「stdout を読む裏で stderr も読み続ける」。`asyncio.create_task` は **コルーチンをバックグラウンドタスクとして走らせる** API。ここで起動しておけば、メイン処理（stdout 読み）と並行に stderr を消費してくれる。

`_drain_stderr` 自体は `await proc.stderr.read()` で末尾まで一気に読むだけのシンプルな実装。`drain` は「排水する／吸い出す」という意味で、**読むこと自体が目的**（内容の利用はエラー時ログ用の副次）。

### Step 5: stdout を 1 行ずつ読んでストリーミング（L211〜215）

```python
try:
    full_text = await asyncio.wait_for(
        _process_stream(proc, config),
        timeout=settings.claude_code_timeout,
    )
```

**この await 中が、フロントエンドから見たストリーミングの本体**。見た目は「1 行の await」だが、中では 1 行読むたびに dispatch が走っている。

#### `_process_stream` の内部（L148〜176）

```python
async for raw_line in proc.stdout:
    line = raw_line.decode("utf-8").strip()
    if not line:
        continue
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        logger.debug("Claude Code: JSON パース失敗: %s", line[:200])
        continue

    full_text, prev_len = await _handle_event(event, config, full_text, prev_len)
```

- `async for raw_line in proc.stdout` は `StreamReader` から **1 行届くたびに 1 イテレーション** 回る
- 空行はスキップ、JSON パース失敗も debug ログだけ残して continue（壊れた行で全体を止めない）
- `_handle_event` に委譲して状態を更新

#### `_handle_event` のイベント種別ごとの挙動（L106〜145）

| `event_type` | 処理 | dispatch する？ |
| --- | --- | --- |
| `"assistant"` | `content` からテキスト抽出 → `prev_len` との差分を計算 | **TOKEN**（差分があるときのみ） |
| `"result"` | `event["result"]` を `full_text` として採用 | なし |
| `"system"` + `subtype=="init"` | セッション開始通知 | **PROGRESS**「Claude Code セッション開始」 |
| `"tool_use"` | ツール名を取り出し進捗通知 | **PROGRESS**「ツール実行中: <ツール名>」 |

差分計算のカラクリ:
```python
delta = text[prev_len:]   # これまでの累積長以降を切り出し
if delta:
    await _dispatch_token(delta, config)
    return text, len(text)
```

`--include-partial-messages` で届く `assistant` イベントは **累積テキスト**（差分ではない）のため、自前で `prev_len` を保持して切り出す必要がある。

#### dispatch の流れ（イベントが届くまで）

```
┌──────────────────────────────────────────────────────────────┐
│ claude_code.py                                               │
│   _dispatch_token("Hello")                                   │
│    └─ adispatch_custom_event("claude_code_token", {...})     │
└───────────────────┬──────────────────────────────────────────┘
                    │ LangChain のコールバック機構
                    ▼
┌──────────────────────────────────────────────────────────────┐
│ stream.py  （astream_events(version="v2") 経由で受信）         │
│   _parse_custom_event("claude_code_token", {...})            │
│    └─ GraphEvent(kind=TOKEN, text="Hello")                   │
│   to_stream_event(ev)                                        │
│    └─ StreamEvent(type=TOKEN, content="Hello")               │
└───────────────────┬──────────────────────────────────────────┘
                    │
                    ▼
              SSE / A2A でフロントへ
```

イベント名は [stream.py](src/application/stream.py) の `CLAUDE_CODE_TOKEN_EVENT` / `CLAUDE_CODE_PROGRESS_EVENT` で共有しており、**発行側と受信側で同じ定数を参照する契約** になっている。

> **ディスパッチ（dispatch）とは**: 「名前付きの出来事を、誰が受け取るか知らずに投げる」こと。呼び出し側（このノード）は SSE の存在を知らなくていいし、配信側（stream.py）はノード内部の事情を知らなくていい。両者をイベント名という "契約" だけで疎結合に保つ仕組み。

#### `wait_for` の役割

```python
await asyncio.wait_for(_process_stream(...), timeout=settings.claude_code_timeout)
```

指定秒を超えたら `TimeoutError` を送出する。`claude_code_timeout` は [settings/app.py](src/common/settings/app.py) で既定 300 秒。

### Step 6: プロセスの後始末（L222〜223）

```python
await proc.wait()
stderr_task = await stderr_task  # 変数名は stderr_text
```

#### よくある誤解

「`_process_stream` で全出力を取得済みなのに、なぜさらに `proc.wait()` が必要？」

→ **stdout が EOF になった ≠ プロセスが完全に終了した**。EOF 後も CLI はわずかに動いている可能性がある（stderr フラッシュ・atexit ハンドラ・孫プロセス待ち等）。

`await proc.wait()` が解決する 3 つのこと:

| 役割 | 省くとどうなる？ |
| --- | --- |
| (a) プロセスの完全終了を待つ | 完全終了前に次の処理に進んでしまう |
| (b) `proc.returncode` を確定させる | `None` のまま。`None != 0` は常に True なので **成功時も毎回エラーログ** が出る |
| (c) Unix のゾンビプロセス回収 | プロセステーブルにゴミが残る。長寿命サーバではプロセス枯渇の原因 |

`await stderr_task` は Step 4 で起動した裏タスクの完了待ち。**起動したタスクは必ず回収する** のが asyncio の作法（放置すると `Task was destroyed but it is pending!` 警告）。

### Step 7: 結果判定と戻り値（L225〜234）

```python
if proc.returncode != 0:
    logger.error("Claude Code CLI 失敗: returncode=%d, stderr=%s", proc.returncode, stderr_text[:500])
    if not full_text:
        full_text = _ERROR_MESSAGE

logger.info("Claude Code CLI 完了: result_length=%d", len(full_text))

return {
    "chat_history": [AIMessage(content=full_text)],
}
```

- 非 0 終了でも、**部分テキストが取れていればそれを返す**（部分回答優先）。空なら定型エラー文に差し替え
- 戻り値の `chat_history` は [states.py](src/application/states.py) で `Annotated[..., add_messages]` されているため、**置換ではなくマージ**（末尾追加）される。ユーザーの `HumanMessage` は既に入っている前提で、ここは AI 応答のみ返す

---

## エラーハンドリングの 3 経路

このノードはどの経路でも **例外を投げず、`AIMessage` を含む dict を返す** ことで LangGraph を止めない設計になっている:

| 経路 | 発生条件 | 処理 |
| --- | --- | --- |
| (a) **CLI 未インストール** | `FileNotFoundError` (L204) | ログに残してエラー文を返す |
| (b) **タイムアウト** | `TimeoutError` (L216) | `proc.kill()` + `proc.wait()` してエラー文を返す |
| (c) **非 0 終了** | `proc.returncode != 0` (L225) | 部分テキストがあれば採用、なければエラー文 |

---

## 補助関数の位置づけ（まとめ）

| 関数 | 呼ばれる場所 | 責務 |
| --- | --- | --- |
| `_build_command` | Step 2 | CLI オプションリストの組み立て |
| `_drain_stderr` | Step 4 | stderr を末尾まで読み切る（デッドロック防止） |
| `_process_stream` | Step 5 | stdout を 1 行ずつ読み `_handle_event` に委譲 |
| `_handle_event` | Step 5 の内部 | イベント種別ごとの dispatch ディスパッチャ |
| `_extract_assistant_text` | `_handle_event` の内部 | content blocks → 結合テキスト |
| `_dispatch_token` / `_dispatch_progress` | `_handle_event` の内部 | LangChain カスタムイベント発行 |

`claude_code` 本体は **段取り（オーケストレーション）だけ** を担当し、個々の処理は補助関数に分離されている。LangGraph ノードとしての「状態受け取り→処理→状態返却」の輪郭が読みやすい構造。

---

## 一言まとめ

このノードの本質は、

> **「CLI が吐く JSONL を 1 行ずつ捌きながら、トークンを `adispatch_custom_event` で上位に投げ、最後にプロセスを綺麗に看取って、最終テキストを LangGraph State に返す」**

という 1 行に集約される。

ストリーミングの "流し込み" は Step 5 の中で起きており、Step 6 以降はあくまで **プロセスの終わり方を綺麗にするための後始末**。`proc.wait()` は「配信」ではなく「看取り」のための処理と理解するとよい。

---

## 関連ドキュメント

- [claude_code_node_explain.md](claude_code_node_explain.md) — 同じファイルの関数ごと詳解（本書と対になる）
- [claudecode_archi.md](claudecode_archi.md) — プロジェクト全体のアーキテクチャ
- [src/application/stream.py](src/application/stream.py) — イベント変換・ストリーミング層
- [src/application/states.py](src/application/states.py) — `State` TypedDict 定義
- [src/common/settings/app.py](src/common/settings/app.py) — `claude_code_*` 設定
