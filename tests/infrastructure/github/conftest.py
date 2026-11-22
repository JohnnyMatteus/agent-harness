from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parents[2] / "fixtures" / "github"


@pytest.fixture
def fixture_json() -> Callable[[str], Any]:
    return lambda nome: json.loads((FIXTURES / f"{nome}.json").read_text())
