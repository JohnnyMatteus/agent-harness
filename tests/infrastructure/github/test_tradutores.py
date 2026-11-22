from collections.abc import Callable
from typing import Any

from forja.application.comandos import CriarIntent, Ignorado, Parar
from forja.infrastructure.github.tradutores import traduzir


def test_label_de_intencao_vira_criar_intent(fixture_json: Callable[[str], Any]) -> None:
    resultado = traduzir("issues", fixture_json("issues_labeled_forja_intent"))

    assert isinstance(resultado, CriarIntent)
    assert resultado.origem.repositorio == "acme-demo/loja-exemplo"
    assert resultado.origem.numero == 42
    assert resultado.origem.referencia == "github:acme-demo/loja-exemplo#42"
    assert resultado.titulo == "Corrigir login"
    assert resultado.autor == "maria-dev"


def test_outro_label_e_ignorado(fixture_json: Callable[[str], Any]) -> None:
    assert isinstance(traduzir("issues", fixture_json("issues_labeled_outro_label")), Ignorado)


def test_comando_stop_vira_parar(fixture_json: Callable[[str], Any]) -> None:
    resultado = traduzir("issue_comment", fixture_json("issue_comment_stop"))

    assert isinstance(resultado, Parar)
    assert resultado.origem.referencia == "github:acme-demo/loja-exemplo#42"
    assert resultado.autor == "maria-dev"


def test_comando_desconhecido_e_ignorado_com_motivo(fixture_json: Callable[[str], Any]) -> None:
    resultado = traduzir("issue_comment", fixture_json("issue_comment_dance"))

    assert isinstance(resultado, Ignorado)
    assert "dance" in resultado.motivo


def test_comentario_comum_e_de_bot_sao_ignorados(fixture_json: Callable[[str], Any]) -> None:
    assert isinstance(traduzir("issue_comment", fixture_json("issue_comment_conversa")), Ignorado)
    assert isinstance(traduzir("issue_comment", fixture_json("issue_comment_bot")), Ignorado)


def test_campos_desconhecidos_sao_ignorados(fixture_json: Callable[[str], Any]) -> None:
    assert isinstance(traduzir("issues", fixture_json("issues_labeled_campos_novos")), CriarIntent)


def test_payload_sem_o_essencial_nao_lanca(fixture_json: Callable[[str], Any]) -> None:
    assert isinstance(traduzir("issues", fixture_json("issues_sem_essencial")), Ignorado)
    assert isinstance(traduzir("issue_comment", {}), Ignorado)


def test_eventos_sem_suporte_e_ping(fixture_json: Callable[[str], Any]) -> None:
    assert traduzir("ping", fixture_json("ping")) == Ignorado("ping")
    assert isinstance(traduzir("pull_request", {}), Ignorado)
