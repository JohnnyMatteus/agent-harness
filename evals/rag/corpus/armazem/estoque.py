"""Controle de estoque do armazem ficticio."""


class Estoque:
    """Guarda a quantidade de cada produto por prateleira."""

    def __init__(self) -> None:
        self._itens: dict[str, int] = {}

    def adicionar(self, sku: str, quantidade: int) -> None:
        """Soma unidades recebidas de um fornecedor."""
        if quantidade <= 0:
            raise ValueError("quantidade deve ser positiva")
        self._itens[sku] = self._itens.get(sku, 0) + quantidade

    def retirar(self, sku: str, quantidade: int) -> None:
        """Baixa unidades; falha se o saldo nao cobre o pedido."""
        if self._itens.get(sku, 0) < quantidade:
            raise ValueError("saldo insuficiente")
        self._itens[sku] -= quantidade

    def saldo(self, sku: str) -> int:
        return self._itens.get(sku, 0)


def produtos_abaixo_do_minimo(estoque: Estoque, minimo: int, skus: list[str]) -> list[str]:
    """Lista os produtos que precisam de reposicao urgente."""
    return [sku for sku in skus if estoque.saldo(sku) < minimo]
