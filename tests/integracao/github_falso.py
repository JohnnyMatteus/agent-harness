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
        self.branches: set[str] = set()
        self.arquivos: dict[tuple[str, str], dict[str, str]] = {}
        self.commits: list[dict[str, Any]] = []
        self.prs: list[dict[str, Any]] = []
        self.falhar_leitura = False
        self.check_runs: list[dict[str, Any]] = []
        self.merges: list[dict[str, Any]] = []
        self.prontos: list[str] = []
        self.arquivos_do_diff: list[dict[str, Any]] = []
        self.ref_final = "b" * 40
        self.app = self._criar_app()

    def arquivo(self, branch: str, caminho: str) -> str:
        import base64

        return base64.b64decode(self.arquivos[(branch, caminho)]["content"]).decode()

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

        @app.get("/repos/{dono}/{nome}")
        async def repo(dono: str, nome: str) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
            return {"default_branch": "main"}

        @app.get("/repos/{dono}/{nome}/git/ref/heads/{ref:path}")
        async def ref(dono: str, nome: str, ref: str) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
            # a branch padrão e a da entrega têm SHAs diferentes: a ponta da entrega é ref_final
            return {"object": {"sha": "a" * 40 if ref == "main" else self.ref_final}}

        @app.post("/repos/{dono}/{nome}/git/refs", status_code=201)
        async def criar_ref(dono: str, nome: str, request: Request) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
            ref = (await request.json())["ref"].removeprefix("refs/heads/")
            if ref in self.branches:
                raise HTTPException(422, "Reference already exists")
            if ref == "main":
                raise HTTPException(403, "branch protegida")
            self.branches.add(ref)
            return {"ref": ref}

        @app.get("/repos/{dono}/{nome}/contents/{caminho:path}")
        async def ler(dono: str, nome: str, caminho: str, ref: str) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
            if self.falhar_leitura:
                raise HTTPException(500)
            achado = self.arquivos.get((ref, caminho))
            if achado is None:
                raise HTTPException(404)
            return achado

        @app.put("/repos/{dono}/{nome}/contents/{caminho:path}")
        async def escrever(dono: str, nome: str, caminho: str, request: Request) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
            c = await request.json()
            if c["branch"] not in self.branches:
                raise HTTPException(404, "branch inexistente")
            self.arquivos[(c["branch"], caminho)] = {
                "content": c["content"],
                "sha": f"s{len(self.commits)}",
            }
            self.commits.append(
                {"branch": c["branch"], "caminho": caminho, "message": c["message"]}
            )
            return {"commit": {"sha": "c" * 40}}

        @app.get("/repos/{dono}/{nome}/pulls")
        async def listar_prs(dono: str, nome: str, head: str) -> list[dict[str, Any]]:  # pyright: ignore[reportUnusedFunction]
            return [
                {**p, "base": {"ref": p["base"]}}  # a API devolve o destino como objeto
                for p in self.prs
                if f"{dono}:{p['head']}" == head
            ]

        @app.post("/repos/{dono}/{nome}/pulls", status_code=201)
        async def criar_pr(dono: str, nome: str, request: Request) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
            pr = await request.json()
            pr["number"] = len(self.prs) + 1
            pr["html_url"] = f"https://github.test/{dono}/{nome}/pull/{pr['number']}"
            self.prs.append(pr)
            return pr

        @app.get("/repos/{dono}/{nome}/compare/{spec:path}")
        async def comparar(dono: str, nome: str, spec: str) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
            if spec.startswith("main..."):
                return {"files": self.arquivos_do_diff, "commits": [{"sha": "0" * 40}]}
            return {"total_commits": 0, "files": [], "commits": []}  # avanço entre SHAs iguais

        @app.post("/repos/{dono}/{nome}/check-runs", status_code=201)
        async def criar_check(dono: str, nome: str, request: Request) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
            corpo = await request.json()
            self.check_runs.append(corpo)
            return {"id": len(self.check_runs)}

        @app.get("/repos/{dono}/{nome}/commits/{sha}/check-runs")
        async def checks(dono: str, nome: str, sha: str) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
            runs = [c for c in self.check_runs if c["head_sha"] == sha]
            return {"total_count": len(runs), "check_runs": runs}

        @app.get("/repos/{dono}/{nome}/commits/{sha}/status")
        async def status(dono: str, nome: str, sha: str) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
            return {"statuses": []}

        @app.get("/repos/{dono}/{nome}/pulls/{numero}")
        async def pr(dono: str, nome: str, numero: int) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
            return {"number": numero, "node_id": f"PR_{numero}"}

        @app.post("/graphql")
        async def graphql(request: Request) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
            corpo = await request.json()
            self.prontos.append(corpo["variables"]["id"])
            return {"data": {"markPullRequestReadyForReview": {"clientMutationId": None}}}

        @app.put("/repos/{dono}/{nome}/pulls/{numero}/merge")
        async def mesclar(dono: str, nome: str, numero: int, request: Request) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
            self.merges.append({"numero": numero, **(await request.json())})
            return {"merged": True}

        return app
