"""Per-key token-bucket rate limiter (issue #13 hardening).

Pure logic with an injectable clock, so it unit-tests without sleeping.
The token server applies it per client IP before minting LiveKit tokens: a
modest sustained rate with a small burst is generous for a human beginning
interviews, and stops a loop from minting hundreds of join tokens. State is
in-process only (one uvicorn worker serves this demo), and memory stays
bounded by pruning buckets that have refilled completely.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

# Prune refilled buckets once the table grows past this many keys.
_PRUNE_THRESHOLD = 1024


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after_seconds: float = 0.0


class RateLimiter:
    """Classic token bucket: ``burst`` capacity, refilled at ``per_minute``."""

    def __init__(
        self,
        per_minute: float,
        burst: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if per_minute <= 0:
            raise ValueError("per_minute must be positive")
        if burst < 1:
            raise ValueError("burst must be at least 1")
        self._rate = per_minute / 60.0
        self._capacity = float(burst)
        self._clock = clock
        # key -> (tokens remaining, last refill timestamp)
        self._buckets: dict[str, tuple[float, float]] = {}

    def check(self, key: str) -> Decision:
        now = self._clock()
        tokens, last = self._buckets.get(key, (self._capacity, now))
        tokens = min(self._capacity, tokens + (now - last) * self._rate)
        if tokens >= 1.0:
            self._buckets[key] = (tokens - 1.0, now)
            self._maybe_prune(now)
            return Decision(allowed=True)
        self._buckets[key] = (tokens, now)
        return Decision(allowed=False, retry_after_seconds=(1.0 - tokens) / self._rate)

    def _maybe_prune(self, now: float) -> None:
        if len(self._buckets) <= _PRUNE_THRESHOLD:
            return
        # Time for an empty bucket to refill completely: pruning such an
        # entry is indistinguishable from keeping it.
        refill_all = self._capacity / self._rate
        self._buckets = {
            key: (tokens, last)
            for key, (tokens, last) in self._buckets.items()
            if now - last < refill_all
        }
