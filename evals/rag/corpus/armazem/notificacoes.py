"""Avisos enviados aos clientes."""


def montar_mensagem_de_atraso(nome: str, dias: int) -> str:
    """Texto educado avisando que a entrega vai atrasar."""
    return f"Ola {nome}, seu pedido vai atrasar {dias} dia(s). Pedimos desculpas."


def escolher_canal(preferencias: dict[str, bool]) -> str:
    """Decide entre e-mail, SMS ou aplicativo conforme a preferencia do cliente."""
    for canal in ("app", "sms", "email"):
        if preferencias.get(canal):
            return canal
    return "email"
