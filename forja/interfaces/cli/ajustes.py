from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Ajustes(BaseSettings):
    """Configuração do binário, lida do ambiente (.env.example documenta cada variável)."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    redis_url: str = Field("redis://localhost:6379/0", validation_alias="REDIS_URL")
    temporal_address: str = Field("localhost:7233", validation_alias="TEMPORAL_ADDRESS")
    temporal_namespace: str = Field("default", validation_alias="TEMPORAL_NAMESPACE")
    otlp_endpoint: str | None = Field(
        None,
        validation_alias=AliasChoices("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "FORJA_OTLP_ENDPOINT"),
    )
    # Vazio recusa toda ativação (falha fechada): o operador lista os repositórios habilitados.
    repos_habilitados: Annotated[list[str], NoDecode] = Field(
        default_factory=list, validation_alias="FORJA_REPOS_HABILITADOS"
    )
    repos_dir: Path = Field(Path("data/repos"), validation_alias="FORJA_REPOS_DIR")
    worktrees_dir: Path = Field(Path("data/worktrees"), validation_alias="FORJA_WORKTREES_DIR")
    # Efeito externo tem dry-run por padrão: só `FORJA_PUBLICAR=true` escreve no GitHub.
    publicar: bool = Field(False, validation_alias="FORJA_PUBLICAR")
    panico_token_sha256: str = Field("", validation_alias="FORJA_PANICO_TOKEN_SHA256")
    api_host: str = Field("127.0.0.1", validation_alias="FORJA_API_HOST")
    api_porta: int = Field(8000, validation_alias="FORJA_API_PORTA")
    metricas_porta: int = Field(9102, validation_alias="FORJA_METRICAS_PORTA")
    # RAG do M2: sem os dois, a spec sai sem fontes. O embedder real é decisão pendente do autor.
    database_url: str | None = Field(None, validation_alias="DATABASE_URL")
    embedder: str | None = Field(None, validation_alias="FORJA_EMBEDDER")
    # Build de longa duração (M4). Exige publicação ligada, banco da memória e imagem com o CLI.
    harness: bool = Field(False, validation_alias="FORJA_HARNESS")
    # Aceite explícito de um risco conhecido (ADR 0040): a chave da API chega ao processo do CLI,
    # que roda no mesmo container e uid do código do repositório.
    harness_aceita_chave_no_sandbox: bool = Field(
        False, validation_alias="FORJA_HARNESS_ACEITA_CHAVE_NO_SANDBOX"
    )
    imagem_agente: str = Field(
        "forja-agente:latest", validation_alias="FORJA_SANDBOX_IMAGEM_AGENTE"
    )
    modelo_avaliador: str | None = Field(None, validation_alias="FORJA_MODELO_AVALIADOR")
    tamanho_do_bloco: int = Field(3, validation_alias="FORJA_TAMANHO_DO_BLOCO")
    modelo: str | None = Field(None, validation_alias="FORJA_MODELO")

    @field_validator("repos_habilitados", mode="before")
    @classmethod
    def _lista(cls, v: object) -> object:
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v

    @classmethod
    def do_ambiente(cls) -> Ajustes:
        return cls()  # pyright: ignore[reportCallIssue]  # campos vêm do ambiente, por alias
