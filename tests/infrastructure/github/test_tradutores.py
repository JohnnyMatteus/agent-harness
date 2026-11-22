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


def _comentario(
    fixture_json: Callable[[str], Any], texto: str, tipo: str = "User"
) -> dict[str, Any]:
    dados = fixture_json("issue_comment_stop")
    dados["comment"]["body"] = texto
    dados["comment"]["user"]["type"] = tipo
    return dados


def test_comandos_de_confirmacao_aprovacao_e_rejeicao(fixture_json: Callable[[str], Any]) -> None:
    from forja.application.comandos import Aprovar, Confirmar, Rejeitar

    assert isinstance(
        traduzir("issue_comment", _comentario(fixture_json, "/forja confirm")), Confirmar
    )
    assert isinstance(
        traduzir("issue_comment", _comentario(fixture_json, "ok\n/forja APPROVE")), Aprovar
    )
    rejeicao = traduzir("issue_comment", _comentario(fixture_json, "/forja reject fora do escopo"))
    assert isinstance(rejeicao, Rejeitar) and rejeicao.motivo == "fora do escopo"
    longa = traduzir("issue_comment", _comentario(fixture_json, "/forja reject " + "x" * 900))
    assert isinstance(longa, Ignorado) or len(longa.motivo) <= 500  # type: ignore[union-attr]


def test_comando_citado_ou_de_bot_nao_conta(fixture_json: Callable[[str], Any]) -> None:
    assert isinstance(
        traduzir("issue_comment", _comentario(fixture_json, "> /forja approve")), Ignorado
    )
    assert isinstance(
        traduzir("issue_comment", _comentario(fixture_json, "/forja approve", "Bot")), Ignorado
    )
    assert isinstance(
        traduzir("issue_comment", _comentario(fixture_json, "vou /forja approve depois")), Ignorado
    )


def test_criar_intent_traz_o_autor_da_issue_alem_de_quem_rotulou(
    fixture_json: Callable[[str], Any],
) -> None:
    dados = fixture_json("issues_labeled_forja_intent")
    dados["sender"]["login"] = "quem-rotulou"
    resultado = traduzir("issues", dados)
    assert isinstance(resultado, CriarIntent)
    assert (resultado.autor, resultado.autor_da_issue) == ("quem-rotulou", "maria-dev")
