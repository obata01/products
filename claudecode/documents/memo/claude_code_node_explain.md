# `src/application/nodes/claude_code.py` 解説

## 概要

Claude Code CLI をサブプロセスとして起動し、ユーザーメッセージを処理する LangGraph ノード。CLI の `stream-json` 出力を 1 行ずつパースし、**トークン（生成テキストの差分）** と **進捗メッセージ**（ツール実行など）を LangChain の「カスタムイベント」として流すことで、LangGraph の `astream_events` 経由でフロントエンドへリアルタイム配信できるようにする。ファイル I/O は行わずメモリ上で完結する。

- レイヤー: `application/nodes/`（LangGraph ノード）
- 責務: Claude Code CLI の実行・出力パース・イベント変換・最終テキストの `chat_history` への反映
- 上位の抽象化: [src/application/stream.py](src/application/stream.py) の `stream_graph_events` が `ON_CUSTOM_EVENT` を拾って `GraphEvent`（TOKEN / PROGRESS）に変換し、さらに `StreamEvent` として SSE / A2A クライアントへ届く

## 依存関係

| 依存先 | 役割 |
| --- | --- |
| `asyncio` | サブプロセスの非同期実行、stdout/stderr の並行読み取り、タイムアウト制御 |
| `json` | stream-json の各行（= 1 JSON オブジェクト）をパース |
| `langchain_core.callbacks.adispatch_custom_event` | LangChain のコールバック機構に **カスタムイベント** を流し込む。`astream_events(version="v2")` 側で `on_custom_event` として拾える |
| `langchain_core.messages.AIMessage` | ノードの最終出力として `chat_history` に積むための LangChain メッセージ型 |
| [src/application/stream.py](src/application/stream.py) | `CLAUDE_CODE_TOKEN_EVENT` / `CLAUDE_CODE_PROGRESS_EVENT` 定数。ノード側とストリーム変換側で共通のイベント名を持つための単一の真実の源 |
| [src/common/settings/app.py](src/common/settings/app.py) | `claude_code_cli_path` / `claude_code_max_turns` / `claude_code_timeout` の 3 設定 |
| [src/application/states.py](src/application/states.py) の `State` | `last_user_message` を読み、`chat_history` に `AIMessage` を追加する |

呼び出し関係:
- 上流: LangGraph ワークフロー（`application/workflows/`）がこのノードを `claude_code` としてグラフに組み込む
- 下流: Claude Code CLI（`claude` コマンド）。ローカルにインストール済みの前提で subprocess として起動される

## 行毎の処理解説

### 1. 定数とロガー（L1〜L28）

```python
_ERROR_MESSAGE = "Claude Code の処理中にエラーが発生しました。"
```

エラー時にユーザーへ返す定型文。CLI 起動失敗・タイムアウト・非 0 終了の 3 経路で同じ文言を使うため定数化している。

`TYPE_CHECKING` ブロックで `RunnableConfig` と `State` を import しているのは、実行時 import のコストを避け、かつ循環 import を防ぐため（Python の型ヒントは `from __future__ import annotations` により文字列として遅延評価される）。

### 2. `_extract_assistant_text`（L31〜L44）

Claude Code CLI が `assistant` イベントで返す `message.content` は **content blocks の配列**（`{"type": "text", "text": "..."}` など）。ここから `type == "text"` のブロックのみ抜き出して結合する。`tool_use` ブロックなどはテキスト出力には含めない。

`isinstance(block, dict)` ガードは、CLI 側の仕様変更で非 dict が紛れても例外で落ちないようにするための防御的チェック。

### 3. `_dispatch_token` / `_dispatch_progress`（L47〜L64）

```python
await adispatch_custom_event(CLAUDE_CODE_TOKEN_EVENT, {"text": delta}, config=config)
```

`adispatch_custom_event` は LangChain が提供する API で、呼び出し時点で有効なコールバックに「ユーザー定義イベント」を送る。`config` を渡すことで **LangGraph が自動注入する run_id / langgraph_node メタデータ** が紐付き、`astream_events` 側で「どのノードで発火したイベントか」が分かる。

