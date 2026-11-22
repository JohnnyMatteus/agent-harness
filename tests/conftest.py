from __future__ import annotations

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


@pytest.fixture(scope="session")
def chave_pem() -> str:
    """Chave gerada na hora: nenhuma chave, nem de teste, vai para o Git."""
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return chave.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
