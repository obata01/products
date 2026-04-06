from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """アプリケーション設定."""

    model_config = SettingsConfigDict(env_prefix="APP_", frozen=True)


settings = AppSettings()