イベント名と `data` のキーは [stream.py](src/application/stream.py) の `_CUSTOM_EVENT_PARSERS` / `_CUSTOM_EVENT_TEXT_KEYS` と対になっている（TOKEN は `text`、PROGRESS は `message`）。ここを変えるなら両側を揃える必要がある。

### 4. `_build_command`（L67〜L88）

Claude Code CLI のオプションを組み立てる:

| オプション | 意味 |
| --- | --- |
| `-p <message>` | **非対話モード**（print mode）。プロンプトを引数で渡し、結果を stdout に吐いて終了 |
| `--output-format stream-json` | 各イベントを 1 行 1 JSON で出力する（JSONL）。これをパースすることでストリーミング再現が可能になる |
| `--verbose` | stream-json 時は必須（CLI 側の仕様。省略するとメタイベントが欠落する） |
| `--include-partial-messages` | 生成途中の `assistant` イベントを逐次出力させる。これがないと最終 `result` までテキストが届かずリアルタイム性が出ない |
| `--max-turns <N>` | エージェントの自律ターン数の上限。`0` 以下なら付けない（= CLI デフォルトに委譲） |

L78 のコメント `# NOTE: --bare は OAuth 認証と併用すると認証エラーになるため除外` は過去に踏んだ落とし穴の記録。`--bare` を再び付けたくなったら OAuth 認証環境で検証すること。

### 5. `_drain_stderr`（L91〜L103）

`proc.stderr.read()` で **stderr を末尾まで一括読み**する単純な実装。ポイントは「なぜこれが必要か」で、stdout を `async for` で読みつつ stderr を放置すると、**OS のパイプバッファ（Linux では既定 64KB 程度）が満杯になった瞬間にサブプロセスの write がブロック → stdout も止まりデッドロック**する。これを防ぐため、`asyncio.create_task` で並行に読み続ける（L209 で起動）。

`decode("utf-8", errors="replace")` は、途中で切れた UTF-8 バイト列などが混じっても例外を出さず `?` で置換する。エラー表示用の best-effort デコード。

### 6. `_handle_event`（L106〜L145）

stream-json の 1 イベントを種別ごとに処理するディスパッチャ。戻り値は `(full_text, prev_len)` で、呼び出し側は返ってきたタプルで状態を更新する（この関数自身は状態を持たない）。

- **`assistant`**: `--include-partial-messages` により同じ会話のテキストが **累積で届く** ため、前回までの長さ `prev_len` を引き算して差分（デルタ）のみトークンイベントとして送出する。デルタが空（変化なし）ならイベント発火しないが、`prev_len` は最新テキスト長で更新しておくと次回以降の計算が壊れない
- **`result`**: CLI の最終出力イベント。`event["result"]` に最終テキストが入るので `full_text` として採用する
- **`system` + `subtype=="init"`**: セッション開始時に一度だけ進捗通知
- **`tool_use`**: ツール名を進捗メッセージに含めて通知。CLI バージョンによりキーが `tool` だったり `name` だったりするため両対応

### 7. `_process_stream`（L148〜L176）

```python
async for raw_line in proc.stdout:
```

`asyncio.subprocess.Process.stdout` は `asyncio.StreamReader` で、`async for` で **1 行単位に非同期読み出し**できる（内部で `\n` で区切る）。

各行について:
1. UTF-8 デコードして strip、空行はスキップ
2. `json.loads` で dict 化。パース失敗は `logger.debug` で先頭 200 文字だけログに残し、処理を続行（壊れた行で全体を止めない）
3. `_handle_event` に委譲して状態を更新

最終的に蓄積した `full_text` を返す。

### 8. `claude_code` 本体（L179〜L234）

ノードとして LangGraph から呼ばれるエントリーポイント。

