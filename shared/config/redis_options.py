"""Connection options every Redis client in ASTRA is built with.

A pooled connection that the network silently drops makes a client with no socket timeout wait for the OS to report a reset
(~30 s observed on a live run). These options bound that wait, probe idle connections before use, and retry once on a fresh one.
Values are platform configuration (Helm), with safe defaults.
"""
from typing import Callable

from redis.backoff import NoBackoff
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from redis.asyncio.retry import Retry

from shared.config.exceptions import ConfigKeyNotFoundError

_DEFAULT_SOCKET_TIMEOUT_SECONDS = 2.0
_DEFAULT_CONNECT_TIMEOUT_SECONDS = 2.0
_DEFAULT_HEALTH_CHECK_INTERVAL_SECONDS = 15.0
_DEFAULT_RETRIES = 1


def _number(get_platform: Callable[[str], str], key: str, default: float) -> float:
    try:
        return float(get_platform(key))
    except (ConfigKeyNotFoundError, ValueError):
        return default


def redis_options(get_platform: Callable[[str], str]) -> dict:
    retries = int(_number(get_platform, "redis.retries", _DEFAULT_RETRIES))
    return {
        "socket_timeout": _number(get_platform, "redis.socket_timeout_seconds", _DEFAULT_SOCKET_TIMEOUT_SECONDS),
        "socket_connect_timeout": _number(get_platform, "redis.connect_timeout_seconds", _DEFAULT_CONNECT_TIMEOUT_SECONDS),
        "health_check_interval": _number(get_platform, "redis.health_check_interval_seconds", _DEFAULT_HEALTH_CHECK_INTERVAL_SECONDS),
        "socket_keepalive": True,
        "retry_on_timeout": True,
        "retry_on_error": [RedisConnectionError],   # redis-py retries a dropped connection only when asked to
        "retry": Retry(NoBackoff(), retries, supported_errors=(RedisConnectionError, RedisTimeoutError)),
    }
