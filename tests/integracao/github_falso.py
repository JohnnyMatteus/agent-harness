"""GitHub falso em ASGI: registra o que o workflow escreve. Nada sai da máquina de testes."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request


class GitHubFalso:
    def __init__(self, permissao: str = "write") -> None:
        self.permissao = permissao
        self.comentarios: list[dict[str, Any]] = []
        self.requisicoes: list[tuple[str, str]] = []
        self.app = self._criar_app()

    def cliente_http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="https://api.github.test"
        )

    def _criar_app(self) -> FastAPI:
        app = FastAPI()

        @app.middleware("http")
        async def registrar(request: Request, call_next: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
            self.requisicoes.append((request.method, request.url.path))
            return await call_next(request)

        @app.get("/repos/{dono}/{nome}/installation")
        async def instalacao(dono: str, nome: str) -> dict[str, int]:  # pyright: ignore[reportUnusedFunction]
            return {"id": 1}

        @app.post("/app/installations/{iid}/access_tokens")
        async def token(iid: int) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
            return {"token": "ghs_FICTICIO", "expires_at": "2099-01-01T00:00:00Z"}

        @app.get("/repos/{dono}/{nome}/collaborators/{usuario}/permission")
        async def permissao(dono: str, nome: str, usuario: str) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
            return {"permission": self.permissao}

        @app.post("/repos/{dono}/{nome}/issues/{numero}/comments", status_code=201)
        async def comentar(dono: str, nome: str, numero: int, request: Request) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
            corpo = await request.json()
            if "body" not in corpo:
                raise HTTPException(422)
            self.comentarios.append({"repo": f"{dono}/{nome}", "numero": numero, **corpo})
            return {"id": len(self.comentarios)}

        return app