```python
message = state["last_user_message"]
cmd = _build_command(message)
```
State から最新のユーザー入力を取り出し、CLI コマンドを組み立てる。

```python
proc = await asyncio.create_subprocess_exec(
    *cmd,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
```
`asyncio.create_subprocess_exec` は **シェルを介さず** 引数を直接渡す（シェルインジェクションのリスクがない）。`*cmd` でリストを展開する形。`FileNotFoundError` は CLI バイナリが存在しない場合に発生するので、ここだけ例外を握って `AIMessage` を返す。

```python
stderr_task = asyncio.create_task(_drain_stderr(proc))
```
stderr 読み取りをバックグラウンドタスク化。stdout 処理と並行に走る。

```python
full_text = await asyncio.wait_for(
    _process_stream(proc, config),
    timeout=settings.claude_code_timeout,
)
```
`asyncio.wait_for` は指定秒を超えたら `TimeoutError` を送出する。タイムアウト時は `proc.kill()`（SIGKILL）で強制終了してから `proc.wait()` で zombie 化を防ぎつつエラーメッセージを返す。

```python
await proc.wait()
stderr_text = await stderr_task
```
正常経路では stream 読み終わり = stdout クローズなので、プロセス終了をここで確定させる。stderr タスクも完了を待ち合わせる。

```python
if proc.returncode != 0:
    ...
    if not full_text:
        full_text = _ERROR_MESSAGE
```
非 0 終了でも、途中まで生成できたテキストがあればそれを返す（部分回答優先）。空なら定型エラー文に差し替える。

```python
return {"chat_history": [AIMessage(content=full_text)]}
```
`State` の `chat_history` は [states.py](src/application/states.py) で `Annotated[..., add_messages]` 指定されているため、返した dict の `chat_history` は **置換ではなくマージ**（LangGraph の `add_messages` reducer が末尾追加）される。そのためユーザーメッセージ（`HumanMessage`）は既に `chat_history` に入っている前提で、ここは AI 応答のみ返せばよい。

## 仕様・設計上のポイント

- **ストリーミング設計の肝**: CLI の JSONL を `adispatch_custom_event` に橋渡しするだけで、LangChain/LangGraph のイベント機構に一本化できる。上位の [stream.py](src/application/stream.py) は `GraphEventKind.TOKEN` / `PROGRESS` しか知らず、Claude Code 固有の事情を知らない。この抽象化の切れ目が綺麗
- **差分計算の根拠**: `--include-partial-messages` は「途中経過を含む assistant イベント」を流すだけで、**差分を計算してくれるわけではない**。そのため `prev_len` を保持して自前で差分を取る必要がある。この仕様を知らないと「同じテキストが重複して見える」バグを生みやすい
- **パイプバッファのデッドロック対策**: `_drain_stderr` の並行実行は、`asyncio` サブプロセスの定番ハマりどころ。将来 stderr を無視したくなっても、「消費する」こと自体は続ける必要がある
- **エラーハンドリングの 3 経路**: (a) CLI 未インストール = `FileNotFoundError`、(b) タイムアウト = `TimeoutError` + `kill`、(c) 非 0 終了 = 部分テキスト優先、の 3 つで粒度を変えている。いずれもノードとしては正常に return して LangGraph を止めない設計
- **ファイル I/O しない理由**: サーバプロセス（FastAPI）内で動くので、Claude Code が書き込むファイルが残るとステートレス性が崩れる。`-p` モードだけを使い、ツール実行の副作用はメモリ上の stdout だけで受け取る
- **制約**: `claude_code_max_turns=0` にすると無制限になる（CLI のデフォルト動作に委譲）点は、設定値の意図が曖昧になりやすい。`0` 特別扱いの条件分岐が L86 にある

## 参考

