from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """アプリケーション設定."""

    model_config = SettingsConfigDict(env_prefix="APP_", frozen=True)

    sample_agent_api_url: str = "http://host.docker.internal:8102/claude-code"
    sample_agent_a2a_url: str = "http://host.docker.internal:8102/a2a"


settings = AppSettings()
