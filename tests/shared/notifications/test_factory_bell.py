"""build_dispatcher includes the bell whenever there is a database, so a bank with no mail server still gets in-app alerts."""
import asyncio

from shared.notifications.factory import build_dispatcher


class _Cfg:
    def __init__(self, **platform):
        self.p = platform

    def get_platform(self, key):
        if key not in self.p:
            raise KeyError(key)
        return self.p[key]

    async def get(self, key):
        from shared.config.config_service import ConfigKeyNotFoundError
        raise ConfigKeyNotFoundError(key)

    async def get_secret(self, key):
        raise KeyError(key)


def test_with_a_database_and_no_mail_server_the_dispatcher_still_exists_with_a_bell():
    d = asyncio.run(build_dispatcher(_Cfg(), "kbl", db_pool=object()))
    assert d is not None and d._bell is not None and d._email is None


def test_with_nothing_configured_there_is_no_dispatcher():
    assert asyncio.run(build_dispatcher(_Cfg(), "kbl")) is None


def test_the_bell_is_added_alongside_email_when_both_exist():
    d = asyncio.run(build_dispatcher(_Cfg(**{"smtp.host": "127.0.0.1", "smtp.port": "1", "smtp.security": "none"}), "kbl", db_pool=object()))
    assert d._bell is not None and d._email is not None
