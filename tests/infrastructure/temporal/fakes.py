# pyright: basic
from __future__ import annotations

from forja.application.portas.publicador import DestinoDaEntrega, ResultadoPublicacao
from forja.infrastructure.temporal.activities import EtapaEntrada, EtapaSaida


class ExecutorFalso:
    """Faz o papel dos agentes: texto fixo por etapa, com pontos em aberto configuráveis."""

    def __init__(self, pontos_em_aberto: int = 0) -> None:
        self.pontos = pontos_em_aberto
        self.entradas: list[EtapaEntrada] = []

    async def __call__(self, entrada: EtapaEntrada) -> EtapaSaida:
        self.entradas.append(entrada)
        textos = {"plan": "# intent\n", "design": "# spec\n", "build": "# plan\n"}
        pontos = self.pontos if entrada.etapa == "design" else 0
        return EtapaSaida(entrada.etapa, "falso", textos.get(entrada.etapa, ""), pontos)


class PublicadorFalso:
    def __init__(self) -> None:
        self.comentarios: list[tuple[str, str]] = []
        self.commits: list[tuple[str, str]] = []
        self.prs: list[tuple[str, str]] = []
        self.arquivos: dict[str, str] = {}

    async def comentar(
        self, repositorio: str, numero: int, corpo: str, chave: str
    ) -> ResultadoPublicacao:
        self.comentarios.append((chave, corpo))
        return "publicado"

    async def commitar_artefato(
        self, destino: DestinoDaEntrega, nome: str, conteudo: str, mensagem: str
    ) -> ResultadoPublicacao:
        self.commits.append((nome, mensagem))
        self.arquivos[nome] = conteudo
        return "publicado"

    async def ler_artefato(self, destino: DestinoDaEntrega, nome: str) -> str | None:
        return self.arquivos.get(nome + ":editado")

    async def abrir_pr(self, destino: DestinoDaEntrega, titulo: str, corpo: str) -> str:
        self.prs.append((titulo, corpo))
        return "https://github.test/pr/1"
