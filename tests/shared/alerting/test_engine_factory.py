"""build_delivery_engine: the engine exists only when everything it needs does; the keys come from the bank's secrets, the policy from configuration."""
import asyncio

from shared.alerting.engine import DeliveryEngine
from shared.alerting.factory import build_delivery_engine


class _Cfg:
    def __init__(self, secrets=None, **v):
        self.secrets, self.v = secrets if secrets is not None else {"banks.kbl.pii_enc_key": "k", "banks.kbl.pii_hash_pepper": "p"}, v

    async def get(self, key):
        from shared.config.config_service import ConfigKeyNotFoundError
        if key not in self.v:
            raise ConfigKeyNotFoundError(key)
        return self.v[key]

    async def get_secret(self, key):
        if key not in self.secrets:
            raise KeyError(key)
        return self.secrets[key]


def _build(cfg, pool=object(), dispatcher=object(), auditor=None):
    return asyncio.run(build_delivery_engine(cfg, "kbl", db_pool=pool, dispatcher=dispatcher, auditor=auditor))


def test_it_builds_when_the_pool_dispatcher_and_keys_exist():
    assert isinstance(_build(_Cfg(**{"alerting.delivery_max_attempts": 7})), DeliveryEngine)


def test_without_a_pool_or_dispatcher_there_is_no_engine():
    assert _build(_Cfg(), pool=None) is None and _build(_Cfg(), dispatcher=None) is None


def test_without_the_encryption_key_or_pepper_there_is_no_engine_and_no_crash():
    assert _build(_Cfg(secrets={"banks.kbl.pii_hash_pepper": "p"})) is None
    assert _build(_Cfg(secrets={"banks.kbl.pii_enc_key": "k"})) is None
