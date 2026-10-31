"""Every Redis client must bound how long it waits on a dead connection.

Found on a live run (2026-10-31): a pooled connection that the network had silently dropped made one config read wait ~30 s
before the OS reported a reset, so a cheque that should take ~6 s took 34 s. A client with no socket timeout and no health
check has no limit at all."""
from shared.config.redis_options import redis_options


def _platform(values):
    def get(key):
        from shared.config.exceptions import ConfigKeyNotFoundError
        if key not in values:
            raise ConfigKeyNotFoundError(key)
        return values[key]
    return get


def test_defaults_bound_every_wait():
    o = redis_options(_platform({}))
    assert 0 < o["socket_timeout"] <= 5
    assert 0 < o["socket_connect_timeout"] <= 5
    assert 0 < o["health_check_interval"] <= 30
    assert o["socket_keepalive"] is True
    assert o["retry_on_timeout"] is True


def test_values_come_from_platform_config():
    o = redis_options(_platform({"redis.socket_timeout_seconds": "0.5", "redis.connect_timeout_seconds": "1",
                                 "redis.health_check_interval_seconds": "7"}))
    assert (o["socket_timeout"], o["socket_connect_timeout"], o["health_check_interval"]) == (0.5, 1.0, 7)


def test_a_retry_policy_reconnects_once_after_a_timeout():
    from redis.exceptions import ConnectionError as RConn, TimeoutError as RTimeout
    r = redis_options(_platform({}))["retry"]
    assert r._retries >= 1
    assert RTimeout in r._supported_errors and RConn in r._supported_errors