- LangChain Custom Events: https://python.langchain.com/docs/how_to/callbacks_custom_events/
- LangGraph `astream_events`（v2）: https://langchain-ai.github.io/langgraph/how-tos/streaming/
- Python `asyncio.subprocess`（パイプとデッドロック）: https://docs.python.org/3/library/asyncio-subprocess.html
- 関連ファイル:
  - [src/application/stream.py](src/application/stream.py) — カスタムイベント → GraphEvent → StreamEvent の変換
  - [src/application/states.py](src/application/states.py) — `State` TypedDict と `add_messages` リデューサ
  - [src/common/settings/app.py](src/common/settings/app.py) — `claude_code_*` 設定
  - [documents/memo/claudecode_archi.md](documents/memo/claudecode_archi.md) — アーキテクチャ全体像（既存）

## 要確認事項

- Claude Code CLI の `--include-partial-messages` で流れる `assistant` イベントが **厳密に累積テキストを返すか**、最終 `result` との差分仕様は CLI のバージョンにより変動しうる。リリースノートを当たること
- `tool_use` イベントのキー名（`tool` / `name`）は CLI バージョン差を想定した両対応になっているが、現行バージョンで実際にどちらが来るかは一次情報未確認

---

## 付録: `asyncio.create_subprocess_exec` 詳解（初心者向け）

```python
proc = await asyncio.create_subprocess_exec(
    *cmd,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
```

やっていることは「**別のプログラム（Claude Code CLI）を子プロセスとして起動し、その入出力を Python から読めるように配線する**」だけ。以下、要素ごとに分解する。

### 1. 「シェルを介さず」とは？

Python から外部コマンドを実行する方法は大きく 2 つ。

#### A) シェル経由（`create_subprocess_shell`）

```python
await asyncio.create_subprocess_shell("claude -p hello")
```

- OS の **シェル**（Linux なら `/bin/sh`、Windows なら `cmd.exe`）を起動し、そこに文字列 `"claude -p hello"` を渡す
- シェルが文字列をパースして「コマンド名」「引数」に分解し、`claude` を起動する
- シェル機能（`|`・`>`・`*`・`$VAR` 展開・`;` など）が使える

#### B) シェルを介さず直接起動（`create_subprocess_exec` ← **今回これ**）

```python
await asyncio.create_subprocess_exec("claude", "-p", "hello")
```

- シェルを挟まず、**Python が直接** `claude` という実行ファイルを起動する
- 引数は **最初からリストで分解済み** で渡す（`["claude", "-p", "hello"]`）
- シェル機能は使えない（`|` と書いても「パイプ」ではなくただの文字列になる）

#### なぜ今回 B を選ぶのか？ — セキュリティと確実性

ユーザー入力 `message` をシェル経由で渡すと、もしユーザーが

```
hello; rm -rf /
```

と送ってきた場合、シェルは `;` を「コマンドの区切り」と解釈して **`rm -rf /` が実行されてしまう**（= シェルインジェクション）。

一方 `create_subprocess_exec` は引数を **1 個の文字列としてそのまま** `claude` に渡すので、`claude` 側から見れば「`hello; rm -rf /` というプロンプト文字列」でしかなく、シェル解釈は一切起こらない。

> **ルール**: ユーザー入力が引数に混ざるときは必ず `exec` 系（リスト渡し）を使う。`shell` 系（文字列渡し）は避ける。

#### `*cmd` の意味

`cmd` は `_build_command` が返したリスト、たとえば

```python
["claude", "-p", "hello", "--output-format", "stream-json", "--verbose", ...]
```

`*cmd` は Python のアンパック構文で、リストを **複数の位置引数に展開** する。

```python
await asyncio.create_subprocess_exec(
    "claude", "-p", "hello", "--output-format", "stream-json", "--verbose", ...,
    stdout=..., stderr=...,
)
```

と書いたのと等価。

### 2. stdout / stderr の役割

すべての Unix 系プロセスには「**3 本の標準ストリーム**」がある。

| 番号 | 名前 | 役割 | 例 |
| --- | --- | --- | --- |
| 0 | stdin（標準入力） | プロセスへの **入力** | キーボード、パイプの左側 |
| 1 | **stdout**（標準出力） | プロセスの **通常の出力** | `print()` の結果、計算結果、JSON など |
| 2 | **stderr**（標準エラー出力） | プロセスの **エラー・ログ・警告** | エラーメッセージ、進捗表示 |

