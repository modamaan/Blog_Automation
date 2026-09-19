from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # OpenAI
    openai_api_key: str

    # DevBlog REST API
    devblog_base_url: str = "https://www.devblog.blog"
    devblog_api_secret_key: str

    # Telegram
    telegram_bot_token: str
    telegram_chat_id: str

    # Database
    database_url: str
    database_url_sync: str

    # Redis
    redis_url: str = "redis://localhost:6381"

    # Pipeline limits
    max_cost_per_run_usd: float = 1.00
    topic_cooldown_hours: int = 168

    # Optional search
    serper_api_key: str | None = None

    @property
    def devblog_posts_url(self) -> str:
        return f"{self.devblog_base_url.rstrip('/')}/api/posts"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
