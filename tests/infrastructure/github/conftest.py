from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

FIXTURES = Path(__file__).parents[2] / "fixtures" / "github"


@pytest.fixture
def fixture_json() -> Callable[[str], Any]:
    return lambda nome: json.loads((FIXTURES / f"{nome}.json").read_text())


@pytest.fixture(scope="session")
def chave_pem() -> str:
    """Chave gerada na hora: nenhuma chave, nem de teste, vai para o Git."""
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return chave.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