ターミナルで `claude ...` を直接叩くと、stdout も stderr も **画面に混ざって表示される** ので違いが見えにくいが、実は 2 本の別チャンネル。

#### 今回のケース

Claude Code CLI は:
- **stdout** に → `stream-json` 形式の JSONL（1 行 1 JSON）を流す。**これがメインの成果物**
- **stderr** に → エラー・警告・デバッグログを流す。CLI 実行が失敗したときの原因調査に使う

Python 側で両方を「読める状態」にしておきたいので、両方に `PIPE` を指定する。

### 3. `PIPE` って何？

`asyncio.subprocess.PIPE` は「このストリームを **Python とつながるパイプ（細い管）** にしてください」という指示。

#### PIPE を指定しない場合（デフォルト）

```python
proc = await asyncio.create_subprocess_exec("claude", "-p", "hello")
```

- stdout / stderr は **親プロセス（= Python プロセス）のものをそのまま引き継ぐ**
- つまり CLI の出力は **Python を動かしているターミナルに直接表示される**
- Python のコードからは **読めない**

#### PIPE を指定した場合（今回）

```python
stdout=asyncio.subprocess.PIPE,
stderr=asyncio.subprocess.PIPE,
```

イメージ図:

```
   Claude Code CLI              Python
  ┌──────────────┐             ┌──────────────┐
  │              │ stdout ───▶ │ proc.stdout  │ ← async for で読める
  │              │             │              │
  │              │ stderr ───▶ │ proc.stderr  │ ← read() で読める
  └──────────────┘             └──────────────┘
```

- CLI が `print("...")` などで stdout に書くと、そのバイト列が **パイプというバッファ** を通って Python の `proc.stdout` から読めるようになる
- stderr も同様に `proc.stderr` から読める
- 画面には **一切表示されない**（Python が奪い取った状態）

コードで使っている部分:
- stdout を読む: L164 `async for raw_line in proc.stdout:`
- stderr を読む: L102 `data = await proc.stderr.read()`

### 4. なぜ stderr も PIPE にするのか？ — 「読まないと詰まる」問題

「エラーログなんて要らないんだから stderr は PIPE にしなくていいのでは？」と思うかもしれない。でも **PIPE にした以上、必ず読まないとマズい**。

#### パイプの正体

パイプには **容量**（バッファ）がある。Linux だと通常 **64 KB** 程度。

```
CLI ──書き込み──▶ [ パイプ(64KB) ] ──読み取り──▶ Python
```

- CLI が書く速度 > Python が読む速度、だとバッファが溜まる
- バッファが満杯になると、**CLI 側の「書く」操作がブロックされる**（書けるようになるまで待つ）
- CLI は stdout と stderr の両方に書いている。**片方でも詰まれば CLI 全体が止まる**

#### 何が起きるか（デッドロックのシナリオ）

もし stderr を PIPE にしたまま **読まずに放置** すると:

1. Python は stdout を `async for` でせっせと読んでいる
2. CLI は stderr にもログを吐き続けている
3. stderr のパイプバッファが 64 KB で満杯になる
4. CLI の **stderr への write() がブロック** → CLI が止まる
5. CLI が止まるので stdout にも何も書かなくなる
6. Python の `async for` は「次の行が来ない…」と永遠に待つ
7. **デッドロック完成**（お互いに待ち合って永久に進まない）

#### 解決策 = 並行して読む

だから L209 でこうしている:

```python
stderr_task = asyncio.create_task(_drain_stderr(proc))
```

`_drain_stderr` を **別タスクとしてバックグラウンド起動** しておき、stdout を読む裏で stderr もずっと消費し続ける。こうすればパイプが詰まらず、CLI も止まらない。

