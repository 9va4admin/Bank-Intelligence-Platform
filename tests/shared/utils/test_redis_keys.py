"""Counting keys works whether the Redis client is the async one (scan_iter is an async generator) or a plain one (an iterator)."""
import asyncio

from shared.utils.redis_keys import count_keys, first_key


class AsyncRedis:
    def __init__(self, keys):
        self.keys, self.patterns = keys, []

    def scan_iter(self, match=None, count=None):
        self.patterns.append(match)

        async def gen():
            for k in self.keys:
                yield k
        return gen()


class PlainRedis:
    def __init__(self, keys):
        self.keys = keys

    def scan_iter(self, match=None, count=None):
        return iter(self.keys)


def run(c):
    return asyncio.run(c)


def test_counts_keys_from_an_async_client_and_passes_the_pattern_on():
    r = AsyncRedis(["a", "b", "c"])
    assert run(count_keys(r, "sig:kbl:*")) == 3 and r.patterns == ["sig:kbl:*"]


def test_counts_keys_from_a_plain_client():
    assert run(count_keys(PlainRedis(["a", "b"]), "x:*")) == 2


def test_no_keys_is_zero_and_the_first_key_is_none():
    assert run(count_keys(AsyncRedis([]), "x:*")) == 0
    assert run(first_key(AsyncRedis([]), "x:*")) is None
    assert run(first_key(PlainRedis([]), "x:*")) is None


def test_the_first_key_is_returned_from_either_client():
    assert run(first_key(AsyncRedis(["k1", "k2"]), "x:*")) == "k1"
    assert run(first_key(PlainRedis(["k1", "k2"]), "x:*")) == "k1"


def test_a_failing_scan_raises_so_the_caller_can_report_it():
    class Bad:
        def scan_iter(self, **kw):
            raise ConnectionError("down")
    try:
        run(count_keys(Bad(), "x:*"))
        assert False, "should raise"
    except ConnectionError:
        pass
