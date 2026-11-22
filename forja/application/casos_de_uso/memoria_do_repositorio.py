"""Backend do memory tool (`memory_20250818`) sobre o armazém por repositório.

O repositório é fixado na construção, nunca vem do agente. Comandos: view, create,
str_replace, insert, delete, rename. Resposta em texto, como a ferramenta oficial.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from forja.application.portas.memoria import ArmazemDeMemoria
from forja.domain.memoria import (
    MAX_ARQUIVOS,
    MAX_BYTES_TOTAL,
    MemoriaInvalida,
    caminho_de_memoria,
    sanear_conteudo,
)
from forja.domain.seguranca import dado_nao_confiavel

LIMITE_DO_PROMPT = 20_000


class MemoriaDoRepositorio:
    def __init__(
        self, armazem: ArmazemDeMemoria, repositorio: str, somente_leitura: bool = False
    ) -> None:
        self._armazem = armazem
        self._repo = repositorio
        self._somente_leitura = somente_leitura

    async def executar(self, comando: Mapping[str, Any]) -> str:
        """Erro de uso volta como texto ao modelo (ele corrige); nunca levanta para o loop."""
        try:
            return await self._despachar(comando)
        except MemoriaInvalida as erro:
            return f"Erro: {erro}"

    async def _despachar(self, c: Mapping[str, Any]) -> str:
        nome = c.get("command")
        if nome == "view":
            return await self._ver(caminho_de_memoria(c.get("path")))
        if self._somente_leitura:
            raise MemoriaInvalida("memória somente leitura nesta sessão")
        caminho = caminho_de_memoria(c.get("path"))
        match nome:
            case "create":
                await self._gravar(caminho, sanear_conteudo(c.get("file_text")))
                return f"Arquivo criado: /memories/{caminho}"
            case "str_replace":
                atual = await self._exigir(caminho)
                antigo = c.get("old_str")
                if not isinstance(antigo, str) or atual.count(antigo) != 1:
                    raise MemoriaInvalida("old_str precisa aparecer exatamente uma vez")
                novo = sanear_conteudo(atual.replace(antigo, str(c.get("new_str", "")), 1))
                await self._gravar(caminho, novo)
                return "Arquivo editado"
            case "insert":
                linhas = (await self._exigir(caminho)).split("\n")
                posicao = c.get("insert_line")
                if not isinstance(posicao, int) or not 0 <= posicao <= len(linhas):
                    raise MemoriaInvalida("insert_line fora do arquivo")
                linhas.insert(posicao, str(c.get("insert_text", "")))
                await self._gravar(caminho, sanear_conteudo("\n".join(linhas)))
                return "Texto inserido"
            case "delete":
                if not caminho or not await self._armazem.apagar(self._repo, caminho):
                    raise MemoriaInvalida("arquivo inexistente")
                return f"Apagado: /memories/{caminho}"
            case "rename":
                destino = caminho_de_memoria(c.get("new_path"))
                conteudo = await self._exigir(caminho)
                await self._gravar(destino, conteudo)
                await self._armazem.apagar(self._repo, caminho)
                return f"Renomeado para /memories/{destino}"
            case _:
                raise MemoriaInvalida("comando desconhecido")

    async def _ver(self, caminho: str) -> str:
        if caminho == "" or caminho not in (await self._armazem.listar(self._repo)):
            arquivos = await self._armazem.listar(self._repo)
            filhos = {
                k: v for k, v in arquivos.items() if caminho == "" or k.startswith(caminho + "/")
            }
            if caminho and not filhos:
                raise MemoriaInvalida("caminho inexistente")
            return "\n".join(f"{v}\t/memories/{k}" for k, v in sorted(filhos.items())) or "(vazio)"
        return await self._exigir(caminho)

    async def _exigir(self, caminho: str) -> str:
        texto = await self._armazem.ler(self._repo, caminho) if caminho else None
        if texto is None:
            raise MemoriaInvalida("arquivo inexistente")
        return texto

    async def _gravar(self, caminho: str, conteudo: str) -> None:
        if not caminho:
            raise MemoriaInvalida("caminho precisa ser um arquivo")
        existentes = await self._armazem.listar(self._repo)
        total = sum(v for k, v in existentes.items() if k != caminho) + len(conteudo.encode())
        if (
            caminho not in existentes and len(existentes) >= MAX_ARQUIVOS
        ) or total > MAX_BYTES_TOTAL:
            raise MemoriaInvalida("memória do repositório cheia: apague ou resuma arquivos")
        await self._armazem.gravar(self._repo, caminho, conteudo)

    async def para_o_prompt(self) -> str:
        """Memória inteira como dado delimitado, no início de uma sessão."""
        arquivos = await self._armazem.listar(self._repo)
        partes: list[str] = []
        tamanho = 0
        for caminho in sorted(arquivos):
            texto = await self._armazem.ler(self._repo, caminho) or ""
            parte = (
                f'<memoria caminho="{dado_nao_confiavel(caminho)}">'
                f"{dado_nao_confiavel(texto)}</memoria>"
            )
            tamanho += len(parte)
            if tamanho > LIMITE_DO_PROMPT:
                break
            partes.append(parte)
        return "\n".join(partes)