`drain`（ドレイン）は「排水する／吸い出す」という意味。**「溜まらないように吸い続ける」** ことが目的なので、読んだ内容は最後にエラー時のログとして使うだけで、処理の主役ではない。

### 5. まとめ表

| 要素 | 何をしている？ | なぜそうする？ |
| --- | --- | --- |
| `create_subprocess_exec` | シェルを介さず直接 CLI を起動 | シェルインジェクション防止。ユーザー入力が引数に混ざるから |
| `*cmd` | リストを位置引数に展開 | `exec` 系は 1 引数 1 要素のリストで渡す規約 |
| `stdout=PIPE` | CLI の標準出力を Python が読めるように配線 | stream-json を 1 行ずつパースするため |
| `stderr=PIPE` | CLI のエラー出力を Python が読めるように配線 | 失敗時の原因ログ取得＋**パイプ詰まり防止で読み切る必要あり** |

一言で: **「シェルを使わず安全に CLI を起動し、その出力 2 本をどちらも Python の中に引き込んで、自前でストリーム処理するための構え」**。

---

## 付録: このパターンが役立つ他のシチュエーション

このノードで使っている要素技術は、「外部プロセス（自作でも他社製でも）からストリーム出力を受け取り、アプリ内のイベント機構に橋渡しする」という汎用パターンになっている。以下、同じ構えが効く典型ケースを紹介する。

### 1. 他の CLI ツールをノード化する（LangGraph 文脈）

Claude Code CLI と同様に **JSONL / SSE で出力するエージェント系 CLI** は多く、同じ構造で LangGraph ノードに包める:

| CLI | 出力形式 | 使い所 |
| --- | --- | --- |
| `codex` / `aider` / `gemini-cli` | 各社固有の JSON ストリーム | 別エージェントをサブノードとして組み込み、結果を比較・アンサンブル |
| `gh copilot suggest` | テキスト | CLI 補助をワークフロー化 |
| `ollama run --format json` | JSONL | ローカル LLM を LangGraph ノードとして使う |

ポイント: 「CLI 固有の出力仕様 → `adispatch_custom_event`」の変換層さえ作れば、上位（[stream.py](src/application/stream.py)）は何も変えなくていい。**プロバイダを増やす = ノードを増やすだけ** の構造。

### 2. メディア / ビルド系の長時間プロセスの進捗監視

CLI を叩いて進捗を UI に出したいケースはほぼ全部このパターン:

- **ffmpeg**: `-progress pipe:1` で進捗を stdout に JSON 風で吐ける → 動画変換の進捗バー
- **docker build** / **docker compose up**: `--progress=plain` でログをそのまま stdout へ → CI ログのリアルタイム配信
- **npm install** / **pip install**: 進捗メッセージを拾って WebSocket で配信
- **terraform apply** / **ansible-playbook**: 適用状況をリアルタイムで可視化
- **pytest -v**: テスト結果を 1 件ずつ拾って ダッシュボードに反映

全部「stdout を 1 行ずつ読んで、意味のあるイベントに変換し、内部 bus に流す」= この実装の焼き直しで書ける。

### 3. セキュリティ境界で外部コマンドを呼ぶ全般

**ユーザー入力が引数に混ざる箇所** では `create_subprocess_exec`（リスト渡し）が定石:

- Web サービスでアップロードファイルに `ffmpeg` / `imagemagick` / `pandoc` をかける変換 API
- ユーザー名やリポジトリ名を `git clone` / `git log` に渡すコード検索サービス
- チャットボットから `kubectl` / `aws` などを叩くオペレーション BOT
- CTF 問題サーバで受け取った入力をサンドボックス実行する仕組み

合わせて使うべきテクニック:
- 引数を **allowlist 方式** でバリデーション（CLI のフラグ追加も拒否）
- `cwd=` を明示して作業ディレクトリを固定
- `timeout` と `proc.kill()` でリソース保護
- `resource.setrlimit` や cgroups / コンテナで二重の隔離

### 4. パイプバッファのデッドロック対策が必要な場面

