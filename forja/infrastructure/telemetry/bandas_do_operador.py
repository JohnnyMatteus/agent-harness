"""Bandas do OPERADOR: as consultas PromQL vêm de arquivos que o operador mantém fora do
repositório monitorado (`<FORJA_BANDAS_DIR>/<dono>__<nome>.yaml`). O repositório-alvo, a issue e
o modelo nunca escolhem a consulta que o Prometheus executa."""

from __future__ import annotations

from pathlib import Path

from forja.application.portas.operacao import LeituraDeDeploys
from forja.domain.bandas import Bandas, BandasInvalidas
from forja.domain.seguranca import repositorio_valido
from forja.infrastructure.yaml_estrito import ler

TETO_DO_ARQUIVO = 64 * 1024


class BandasDoOperador:
    def __init__(self, diretorio: Path) -> None:
        self._dir = diretorio.resolve()

    def _caminho(self, repositorio: str) -> Path:
        if not repositorio_valido(repositorio):
            raise BandasInvalidas("repositório inválido")
        dono, nome = repositorio.split("/", 1)
        return self._dir / f"{dono}__{nome}.yaml"

    async def bandas(self, repositorio: str) -> Bandas | None:
        caminho = self._caminho(repositorio)
        if caminho.is_symlink() or not caminho.is_file():
            return None
        if caminho.stat().st_size > TETO_DO_ARQUIVO:
            raise BandasInvalidas("arquivo de bandas acima do teto")
        return Bandas.de_dict(ler(caminho.read_text(encoding="utf-8")))


class LeituraComposta:
    """Bandas do operador + deploys recentes do GitHub (dado do repositório, só para o texto
    do diagnóstico, delimitado como não confiável)."""

    def __init__(self, bandas: BandasDoOperador, deploys: LeituraDeDeploys) -> None:
        self._bandas = bandas
        self._deploys = deploys

    async def bandas(self, repositorio: str) -> Bandas | None:
        return await self._bandas.bandas(repositorio)

    async def deploys_recentes(self, repositorio: str) -> list[str]:
        return await self._deploys.deploys_recentes(repositorio)
