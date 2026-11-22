"""Erros de domínio: toda regra violada vira uma destas exceções, nunca um valor mágico."""


class ErroDeDominio(Exception):
    """Base de todas as violações de regra de negócio."""


class OrigemInvalida(ErroDeDominio):
    """A origem da intenção não identifica de onde ela veio."""


class IntentInvalida(ErroDeDominio):
    """A intenção não tem o conteúdo mínimo para existir."""


class TransicaoInvalida(ErroDeDominio):
    """A entrega não pode ir do estado atual para o pedido."""


class CiclosEsgotados(TransicaoInvalida):
    """A entrega já voltou de Test para Build o número máximo de vezes."""
