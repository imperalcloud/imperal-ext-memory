"""Test harness for imperal-ext-memory.

The extension talks ONLY to Redis (redis.asyncio), so tests swap
``app.get_redis`` for an in-memory fake that implements the four calls the
code actually uses: ``get``, ``set``, ``scan_iter`` and ``aclose``. No real
Redis, no third-party mocking library (the validation host's worker venv has
pytest + redis but not fakeredis).
"""
import json
import os
import sys
from types import SimpleNamespace

import pytest

# Make the ext modules importable (they use bare `import app`, `from app import …`).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_mod  # noqa: E402


class FakeRedis:
    """Minimal async Redis stand-in backed by a plain dict."""

    def __init__(self, store: dict):
        self.store = store
        self.closed = False
        self.set_calls: list[tuple[str, str, int | None]] = []

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value
        self.set_calls.append((key, value, ex))
        return True

    async def scan_iter(self, match="*", count=100):
        import fnmatch
        for key in list(self.store):
            if fnmatch.fnmatch(key, match):
                yield key

    async def aclose(self):
        self.closed = True


@pytest.fixture
def store():
    """The fake keyspace. Tests seed it directly with kernel-shaped payloads."""
    return {}


@pytest.fixture
def redis_mock(monkeypatch, store):
    """Patch app.get_redis so every handler/panel call hits the fake."""
    created: list[FakeRedis] = []

    async def _factory():
        r = FakeRedis(store)
        created.append(r)
        return r

    monkeypatch.setattr(app_mod, "get_redis", _factory)
    return SimpleNamespace(store=store, created=created)


@pytest.fixture
def make_ctx():
    """Minimal ctx stand-in — only ctx.user.imperal_id is ever read."""
    def _make(imperal_id: str = "imp_u_TEST"):
        return SimpleNamespace(user=SimpleNamespace(imperal_id=imperal_id))
    return _make


@pytest.fixture
def seed(store):
    """Helper: put a kernel-shaped index map / note set into the fake keyspace."""
    def _seed(uid="imp_u_TEST", repo_key="abc123def456", index=None, notes=None):
        if index is not None:
            store[f"{app_mod.INDEX_PREFIX}{uid}:{repo_key}"] = json.dumps(index)
        if notes is not None:
            store[f"{app_mod.MEMORY_PREFIX}{uid}:{repo_key}"] = json.dumps(
                {"user_id": uid, "repo_key": repo_key, "entries": notes})
    return _seed


@pytest.fixture
def seed_index(store):
    """Seed ONE kernel-shaped index map. Mirrors core/repo_index_map.py payload."""
    def _seed(uid="imp_u_TEST", repo_key="abc123", **fields):
        payload = {
            "repo_root": fields.pop("repo_root", f"/Users/dev/{repo_key}"),
            "file_count": fields.pop("file_count", 0),
            "languages": fields.pop("languages", {"python": 1}),
            "symbol_kinds": fields.pop("symbol_kinds", {"function": 1}),
            "embedded_chunks": fields.pop("embedded_chunks", 0),
            "vectors_ready": fields.pop("vectors_ready", True),
            "git_ref": fields.pop("git_ref", "deadbeefcafe"),
            "branch": fields.pop("branch", "main"),
            "updated_at": fields.pop("updated_at", 1787000000),
        }
        payload.update(fields)
        store[f"{app_mod.INDEX_PREFIX}{uid}:{repo_key}"] = json.dumps(payload)
        return payload
    return _seed


@pytest.fixture
def seed_memory(store):
    """Seed ONE kernel-shaped note set: {user_id, repo_key, entries[]}.

    ``notes`` may be plain strings (wrapped into the kernel's entry dict) or
    full entry dicts, so a test can pin citations/timestamps when it matters.
    """
    def _seed(uid="imp_u_TEST", repo_key="abc123", notes=None):
        entries = []
        for n in (notes or []):
            entries.append(n if isinstance(n, dict) else {"note": n, "citations": []})
        store[f"{app_mod.MEMORY_PREFIX}{uid}:{repo_key}"] = json.dumps(
            {"user_id": uid, "repo_key": repo_key, "entries": entries})
        return entries
    return _seed
