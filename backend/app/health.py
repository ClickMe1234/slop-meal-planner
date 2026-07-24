"""Short, non-sensitive dependency checks used by readiness."""

from __future__ import annotations

import os

from sqlalchemy import text

from .db import engine
from .deployment import configured_redis_urls


def check_database() -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


def check_redis() -> bool:
    urls = configured_redis_urls(os.environ)
    if not urls:
        return True
    try:
        import redis

        for url in urls:
            client = redis.Redis.from_url(
                url,
                socket_connect_timeout=2,
                socket_timeout=2,
                retry_on_timeout=False,
            )
            try:
                client.ping()
            finally:
                client.close()
    except Exception:
        return False
    return True

