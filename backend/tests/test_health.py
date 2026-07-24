from __future__ import annotations

import redis

from app import health


def test_readiness_skips_redis_when_no_explicit_url_exists(monkeypatch):
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    monkeypatch.delenv("CELERY_RESULT_BACKEND", raising=False)

    assert health.check_redis() is True


def test_readiness_checks_each_distinct_redis_endpoint(monkeypatch):
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://broker:6379/0")
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "redis://results:6379/1")
    checked: list[str] = []

    class FakeClient:
        def __init__(self, url: str):
            self.url = url

        def ping(self):
            checked.append(self.url)

        def close(self):
            pass

    monkeypatch.setattr(
        redis.Redis,
        "from_url",
        staticmethod(lambda url, **_: FakeClient(url)),
    )

    assert health.check_redis() is True
    assert checked == ["redis://broker:6379/0", "redis://results:6379/1"]

