from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ClaudeCodePermissionMode = Literal["default", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "auto"]


class AppSettings(BaseSettings):
    """アプリケーション設定."""

    model_config = SettingsConfigDict(env_prefix="APP_", frozen=True)

    config_yaml_path: str = "/app/config/app.yaml"
    prompts_dir: str = "/app/prompts"
    a2a_base_url: str = "http://host.docker.internal:8102/a2a/"
    claude_code_backend: Literal["cli", "sdk"] = "sdk"
    claude_code_cli_path: str = "claude"
    # 0 以下なら無制限 (Claude が必要なだけターンを使う).
    claude_code_max_turns: int = 0
    claude_code_timeout: int = 300
    # サーバ非対話コンテキストでツール (Bash 等) を使えるようにする.
    # None にすると CLI デフォルト (= 権限プロンプト要) になり、サーバ実行では応答できないため失敗する.
    # ``bypassPermissions`` は root 実行下では Claude Code CLI 側でブロックされるため、
    # コンテナ実行を考慮して ``auto`` を既定値にしている.
    claude_code_permission_mode: ClaudeCodePermissionMode | None = "auto"
    log_level: str = "INFO"


settings = AppSettings()
