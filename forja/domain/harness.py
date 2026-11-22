"""Harness de longa duração (seção 5.3): feature_list.json, contrato de sprint e veredito.

Regras de integridade vivem aqui, em código: o modelo propõe, o código decide.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from forja.domain.artefatos import linha_unica
from forja.domain.erros import ErroDeDominio

NOTA_MAXIMA = 10
_ID_FEATURE = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
_ARGUMENTO = re.compile(r"[A-Za-z0-9_./:=,@+%~-]{1,200}")
EXECUTAVEIS_DE_TESTE = frozenset(
    {"pytest", "python", "python3", "uv", "npm", "go", "make", "cargo"}
)
MODULOS_PYTHON_DE_TESTE = frozenset({"pytest", "unittest"})


class HarnessInvalido(ErroDeDominio):
    """Estrutura do harness que viola uma regra (lista adulterada, contrato fora da lista)."""


class FeatureListAdulterada(HarnessInvalido):
    """Algo além do campo `passes` mudou na feature_list.json."""


def comando_de_teste_valido(argv: tuple[str, ...]) -> tuple[str, ...]:
    """Comando de teste como lista de argumentos (nunca string de shell). Só executáveis de
    teste conhecidos; `python` só como `-m pytest|unittest`."""
    if len(argv) == 0 or len(argv) > 20 or any(_ARGUMENTO.fullmatch(a) is None for a in argv):
        raise HarnessInvalido("comando de teste vazio, longo ou com argumento inválido")
    if argv[0] not in EXECUTAVEIS_DE_TESTE:
        raise HarnessInvalido(f"executável de teste não permitido: {argv[0][:30]}")
    if argv[0] in ("python", "python3") and (
        len(argv) < 3 or argv[1] != "-m" or argv[2] not in MODULOS_PYTHON_DE_TESTE
    ):
        raise HarnessInvalido("python só como `-m pytest` ou `-m unittest`")
    return argv


@dataclass(frozen=True, slots=True)
class Feature:
    id: str
    categoria: str
    descricao: str
    passos_de_teste: tuple[str, ...]
    comando_de_teste: tuple[str, ...]
    passes: bool = False

    def __post_init__(self) -> None:
        if _ID_FEATURE.fullmatch(self.id) is None:
            raise HarnessInvalido(f"id de feature inválido: {self.id[:40]!r}")
        if not self.descricao.strip() or not self.passos_de_teste:
            raise HarnessInvalido("feature sem descrição ou sem passos de teste")
        comando_de_teste_valido(self.comando_de_teste)

    def como_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "categoria": linha_unica(self.categoria, 60),
            "descricao": linha_unica(self.descricao, 500),
            "passos_de_teste": [linha_unica(p) for p in self.passos_de_teste],
            "comando_de_teste": list(self.comando_de_teste),
            "passes": self.passes,
        }


@dataclass(frozen=True, slots=True)
class FeatureList:
    features: tuple[Feature, ...]
    # Teste básico de ponta a ponta que o Executor roda antes de cada sessão (seção 5.3, passo 4).
    comando_de_fumaca: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        ids = [f.id for f in self.features]
        if not ids or len(set(ids)) != len(ids):
            raise HarnessInvalido("feature_list vazia ou com ids repetidos")
        if self.comando_de_fumaca:
            comando_de_teste_valido(self.comando_de_fumaca)

    def para_json(self) -> str:
        corpo = {
            "comando_de_fumaca": list(self.comando_de_fumaca),
            "features": [f.como_dict() for f in self.features],
        }
        return json.dumps(corpo, ensure_ascii=False, indent=2) + "\n"

    @classmethod
    def de_json(cls, texto: str) -> FeatureList:
        try:
            bruto = json.loads(texto)
            itens = bruto["features"]
            fumaca = tuple(bruto.get("comando_de_fumaca", ()))
            return cls(
                comando_de_fumaca=fumaca,
                features=tuple(
                    Feature(
                        i["id"],
                        i["categoria"],
                        i["descricao"],
                        tuple(i["passos_de_teste"]),
                        tuple(i["comando_de_teste"]),
                        bool(i["passes"]) if isinstance(i["passes"], bool) else _recusar(),
                    )
                    for i in itens
                ),
            )
        except (ValueError, KeyError, TypeError) as erro:
            raise HarnessInvalido(f"feature_list.json ilegível: {type(erro).__name__}") from erro

    def pendentes(self) -> tuple[Feature, ...]:
        return tuple(f for f in self.features if not f.passes)

    @property
    def completa(self) -> bool:
        return not self.pendentes()

    def bloco(self, tamanho: int) -> tuple[Feature, ...]:
        """As próximas `tamanho` funcionalidades pendentes, na ordem de prioridade da lista."""
        return self.pendentes()[: max(1, tamanho)]

    def com_passes(self, ids: frozenset[str]) -> FeatureList:
        """Única forma de marcar `passes: true`; quem chama é o grader de código."""
        desconhecidos = ids - {f.id for f in self.features}
        if desconhecidos:
            raise HarnessInvalido(f"features desconhecidas: {sorted(desconhecidos)[:3]}")
        return FeatureList(
            tuple(
                Feature(
                    f.id, f.categoria, f.descricao, f.passos_de_teste, f.comando_de_teste,
                    f.passes or f.id in ids,
                )
                for f in self.features
            ),
            self.comando_de_fumaca,
        )  # fmt: skip


def _recusar() -> bool:
    raise ValueError("passes precisa ser booleano")


def exigir_so_passes_mudou(antes: FeatureList, depois: FeatureList) -> None:
    """Hook de integridade (seção 5.3): só `passes` pode mudar, e nunca de true para false."""
    if antes.comando_de_fumaca != depois.comando_de_fumaca:
        raise FeatureListAdulterada("comando de fumaça alterado")
    if len(antes.features) != len(depois.features):
        raise FeatureListAdulterada("quantidade de funcionalidades mudou")
    for a, d in zip(antes.features, depois.features, strict=True):
        if (a.id, a.categoria, a.descricao, a.passos_de_teste, a.comando_de_teste) != (
            d.id, d.categoria, d.descricao, d.passos_de_teste, d.comando_de_teste,
        ):  # fmt: skip
            raise FeatureListAdulterada(f"funcionalidade {a.id} alterada além de `passes`")
        if a.passes and not d.passes:
            raise FeatureListAdulterada(f"funcionalidade {a.id} voltou de passes para falha")


class Criterio(StrEnum):
    FUNCIONALIDADE = "funcionalidade"
    PROFUNDIDADE = "profundidade"
    QUALIDADE_DE_CODIGO = "qualidade_de_codigo"
    ADERENCIA_A_ADRS = "aderencia_a_adrs"


# Valores iniciais provisórios: a rubrica e os limiares são núcleo do autor (seção 14).
LIMIARES_PROVISORIOS: Mapping[Criterio, int] = {c: 7 for c in Criterio}


@dataclass(frozen=True, slots=True)
class ContratoDeSprint:
    bloco: int
    features: tuple[str, ...]
    entregaveis: tuple[str, ...]
    verificacao: tuple[str, ...]
    limiares: Mapping[Criterio, int]

    def __post_init__(self) -> None:
        if self.bloco < 1 or not self.features or not self.entregaveis or not self.verificacao:
            raise HarnessInvalido("contrato sem bloco, funcionalidades, entregáveis ou verificação")
        if set(self.limiares) != set(Criterio) or any(
            not 1 <= v <= NOTA_MAXIMA for v in self.limiares.values()
        ):
            raise HarnessInvalido("limiar ausente ou fora de 1..10 em algum critério")

    def exigir_dentro_de(self, lista: FeatureList, tamanho: int) -> None:
        """O contrato só cobre funcionalidades pendentes da lista e no máximo `tamanho` delas."""
        pendentes = {f.id for f in lista.pendentes()}
        if len(self.features) > tamanho or not set(self.features) <= pendentes:
            raise HarnessInvalido(
                "contrato cobre funcionalidade inexistente, pronta ou além do bloco"
            )

    def para_json(self) -> str:
        return json.dumps(
            {
                "bloco": self.bloco,
                "features": list(self.features),
                "entregaveis": [linha_unica(e) for e in self.entregaveis],
                "verificacao": [linha_unica(v) for v in self.verificacao],
                "limiares": {c.value: v for c, v in self.limiares.items()},
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n"  # fmt: skip


@dataclass(frozen=True, slots=True)
class Veredito:
    aprovado: bool
    reprovados: tuple[Criterio, ...]


def decidir_bloco(limiares: Mapping[Criterio, int], notas: Mapping[Criterio, int]) -> Veredito:
    """Limiar rígido: abaixo em qualquer critério (ou critério sem nota) o bloco falha."""
    reprovados = tuple(
        c for c in Criterio if not (0 <= notas.get(c, -1) <= NOTA_MAXIMA) or notas[c] < limiares[c]
    )
    return Veredito(not reprovados, reprovados)


def features_que_passam(
    veredito: Veredito, resultados_dos_testes: Mapping[str, bool], contrato: ContratoDeSprint
) -> frozenset[str]:
    """`passes: true` exige as duas coisas: o Avaliador aprovou o bloco e o grader de código
    viu o teste da própria funcionalidade passar."""
    if not veredito.aprovado:
        return frozenset()
    return frozenset(f for f in contrato.features if resultados_dos_testes.get(f) is True)
