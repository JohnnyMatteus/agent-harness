from __future__ import annotations

from typing import Literal

from redis.asyncio import Redis

_PREFIXO = "forja:idem:"
_PENDENTE = "pendente"
_CONCLUIDA = "concluida"
LEASE_S = 600
CONCLUIDA_TTL_S = 30 * 24 * 3600


class IdempotenciaRedis:
    """`SET NX` com lease: a reivindicação é atômica e expira se o processo morrer no meio."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def reivindicar(self, chave: str) -> Literal["nova", "em_andamento", "concluida"]:
        if await self._redis.set(_PREFIXO + chave, _PENDENTE, nx=True, ex=LEASE_S):
            return "nova"
        valor = await self._redis.get(_PREFIXO + chave)
        if valor is None:  # expirou entre o SET e o GET: tenta de novo, uma vez
            return await self.reivindicar(chave)
        return "concluida" if valor in (_CONCLUIDA, _CONCLUIDA.encode()) else "em_andamento"

    async def concluir(self, chave: str) -> None:
        await self._redis.set(_PREFIXO + chave, _CONCLUIDA, ex=CONCLUIDA_TTL_S)

    async def liberar(self, chave: str) -> None:
        await self._redis.delete(_PREFIXO + chave)
