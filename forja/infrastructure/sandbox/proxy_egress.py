"""Política de egress por allowlist e configuração do proxy de saída (Squid).

O container fica numa rede interna sem rota externa; o único caminho é o proxy,
que só encaminha para hosts da allowlist e registra o que bloqueou.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Registries de pacotes e API do modelo; ampliar é decisão explícita por configuração.
ALLOWLIST_PADRAO = frozenset(
    {"api.anthropic.com", "pypi.org", "files.pythonhosted.org", "registry.npmjs.org"}
)


@dataclass(frozen=True)
class PoliticaEgress:
    hosts: frozenset[str] = ALLOWLIST_PADRAO

    def permite(self, host: str) -> bool:
        h = host.lower().rstrip(".")
        return any(h == p or h.endswith("." + p) for p in self.hosts)


@dataclass
class RegistroBloqueios:
    """Tentativas bloqueadas; alimenta a métrica de bloqueios (seção 3A)."""

    bloqueios: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])

    def registrar(self, sessao_id: str, host: str) -> None:
        self.bloqueios.append((sessao_id, host))


def configuracao_squid(politica: PoliticaEgress, porta: int = 3128) -> str:
    dominios = " ".join("." + h for h in sorted(politica.hosts))
    return "\n".join(
        [
            f"http_port {porta}",
            f"acl permitidos dstdomain {dominios}",
            "acl CONNECT method CONNECT",
            "acl portas_seguras port 443 80",
            "http_access deny !portas_seguras",
            "http_access allow permitidos",
            "http_access deny all",
            "access_log stdio:/dev/stdout",
            "",
        ]
    )


def ambiente_proxy(url_proxy: str) -> dict[str, str]:
    return {k: url_proxy for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")}