「stdout / stderr の両方 PIPE & 並行 drain」は以下でも必要:

- **ビルドツール（cargo, maven, gradle など）**: stderr にログ、stdout に成果情報を分けて吐くものが多い
- **静的解析ツール（ruff, mypy, eslint）**: 大量の警告を stderr に出すため、読まないと詰まる
- **LLM ローカル推論（llama.cpp サーバ起動など）**: 起動ログが大量
- **ML トレーニングスクリプト**: 学習ログを放置するとトレーニングが止まる

教訓: **PIPE にしたら必ず読む。読まないなら `subprocess.DEVNULL` にリダイレクトして捨てる**。中途半端が一番危険。

```python
# 読まないなら捨てる
stderr=asyncio.subprocess.DEVNULL
```

### 5. `adispatch_custom_event` の応用（LangChain 文脈）

「内部で何か起きた → 上位のストリームに通知したい」全般に使える:

- **RAG の検索中**: ベクトル検索ヒット件数・再ランキング経過を PROGRESS として配信
- **ツール実行ノード**: API コール先・レスポンスサイズなどを逐次通知
- **長時間のバッチ処理**: 進捗率 N% を定期 dispatch してフロントの進捗バーに反映
- **デバッグ可視化**: 本番では OFF にできる、ノード内部の中間状態を開発時のみフロントへ流す

コツ: **イベント名とデータ構造をプロジェクト内で定数化**（本プロジェクトでは [stream.py](src/application/stream.py) の `CLAUDE_CODE_TOKEN_EVENT` 等）。発行側と受信側の「契約」が 1 箇所にまとまるので、追加・変更が壊れにくい。

### 6. `asyncio.wait_for` + `create_task` の使いどころ

「タイムアウト付きの非同期処理」+「バックグラウンドでの並行タスク」の組み合わせは応用範囲が広い:

- **外部 API 呼び出しに SLA を持たせる**: ネットワーク越しのリクエストを `wait_for` で囲む
- **WebSocket / SSE の keep-alive**: 本処理とは別タスクで ping を送り続ける
- **複数 LLM の並列呼び出し + 早いもの勝ち**: `asyncio.wait(..., return_when=FIRST_COMPLETED)` との組み合わせ
- **クリーンアップの並行実行**: メイン処理が終わったあと、ログ送信や一時ファイル削除を裏で走らせる

注意点: `create_task` で起動したタスクは **必ず `await` または `cancel` する**。放置すると `Task was destroyed but it is pending!` 警告やリークの原因になる。本コードでは L223 `await stderr_task` で回収している。

### 7. JSONL / ストリーム parse パターンの一般性

`async for line in stream: json.loads(line.strip())` は JSONL を扱う普遍的なイディオム:

- **LLM API の SSE レスポンス**: OpenAI / Anthropic / Bedrock などのストリームを直接 parse
- **ログ集約**: fluentd / Vector / Loki などが吐く JSONL を処理
- **データ ETL**: BigQuery export、Firebase export などの JSONL ファイル
- **監視メトリクス**: Prometheus の `/metrics` や OpenTelemetry のストリーム

共通の注意点:
- **1 行壊れてても全体を止めない**（本コードの `json.JSONDecodeError` を debug ログに落として continue）
- **巨大な 1 行に備える**: `StreamReader` のデフォルト上限（64KB）を超えるなら `limit=` を引き上げる
- **バイナリ境界**: `decode("utf-8", errors="replace")` で best-effort にする

### まとめ

このノードで使っている 5 つの要素 — **(a) 安全なサブプロセス起動 / (b) stdout/stderr 両 PIPE / (c) 並行 drain / (d) JSONL ストリーム parse / (e) カスタムイベント経由で上位に通知** — は、それぞれ単独でも「外部プロセスと非同期に付き合う」ほぼ全ての場面で使える。覚えておくと、CLI 連携、ビルド自動化、AI エージェント拡張、長時間処理の可視化など幅広く応用できる。
