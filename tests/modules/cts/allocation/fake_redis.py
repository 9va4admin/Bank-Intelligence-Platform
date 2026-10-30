"""In-memory stand-in for the Redis operations the allocation code uses (async, TTL-aware)."""
import fnmatch
import time


class FakeRedis:
    def __init__(self) -> None:
        self.kv: dict = {}
        self.exp: dict = {}
        self.z: dict = {}
        self.h: dict = {}
        self.now = time.time

    def _alive(self, key) -> bool:
        e = self.exp.get(key)
        if e is not None and e <= self.now():
            self.kv.pop(key, None); self.exp.pop(key, None)
            return False
        return key in self.kv

    async def get(self, key):
        return self.kv.get(key) if self._alive(key) else None

    async def set(self, key, value, ex=None, nx=False, xx=False):
        alive = self._alive(key)
        if nx and alive:
            return None
        if xx and not alive:
            return None
        self.kv[key] = value
        if ex:
            self.exp[key] = self.now() + ex
        else:
            self.exp.pop(key, None)
        return True

    async def delete(self, *keys):
        n = 0
        for k in keys:
            n += 1 if self.kv.pop(k, None) is not None or self.z.pop(k, None) is not None or self.h.pop(k, None) is not None else 0
            self.exp.pop(k, None)
        return n

    async def expire(self, key, seconds):
        if self._alive(key):
            self.exp[key] = self.now() + seconds

    async def mget(self, keys):
        return [await self.get(k) for k in keys]

    async def scan(self, cursor, match=None, count=None):
        keys = [k for k in list(self.kv) if self._alive(k) and (match is None or fnmatch.fnmatch(k, match))]
        return 0, keys

    async def zadd(self, key, mapping):
        d = self.z.setdefault(key, {})
        new = sum(1 for m in mapping if m not in d)
        d.update(mapping)
        return new

    async def zrem(self, key, *members):
        d = self.z.get(key, {})
        return sum(1 for m in members if d.pop(m, None) is not None)

    async def zrange(self, key, start, end, withscores=False):
        items = sorted(self.z.get(key, {}).items(), key=lambda kv: kv[1])
        items = items if end == -1 else items[start:end + 1]
        return [(m, s) for m, s in items] if withscores else [m for m, _ in items]

    async def zscore(self, key, member):
        return self.z.get(key, {}).get(member)

    async def zremrangebyscore(self, key, mn, mx):
        d = self.z.get(key, {})
        hi = float("inf") if mx == "+inf" else float(mx)
        gone = [m for m, s in d.items() if s <= hi]
        for m in gone:
            d.pop(m)
        return len(gone)

    async def zrangebyscore(self, key, mn, mx, start=0, num=None):
        hi = float("inf") if mx == "+inf" else float(mx)
        items = sorted(((m, s) for m, s in self.z.get(key, {}).items() if s <= hi), key=lambda kv: kv[1])
        out = [m for m, _ in items][start:]
        return out if num is None else out[:num]

    async def hset(self, name, key, value):
        self.h.setdefault(name, {})[key] = value
        return 1

    async def hget(self, name, key):
        return self.h.get(name, {}).get(key)

    async def hgetall(self, name):
        return dict(self.h.get(name, {}))

    async def hdel(self, name, *keys):
        return sum(1 for k in keys if self.h.get(name, {}).pop(k, None) is not None)
