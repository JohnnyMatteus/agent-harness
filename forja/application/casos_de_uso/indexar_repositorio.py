from __future__ import annotations

from dataclasses import dataclass, field

from forja.application.portas.knowledge import (
    Chunker,
    Embedder,
    FonteDeArquivos,
    GeradorDeContexto,
    IndiceDeTrechos,
)
from forja.domain.knowledge import Escopo, Trecho, id_do_trecho


@dataclass(frozen=True, slots=True)
class RelatorioDeIndexacao:
    indexados: int = 0
    inalterados: int = 0
    removidos: int = 0
    trechos: int = 0
    recusados: dict[str, int] = field(default_factory=lambda: {})


def _nao_lido(caminho: str, nao_lidos: tuple[str, ...]) -> bool:
    return any(p == "." or caminho == p or caminho.startswith(p + "/") for p in nao_lidos)


class IndexarRepositorio:
    """Reindexa só o que mudou: compara o SHA do conteúdo (mais a versão do pipeline).

    Idempotente: rodar duas vezes sobre a mesma fonte não escreve nada na segunda.
    """

    def __init__(
        self,
        fonte: FonteDeArquivos,
        chunker: Chunker,
        embedder: Embedder,
        gerador: GeradorDeContexto,
        indice: IndiceDeTrechos,
    ) -> None:
        self._fonte = fonte
        self._chunker = chunker
        self._embedder = embedder
        self._gerador = gerador
        self._indice = indice

    @property
    def versao_do_pipeline(self) -> str:
        return f"{self._chunker.versao}+{self._embedder.versao}+{self._gerador.versao}"

    def executar(self, escopo: Escopo) -> RelatorioDeIndexacao:
        varredura = self._fonte.varrer()
        existentes = self._indice.versoes_por_arquivo(escopo)
        presentes = {a.caminho for a in varredura.arquivos}

        indexados = inalterados = trechos_gravados = 0
        for arquivo in varredura.arquivos:
            versao = f"{arquivo.sha}@{self.versao_do_pipeline}"
            if existentes.get(arquivo.caminho) == versao:
                inalterados += 1
                continue
            particao = self._chunker.dividir(arquivo.caminho, arquivo.conteudo)
            trechos = [
                Trecho(
                    id=id_do_trecho(escopo, arquivo.caminho, ordem, bruto.conteudo),
                    escopo=escopo,
                    caminho=arquivo.caminho,
                    linguagem=particao.linguagem,
                    tipo=particao.tipo,
                    simbolo=bruto.simbolo,
                    linha_inicio=bruto.linha_inicio,
                    linha_fim=bruto.linha_fim,
                    conteudo=bruto.conteudo,
                    contexto=self._gerador.contexto(arquivo.caminho, bruto.simbolo, particao),
                    commit=varredura.commit,
                )
                for ordem, bruto in enumerate(particao.trechos)
            ]
            vetores = self._embedder.embutir([t.texto_indexado for t in trechos]) if trechos else []
            self._indice.substituir_arquivo(
                escopo, arquivo.caminho, versao, list(zip(trechos, vetores, strict=True))
            )
            indexados += 1
            trechos_gravados += len(trechos)

        removidos = 0
        for caminho in existentes.keys() - presentes:
            if _nao_lido(caminho, varredura.nao_lidos):
                continue
            self._indice.remover_arquivo(escopo, caminho)
            removidos += 1

        return RelatorioDeIndexacao(
            indexados=indexados,
            inalterados=inalterados,
            removidos=removidos,
            trechos=trechos_gravados,
            recusados=dict(varredura.recusados),
        )
