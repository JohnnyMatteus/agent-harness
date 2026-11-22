from __future__ import annotations

from redis.asyncio import Redis

_PREFIXO = "forja:webhook:delivery:"
TTL_PADRAO_S = 24 * 3600


class RegistroEntregasRedis:
    """Deduplicação por X-GitHub-Delivery: SET NX com TTL, atômico (seção 7)."""

    def __init__(self, redis: Redis, ttl_s: int = TTL_PADRAO_S) -> None:
        self._redis = redis
        self._ttl_s = ttl_s

    async def registrar_nova(self, entrega_id: str) -> bool:
        return bool(await self._redis.set(_PREFIXO + entrega_id, "1", nx=True, ex=self._ttl_s))

    async def esquecer(self, entrega_id: str) -> None:
        await self._redis.delete(_PREFIXO + entrega_id)
