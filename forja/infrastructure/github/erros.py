from __future__ import annotations


class GitHubError(Exception):
    """Mensagens nunca carregam corpo de resposta, chave ou token."""


class GitHubAuthError(GitHubError):
    pass


class GitHubApiError(GitHubError):
    def __init__(self, status: int, operacao: str) -> None:
        super().__init__(f"GitHub respondeu {status} em {operacao}")
        self.status = status


class BranchProtegida(GitHubError):
    pass
