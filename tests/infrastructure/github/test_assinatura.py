from forja.infrastructure.github.assinatura import assinar, assinatura_valida

SEGREDO = "segredo-de-teste"
CORPO = b'{"a":1}'


def test_assinatura_correta_e_valida() -> None:
    assert assinatura_valida(SEGREDO, CORPO, assinar(SEGREDO, CORPO))


def test_assinatura_errada_ausente_ou_malformada_e_invalida() -> None:
    assert not assinatura_valida(SEGREDO, CORPO, assinar("outro", CORPO))
    assert not assinatura_valida(SEGREDO, CORPO, None)
    assert not assinatura_valida(SEGREDO, CORPO, "")
    assert not assinatura_valida(SEGREDO, CORPO, assinar(SEGREDO, CORPO).removeprefix("sha256="))


def test_corpo_alterado_invalida() -> None:
    assert not assinatura_valida(SEGREDO, CORPO + b" ", assinar(SEGREDO, CORPO))
