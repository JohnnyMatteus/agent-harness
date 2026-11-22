import pytest

from forja.domain.erros import IntentInvalida, OrigemInvalida
from forja.domain.eventos import IntentConfirmada, IntentRecebida
from forja.domain.intent import Intent, Origem, TipoDeOrigem, intent_id_de


def origem(numero: str = "42", repo: str = "acme/loja") -> Origem:
    return Origem(TipoDeOrigem.ISSUE_GITHUB, repo, numero, "Corrigir login", "Não entra")


def test_intent_recebida_emite_evento_com_id_derivado_da_origem() -> None:
    intent = Intent.receber(origem())
    eventos = intent.retirar_eventos()
    assert intent.id == intent_id_de(origem())
    assert [type(e) for e in eventos] == [IntentRecebida]
    assert intent.retirar_eventos() == []


def test_mesma_origem_mesmo_id_e_repositorio_ignora_caixa() -> None:
    assert Intent.receber(origem()).id == Intent.receber(origem(repo="ACME/Loja")).id


def test_origens_diferentes_ids_diferentes() -> None:
    assert Intent.receber(origem("42")).id != Intent.receber(origem("43")).id
    assert Intent.receber(origem(repo="acme/a")).id != Intent.receber(origem(repo="acme/b")).id


def test_titulo_e_corpo_nao_entram_no_id() -> None:
    editada = Origem(TipoDeOrigem.ISSUE_GITHUB, "acme/loja", "42", "Outro título", "outro corpo")
    assert intent_id_de(editada) == intent_id_de(origem())


def test_confirmar_emite_uma_vez() -> None:
    intent = Intent.receber(origem())
    intent.retirar_eventos()
    intent.confirmar("maria")
    intent.confirmar("joao")
    eventos = intent.retirar_eventos()
    assert eventos == [IntentConfirmada(intent_id=intent.id, confirmado_por="maria")]
    assert intent.confirmada_por == "maria"


def test_confirmar_exige_quem() -> None:
    with pytest.raises(IntentInvalida):
        Intent.receber(origem()).confirmar("  ")


@pytest.mark.parametrize("identificador", ["", "  ", "abc", "0", "-3", "4.2"])
def test_issue_com_identificador_invalido_falha(identificador: str) -> None:
    with pytest.raises(OrigemInvalida):
        origem(identificador)


@pytest.mark.parametrize("repo", ["", "acme", "acme/", "/loja", "a/b/c"])
def test_repositorio_invalido_falha(repo: str) -> None:
    with pytest.raises(OrigemInvalida):
        origem(repo=repo)


def test_origem_sem_titulo_falha() -> None:
    with pytest.raises(OrigemInvalida):
        Origem(TipoDeOrigem.CLI, "acme/loja", "run-1", " ")


def test_criterio_de_sucesso_vazio_falha() -> None:
    with pytest.raises(IntentInvalida):
        Intent.receber(origem(), ("ok", " "))


def test_chave_da_origem_github_coincide_com_a_referencia_do_gateway() -> None:
    assert origem("42", "acme/loja").chave == "github:acme/loja#42"
