from unittest.mock import MagicMock, patch


def _make_redis_pipeline(hour_count: int, day_count: int):
    """Return a mock Redis client whose pipeline returns (hour_count, _, day_count, _)."""
    pipe = MagicMock()
    pipe.execute.return_value = [hour_count, True, day_count, True]
    pipe.incr = MagicMock(return_value=pipe)
    pipe.expire = MagicMock(return_value=pipe)

    client = MagicMock()
    client.pipeline.return_value = pipe
    return client


def test_allowed_under_limits():
    with patch("app.ratelimit._redis", _make_redis_pipeline(1, 1)):
        from app.ratelimit import check_and_consume
        allowed, retry_after = check_and_consume("user_1")
    assert allowed is True
    assert retry_after == 0


def test_blocked_at_hourly_limit():
    with patch("app.ratelimit._redis", _make_redis_pipeline(31, 1)):
        from app.ratelimit import check_and_consume
        allowed, retry_after = check_and_consume("user_2")
    assert allowed is False
    assert retry_after > 0


def test_blocked_at_daily_limit():
    with patch("app.ratelimit._redis", _make_redis_pipeline(1, 201)):
        from app.ratelimit import check_and_consume
        allowed, retry_after = check_and_consume("user_3")
    assert allowed is False
    assert retry_after > 0


def test_hourly_limit_takes_priority_over_daily():
    # Both exceeded: hourly retry_after is smaller than daily
    with patch("app.ratelimit._redis", _make_redis_pipeline(31, 201)):
        from app.ratelimit import check_and_consume
        allowed, retry_after = check_and_consume("user_4")
    assert allowed is False
    # Hourly window is at most 3600 seconds, daily is up to 86400
    assert retry_after <= 3600


def test_exactly_at_limit_is_allowed():
    # count == limit should still be allowed, blocking starts at count > limit
    with patch("app.ratelimit._redis", _make_redis_pipeline(30, 200)), \
         patch("app.ratelimit.RATE_LIMIT_PER_HOUR", 30), \
         patch("app.ratelimit.RATE_LIMIT_PER_DAY", 200):
        from app.ratelimit import check_and_consume
        allowed, _ = check_and_consume("user_5")
    assert allowed is True
