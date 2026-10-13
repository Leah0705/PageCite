from __future__ import annotations

import logging
import os
import time

import redis as _redis_mod

logger = logging.getLogger(__name__)

RATE_LIMIT_PER_HOUR = int(os.getenv("RATE_LIMIT_PER_HOUR", "30"))
RATE_LIMIT_PER_DAY  = int(os.getenv("RATE_LIMIT_PER_DAY",  "200"))

_redis = _redis_mod.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True
)


def check_and_consume(user_id: str) -> tuple[bool, int]:
    """Fixed-window rate check for chat queries (hourly and daily counters).

    Returns (allowed, retry_after_seconds).
    retry_after_seconds is 0 when allowed=True.
    Fails open (returns True) if Redis is unavailable.
    """
    try:
        now = int(time.time())
        hour_key = f"rl:{user_id}:h:{now // 3600}"
        day_key  = f"rl:{user_id}:d:{now // 86400}"

        pipe = _redis.pipeline(transaction=True)
        pipe.incr(hour_key)
        pipe.expire(hour_key, 3600)
        pipe.incr(day_key)
        pipe.expire(day_key, 86400)
        hour_count, _, day_count, _ = pipe.execute()

        if hour_count > RATE_LIMIT_PER_HOUR:
            retry_after = 3600 - (now % 3600)
            return False, retry_after

        if day_count > RATE_LIMIT_PER_DAY:
            retry_after = 86400 - (now % 86400)
            return False, retry_after

        return True, 0

    except Exception as exc:
        logger.warning("Rate limiter Redis unavailable, failing open: %s", exc)
        return True, 0
