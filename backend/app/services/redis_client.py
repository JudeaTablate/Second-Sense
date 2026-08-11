"""
Thin Redis wrapper. We cache each user's live EWMA scorer state here
so we don't have to hit Postgres on every single event batch — only
flushing to Postgres periodically / on session end for durability.
"""

import json
import redis

from app.config import settings

_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def get_client() -> redis.Redis:
    return _client


def cache_baseline_state(user_id: str, state: dict, ttl_seconds: int = 3600) -> None:
    _client.set(f"baseline:{user_id}", json.dumps(state), ex=ttl_seconds)


def get_cached_baseline_state(user_id: str) -> dict | None:
    raw = _client.get(f"baseline:{user_id}")
    return json.loads(raw) if raw else None
