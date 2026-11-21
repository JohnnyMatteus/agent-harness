from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class GitHubConfig(BaseSettings):
    """Variáveis FORJA_GITHUB_*; segredos como SecretStr para não vazarem em repr ou log."""

    model_config = SettingsConfigDict(env_prefix="FORJA_GITHUB_", extra="ignore")

    webhook_secret: SecretStr
    app_id: str = ""
    api_url: str = "https://api.github.com"
    max_corpo_bytes: int = 1_048_576
