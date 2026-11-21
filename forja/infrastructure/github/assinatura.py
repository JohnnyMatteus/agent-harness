from __future__ import annotations

import hashlib
import hmac

_PREFIXO = "sha256="


def assinar(segredo: str, corpo: bytes) -> str:
    digest = hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()
    return f"{_PREFIXO}{digest}"


def assinatura_valida(segredo: str, corpo: bytes, cabecalho: str | None) -> bool:
    """Compara em tempo constante; cabeçalho ausente ou malformado é inválido."""
    if not cabecalho or not cabecalho.startswith(_PREFIXO):
        return False
    return hmac.compare_digest(assinar(segredo, corpo), cabecalho)
