from collections.abc import Sequence
from pathlib import Path

from forja.application.casos_de_uso.indexar_repositorio import IndexarRepositorio
from forja.domain.knowledge import Escopo, Trecho
from forja.infrastructure.knowledge.chunker import ChunkerEstrutural
from forja.infrastructure.knowledge.contexto import ContextoPorEstrutura
from forja.infrastructure.knowledge.embedder_falso import EmbedderFalso
from forja.infrastructure.knowledge.memoria import IndiceEmMemoria
from forja.infrastructure.knowledge.varredura import VarreduraDeDiretorio

ESCOPO = Escopo("acme", "loja")


class IndiceEspiao(IndiceEmMemoria):
    def __init__(self) -> None:
        super().__init__()
        self.escritas: list[str] = []
        self.remocoes: list[str] = []

    def substituir_arquivo(
        self,
        escopo: Escopo,
        caminho: str,
        versao: str,
        itens: Sequence[tuple[Trecho, Sequence[float]]],
    ) -> None:
        self.escritas.append(caminho)
        super().substituir_arquivo(escopo, caminho, versao, itens)

    def remover_arquivo(self, escopo: Escopo, caminho: str) -> None:
        self.remocoes.append(caminho)
        super().remover_arquivo(escopo, caminho)


def montar(raiz: Path, indice: IndiceEmMemoria, dimensao: int = 32) -> IndexarRepositorio:
    return IndexarRepositorio(
        VarreduraDeDiretorio(raiz, "abc123"),
        ChunkerEstrutural(),
        EmbedderFalso(dimensao),
        ContextoPorEstrutura(),
        indice,
    )


def repo(tmp_path: Path) -> Path:
    (tmp_path / "a.py").write_text("def a():\n    return 1\n")
    (tmp_path / "b.py").write_text("def b():\n    return 2\n")
    return tmp_path


def test_segunda_execucao_nao_escreve_nada(tmp_path: Path) -> None:
    indice = IndiceEspiao()
    caso = montar(repo(tmp_path), indice)
    primeira = caso.executar(ESCOPO)
    assert (primeira.indexados, primeira.inalterados) == (2, 0)
    indice.escritas.clear()
    segunda = caso.executar(ESCOPO)
    assert (segunda.indexados, segunda.inalterados, segunda.trechos) == (0, 2, 0)
    assert indice.escritas == [] and indice.remocoes == []


def test_so_o_arquivo_alterado_e_reindexado_e_o_removido_sai(tmp_path: Path) -> None:
    indice = IndiceEspiao()
    raiz = repo(tmp_path)
    caso = montar(raiz, indice)
    caso.executar(ESCOPO)
    indice.escritas.clear()
    (raiz / "a.py").write_text("def a():\n    return 10\n")
    (raiz / "b.py").unlink()
    relatorio = caso.executar(ESCOPO)
    assert indice.escritas == ["a.py"]
    assert indice.remocoes == ["b.py"]
    assert (relatorio.indexados, relatorio.removidos) == (1, 1)
    assert set(indice.versoes_por_arquivo(ESCOPO)) == {"a.py"}


def test_mudar_o_pipeline_reindexa_tudo(tmp_path: Path) -> None:
    indice = IndiceEspiao()
    raiz = repo(tmp_path)
    montar(raiz, indice, dimensao=32).executar(ESCOPO)
    indice.escritas.clear()
    montar(raiz, indice, dimensao=16).executar(ESCOPO)
    assert sorted(indice.escritas) == ["a.py", "b.py"]


def test_recusas_aparecem_no_relatorio_sem_chegar_ao_indice(tmp_path: Path) -> None:
    raiz = repo(tmp_path)
    (raiz / ".env").write_text("X=1\n")
    indice = IndiceEspiao()
    relatorio = montar(raiz, indice).executar(ESCOPO)
    assert relatorio.recusados == {"segredo": 1}
    assert ".env" not in indice.versoes_por_arquivo(ESCOPO)


def test_trecho_carrega_commit_contexto_e_id_estavel(tmp_path: Path) -> None:
    indice = IndiceEmMemoria()
    caso = montar(repo(tmp_path), indice)
    caso.executar(ESCOPO)
    (trecho,) = indice.obter_simbolo(ESCOPO, "a.py", "a")
    assert trecho.commit == "abc123"
    assert trecho.contexto.endswith("em a.py")
    outro = IndiceEmMemoria()
    montar(tmp_path, outro).executar(ESCOPO)
    assert outro.obter_simbolo(ESCOPO, "a.py", "a")[0].id == trecho.id
