"""Memory reaches the vault only through the gateway's owner-scoped /v1/memory."""
import inspect
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from imperal_sdk import _gateway

from memory_client import MemoryClient


@pytest.fixture
def gw(monkeypatch):
    calls: list[httpx.Request] = []
    routes: dict = {}

    def handler(request):
        calls.append(request)
        return routes.get((request.method, request.url.path),
                          httpx.Response(404, json={"detail": "no route"}))

    @asynccontextmanager
    async def fake_pool(*_a, **_kw):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            yield c

    monkeypatch.setattr(_gateway, "shared_http", fake_pool)
    return calls, routes


def _client(uid="imp_u_OWNER00000"):
    return MemoryClient(gateway_url="http://gateway.test:8085", service_token="svc",
                        user_id=uid, extension_id="memory-index", tenant_id="t1")


@pytest.mark.asyncio
async def test_facts_go_through_gateway_as_the_acting_user(gw):
    calls, routes = gw
    routes[("GET", "/v1/memory/facts")] = httpx.Response(200, json={"facts": [{"fact_id": "f"}]})
    data = await _client().facts()
    assert data == {"facts": [{"fact_id": "f"}]}
    assert calls[0].headers["X-Acting-User"] == "imp_u_OWNER00000"
    assert "user_id" not in calls[0].url.params


@pytest.mark.asyncio
async def test_save_repo_sends_no_user_id(gw):
    calls, routes = gw
    routes[("PUT", "/v1/memory/repo")] = httpx.Response(200, json={"ok": True, "count": 1})
    await _client().save_repo("abc", [{"note": "n"}])
    body = json.loads(calls[0].content)
    assert body == {"repo_key": "abc", "entries": [{"note": "n"}]}


def test_app_holds_no_vault_address_or_direct_vault_calls():
    import app
    import storage_user_mem
    for mod in (app, storage_user_mem):
        src = inspect.getsource(mod)
        for needle in ("10.199.6.160", "IMPERAL_VAULT_URL", "/v1/repo/memory", "VAULT_BASE_URL"):
            assert needle not in src, (mod.__name__, needle)
