"""Calculo de frete e prazo de entrega."""

TARIFA_POR_KG = 2.5
LIMITE_FRETE_GRATIS = 300.0


def calcular_frete(peso_kg: float, distancia_km: float) -> float:
    """Cobra pelo peso e pela distancia percorrida ate o cliente."""
    return round(peso_kg * TARIFA_POR_KG + distancia_km * 0.1, 2)


def frete_gratis(total_do_pedido: float) -> bool:
    """Pedidos acima do limite nao pagam entrega."""
    return total_do_pedido >= LIMITE_FRETE_GRATIS


def estimar_prazo_em_dias(distancia_km: float) -> int:
    """Estima quantos dias uteis a transportadora leva para entregar."""
    return 1 + int(distancia_km // 400)
