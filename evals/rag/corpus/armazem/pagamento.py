"""Cobranca dos pedidos."""


def aplicar_desconto_cupom(total: float, percentual: float) -> float:
    """Reduz o total do pedido conforme o cupom informado."""
    return round(total * (1 - percentual / 100), 2)


def dividir_em_parcelas(total: float, parcelas: int) -> list[float]:
    """Parcela o pagamento no cartao; a ultima parcela absorve o arredondamento."""
    base = round(total / parcelas, 2)
    resto = round(total - base * parcelas, 2)
    return [base] * (parcelas - 1) + [round(base + resto, 2)]


def reembolsar_pedido_cancelado(valor_pago: float, taxa_cancelamento: float) -> float:
    """Devolve o dinheiro ao cliente descontando a taxa de cancelamento."""
    return round(valor_pago - taxa_cancelamento, 2)
