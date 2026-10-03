"""
Bounded In-Memory LRU Cache for Query Embeddings (Phase 2).
Provides thread-safe, async-safe caching for dense query vectors with:
- SHA-256 key hashing (no raw queries stored or exposed).
- Bounded LRU eviction.
- In-flight request deduplication (stampede protection).
- Defensive copying (mutation isolation).
- Granular telemetry counters (hits, misses, evictions, calls avoided).
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
import hashlib
import logging
import time
from typing import Any, Callable, Coroutine

from app.core.config import get_settings
from app.services.embeddings.base import BaseEmbeddingProvider

logger = logging.getLogger("app.services.embeddings.cache")


class QueryEmbeddingCache:
    """
    In-memory, bounded LRU cache for dense retrieval query embeddings.
    Keyed by SHA-256 digest of normalized query + model identity.
    """

    def __init__(self, max_size: int = 1000) -> None:
        self.max_size = max(1, max_size)
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._in_flight: dict[str, asyncio.Future[list[float]]] = {}
        self._lock = asyncio.Lock()

        # Metrics counters
        self._hits: int = 0
        self._misses: int = 0
        self._evictions: int = 0
        self._calls_avoided: int = 0

    @staticmethod
    def generate_cache_key(
        query: str,
        provider_name: str,
        model_name: str,
        dimension: int,
    ) -> str:
        """
        Construct a secure, deterministic SHA-256 digest cache key.
        Prevents raw user query retention in cache keys or logs.
        """
        canonical_str = f"{provider_name}:{model_name}:{dimension}:{query.strip()}"
        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

    async def get_or_compute(
        self,
        query: str,
        provider: BaseEmbeddingProvider,
        compute_fn: Callable[[], Coroutine[Any, Any, list[float]]],
    ) -> tuple[list[float], bool, float]:
        """
        Retrieve cached embedding or execute computation.

        Returns:
            tuple[list[float], bool, float]:
                - embedding vector (defensive copy)
                - is_cache_hit (True if served from cache)
                - duration_ms (cache lookup latency on hit, or full computation latency on miss)
        """
        key = self.generate_cache_key(
            query=query,
            provider_name=provider.provider_name,
            model_name=provider.model_name,
            dimension=provider.dimension,
        )

        # 1. Fast lookup under async lock
        t0 = time.perf_counter()
        async with self._lock:
            if key in self._cache:
                self._hits += 1
                self._calls_avoided += 1
                # Move to end (most recently used)
                self._cache.move_to_end(key)
                vector = list(self._cache[key])  # Defensive copy
                lookup_ms = (time.perf_counter() - t0) * 1000.0
                return vector, True, lookup_ms

            # 2. Check for in-flight identical request (stampede protection)
            if key in self._in_flight:
                future = self._in_flight[key]
                # Await in-flight future outside the lock
                t_in_flight = time.perf_counter()
                pass
            else:
                # Create future for this request
                loop = asyncio.get_running_loop()
                future = loop.create_future()
                self._in_flight[key] = future
                future = None  # Indicates caller should execute compute_fn

        # If another task is already computing this key, await its completion
        if future is not None:
            try:
                result_vector = await future
                lookup_ms = (time.perf_counter() - t0) * 1000.0
                async with self._lock:
                    self._hits += 1
                    self._calls_avoided += 1
                return list(result_vector), True, lookup_ms
            except Exception:
                # In-flight task failed; proceed to own compute
                pass

        # 3. Caller is the primary executor: run compute_fn
        try:
            self._misses += 1
            computed_vector = await compute_fn()
            calc_ms = (time.perf_counter() - t0) * 1000.0

            # Validate output vector before caching
            if not isinstance(computed_vector, list) or len(computed_vector) != provider.dimension:
                raise ValueError(
                    f"Computed vector dimension mismatch: got {len(computed_vector) if isinstance(computed_vector, list) else 0}, "
                    f"expected {provider.dimension}"
                )

            # Store in cache and notify in-flight waiters
            async with self._lock:
                # Enforce LRU capacity eviction
                if len(self._cache) >= self.max_size and key not in self._cache:
                    self._cache.popitem(last=False)  # Evict least recently used
                    self._evictions += 1

                self._cache[key] = list(computed_vector)
                # Resolve in-flight future
                pending = self._in_flight.pop(key, None)
                if pending and not pending.done():
                    pending.set_result(computed_vector)

            return list(computed_vector), False, calc_ms

        except BaseException as exc:
            # On failure or cancellation, clean up in-flight future so waiters don't hang
            async with self._lock:
                pending = self._in_flight.pop(key, None)
                if pending and not pending.done():
                    if isinstance(exc, asyncio.CancelledError):
                        pending.cancel()
                    else:
                        pending.set_exception(exc)
            raise

    async def get(
        self,
        query: str,
        provider: BaseEmbeddingProvider,
    ) -> list[float] | None:
        """Retrieve vector if cached, without computing on miss."""
        key = self.generate_cache_key(
            query=query,
            provider_name=provider.provider_name,
            model_name=provider.model_name,
            dimension=provider.dimension,
        )
        async with self._lock:
            if key in self._cache:
                self._hits += 1
                self._calls_avoided += 1
                self._cache.move_to_end(key)
                return list(self._cache[key])
            self._misses += 1
            return None

    async def clear(self) -> None:
        """Reset cache and metrics. Used in tests and configuration updates."""
        async with self._lock:
            self._cache.clear()
            # Cancel any orphaned in-flight futures
            for fut in self._in_flight.values():
                if not fut.done():
                    fut.cancel()
            self._in_flight.clear()
            self._hits = 0
            self._misses = 0
            self._evictions = 0
            self._calls_avoided = 0

    @property
    def stats(self) -> dict[str, Any]:
        """Return cache health and hit/miss statistics."""
        total = self._hits + self._misses
        hit_rate = (self._hits / total) if total > 0 else 0.0
        return {
            "entries": len(self._cache),
            "max_size": self.max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 4),
            "evictions": self._evictions,
            "calls_avoided": self._calls_avoided,
            "in_flight": len(self._in_flight),
        }


# Singleton cache instance
_GLOBAL_QUERY_EMBEDDING_CACHE: QueryEmbeddingCache | None = None


def get_query_embedding_cache() -> QueryEmbeddingCache:
    """Return singleton QueryEmbeddingCache configured with app settings."""
    global _GLOBAL_QUERY_EMBEDDING_CACHE
    if _GLOBAL_QUERY_EMBEDDING_CACHE is None:
        settings = get_settings()
        max_size = getattr(settings, "QUERY_EMBEDDING_CACHE_SIZE", 1000)
        _GLOBAL_QUERY_EMBEDDING_CACHE = QueryEmbeddingCache(max_size=max_size)
    return _GLOBAL_QUERY_EMBEDDING_CACHE
