"""A small in-memory stand-in for the Redis list commands used by rag.agents.memory."""
from __future__ import annotations

from fnmatch import fnmatchcase


class FakeRedis:
    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.ttl: dict[str, int] = {}

    def rpush(self, key: str, *values: str) -> int:
        self.lists.setdefault(key, []).extend(values)
        return len(self.lists[key])

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        items = self.lists.get(key, [])
        return items[start:] if end == -1 else items[start:end + 1]

    def ltrim(self, key: str, start: int, end: int) -> bool:
        items = self.lists.get(key, [])
        self.lists[key] = items[start:] if end == -1 else items[start:end + 1]
        return True

    def expire(self, key: str, seconds: int) -> bool:
        self.ttl[key] = seconds
        return True

    def delete(self, *keys: str) -> int:
        removed = sum(1 for k in keys if self.lists.pop(k, None) is not None)
        for k in keys:
            self.ttl.pop(k, None)
        return removed

    def scan_iter(self, match: str = "*", count: int | None = None):
        return iter([k for k in list(self.lists) if fnmatchcase(k, match)])

    def pipeline(self) -> "FakeRedis._Pipeline":
        return FakeRedis._Pipeline(self)

    class _Pipeline:
        def __init__(self, redis: "FakeRedis") -> None:
            self._redis = redis
            self._ops: list[tuple[str, tuple]] = []

        def __getattr__(self, name: str):
            def queue(*args):
                self._ops.append((name, args))
                return self
            return queue

        def execute(self) -> list:
            return [getattr(self._redis, name)(*args) for name, args in self._ops]
