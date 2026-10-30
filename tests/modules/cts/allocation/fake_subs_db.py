"""Fake asyncpg pool for SubscriptionStore: understands the store's own SQL constants."""
from modules.cts.allocation import subscriptions as S


class _Tx:
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False


class _Conn:
    def __init__(self, rows): self.rows = rows            # set of (bank_id, reviewer_id, bucket)

    def transaction(self): return _Tx()

    async def fetch(self, sql, *args):
        if sql == S.SQL_BY_REVIEWER:
            return [{"bucket": b} for (bk, r, b) in sorted(self.rows) if bk == args[0] and r == args[1]]
        if sql == S.SQL_BY_BUCKET:
            return [{"reviewer_id": r} for (bk, r, b) in sorted(self.rows) if bk == args[0] and b == args[1]]
        if sql == S.SQL_ALL:
            return [{"bucket": b, "reviewer_id": r} for (bk, r, b) in sorted(self.rows) if bk == args[0]]
        raise AssertionError(f"unexpected SQL: {sql[:60]}")

    async def execute(self, sql, *args):
        if sql == S.SQL_DELETE_FOR_REVIEWER:
            self.rows -= {x for x in self.rows if x[0] == args[0] and x[1] == args[1]}
        elif sql == S.SQL_INSERT:
            self.rows.add((args[0], args[1], args[2]))
        elif sql == S.SQL_DELETE_ONE:
            self.rows.discard((args[0], args[1], args[2]))
        else:
            raise AssertionError(f"unexpected SQL: {sql[:60]}")


class _Acq:
    def __init__(self, conn): self.c = conn
    async def __aenter__(self): return self.c
    async def __aexit__(self, *a): return False


class FakeSubsPool:
    def __init__(self): self.rows = set(); self.calls = 0
    def acquire(self):
        self.calls += 1
        return _Acq(_Conn(self.rows))
