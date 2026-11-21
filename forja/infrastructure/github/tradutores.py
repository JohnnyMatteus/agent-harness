"""ACL do GitHub: payloads de webhook viram comandos da aplicação (ADR 0010).

Campos desconhecidos são ignorados; payload sem o essencial vira `Ignorado`, nunca exceção.
O texto de issues e comentários é dado: aqui só se reconhece um comando exato.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from forja.application.comandos import CriarIntent, Ignorado, OrigemExterna, Parar, Traducao

LABEL_INTENT = "forja:intent"
_COMANDO = re.compile(r"^/forja\s+(\S+)\s*$", re.IGNORECASE)


class _Modelo(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _Usuario(_Modelo):
    login: str
    type: str = "User"


class _Repositorio(_Modelo):
    full_name: str


class _Issue(_Modelo):
    number: int
    title: str
    body: str | None = None
    html_url: str
    pull_request: dict[str, Any] | None = None


class _Label(_Modelo):
    name: str


class _EventoIssue(_Modelo):
    action: str
    issue: _Issue
    repository: _Repositorio
    sender: _Usuario
    label: _Label | None = None


class _Comentario(_Modelo):
    body: str
    user: _Usuario


class _EventoComentario(_Modelo):
    action: str
    issue: _Issue
    repository: _Repositorio
    comment: _Comentario


def traduzir(evento: str, payload: dict[str, Any]) -> Traducao:
    match evento:
        case "issues":
            return _traduzir_issue(payload)
        case "issue_comment":
            return _traduzir_comentario(payload)
        case "ping":
            return Ignorado("ping")
        case _:
            return Ignorado(f"evento sem suporte no M1: {evento}")


def _traduzir_issue(payload: dict[str, Any]) -> Traducao:
    try:
        evento = _EventoIssue.model_validate(payload)
    except ValidationError:
        return Ignorado("payload de issues sem os campos essenciais")
    if evento.action != "labeled" or evento.label is None or evento.label.name != LABEL_INTENT:
        return Ignorado("issue sem o label forja:intent")
    if evento.sender.type == "Bot":
        return Ignorado("evento de bot")
    return CriarIntent(
        origem=_origem(evento.repository, evento.issue),
        titulo=evento.issue.title,
        corpo=evento.issue.body or "",
        autor=evento.sender.login,
    )


def _traduzir_comentario(payload: dict[str, Any]) -> Traducao:
    try:
        evento = _EventoComentario.model_validate(payload)
    except ValidationError:
        return Ignorado("payload de comentário sem os campos essenciais")
    if evento.action != "created":
        return Ignorado("comentário não criado")
    if evento.comment.user.type == "Bot":
        return Ignorado("comentário de bot")
    comando = _extrair_comando(evento.comment.body)
    if comando is None:
        return Ignorado("comentário sem comando /forja")
    if comando == "stop":
        return Parar(origem=_origem(evento.repository, evento.issue), autor=evento.comment.user.login)
    return Ignorado(f"comando desconhecido: {comando[:32]}")


def _extrair_comando(corpo: str) -> str | None:
    for linha in corpo.splitlines():
        achado = _COMANDO.match(linha.strip())
        if achado:
            return achado.group(1).lower()
    return None


def _origem(repositorio: _Repositorio, issue: _Issue) -> OrigemExterna:
    return OrigemExterna(repositorio=repositorio.full_name, numero=issue.number, url=issue.html_url)
