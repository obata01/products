## プロジェクト構成
※一部抜粋

```
src/
├── common/
│   ├── settings/        # 設定情報
│   ├── defs/            # 型定義、Enum、Pydanticモデル等の定義
│   ├── di/              # 依存性注入（dependency-injector）
│   ├── exceptions/      # カスタム例外
│   ├── lib/             # ロギング等、全体で使うユーティリティ
│   └── schema/          # APIリクエスト/レスポンススキーマ
├── components/          # 他に依存しない技術コンポーネント（コピペで動くレベル）
│   └── llms/            # LangChain LLMクライアント（ファクトリ付き）
├── application/
│   ├── nodes/           # LangGraphノード
│   ├── workflows/       # LangGraphワークフロー定義
│   └── services/        # ユースケース
├── scripts/             # 動作確認スクリプト
│   └── ...
├── main.py              # FastAPIエントリポイント
└── gunicorn.conf.py     # Gunicorn設定
tests/                   # テストコード
config/                  # 設定ファイル（YAML等）
prompts/                 # プロンプトテンプレート
```


## アーキテクチャ方針

- シンプルな2層（application + components）+ common構成
- 高度なDDDパターンは採用しない
- `components/` は外部ライブラリのみに依存し、application層には依存しない（コピペで動くレベル）
- `application/` は `components/` をimportしてビジネスロジックを組み立てる（逆方向の依存はない）
- `common/` は設定とDIを提供し、components/applicationの両方から参照される
- FastAPIは `src/main.py` に配置する（presentation層は設けない）
- 依存性注入（dependency-injector）でコンポーネント間を疎結合にする
- LLMClientはファクトリ関数でプロバイダ（OpenAI / Bedrock / Azure等）を出し分けるシンプルな設計
