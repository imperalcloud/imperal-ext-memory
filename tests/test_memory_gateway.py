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
    assert body == {"repo_key": "abc", "entries": [{"note": "n"}], "if_version": None}


@pytest.mark.asyncio
async def test_save_repo_carries_the_version_it_read(gw):
    calls, routes = gw
    routes[("PUT", "/v1/memory/repo")] = httpx.Response(200, json={"ok": True, "count": 0})
    await _client().save_repo("abc", [], if_version=7)
    assert json.loads(calls[0].content)["if_version"] == 7


@pytest.mark.asyncio
async def test_repo_routes_are_owner_scoped_and_bare(gw):
    """repos/index/delete reach the contract routes with no user_id anywhere."""
    calls, routes = gw
    routes[("GET", "/v1/memory/repos")] = httpx.Response(200, json={"repos": []})
    routes[("GET", "/v1/memory/index")] = httpx.Response(200, json={"repo_key": "abc", "map": None})
    routes[("DELETE", "/v1/memory/repo")] = httpx.Response(200, json={"repo_key": "abc", "deleted": True})
    client = _client()
    assert await client.repos() == {"repos": []}
    assert (await client.index("abc"))["map"] is None
    assert (await client.delete_repo("abc"))["deleted"] is True
    assert [c.url.params.get("repo_key") for c in calls] == [None, "abc", "abc"]
    assert all("user_id" not in c.url.params for c in calls)
    assert all(c.headers["X-Acting-User"] == "imp_u_OWNER00000" for c in calls)


@pytest.mark.asyncio
async def test_a_stale_save_raises_instead_of_failing_soft(gw):
    """A 409 from the gateway must reach the caller, not vanish into a log."""
    from imperal_sdk.errors import APIError
    _, routes = gw
    routes[("PUT", "/v1/memory/repo")] = httpx.Response(409, json={"detail": "stale"})
    with pytest.raises(APIError) as err:
        await _client().save_repo("abc", [], if_version=1)
    assert err.value.status_code == 409


def test_app_holds_no_vault_address_or_direct_vault_calls():
    import app
    import storage_user_mem
    for mod in (app, storage_user_mem):
        src = inspect.getsource(mod)
        for needle in ("10.199.6.160", "IMPERAL_VAULT_URL", "/v1/repo/memory", "VAULT_BASE_URL"):
            assert needle not in src, (mod.__name__, needle)


# ── Behaviour on top of the contract (fake gateway from conftest) ────────

@pytest.mark.asyncio
async def test_a_stale_note_edit_tells_the_user_to_retry(gateway, make_ctx, seed_memory,
                                                         monkeypatch):
    """The distiller wrote between read and save: the edit must not be lost
    silently, and must not overwrite the newer note."""
    import handlers as h
    from tests.conftest import FakeMemoryClient

    seed_memory("imp_u_TEST", "abc123", ["old truth"])
    real_save = FakeMemoryClient.save_repo

    async def _distiller_got_there_first(self, repo_key, entries, if_version=None):
        gateway.files["imp_u_TEST"][repo_key]["entries"].append({"note": "kernel note"})
        gateway.files["imp_u_TEST"][repo_key]["version"] += 1
        return await real_save(self, repo_key, entries, if_version)

    monkeypatch.setattr(FakeMemoryClient, "save_repo", _distiller_got_there_first)
    res = await h.fn_edit_note(make_ctx("imp_u_TEST"),
                               h.EditNoteParams(position=1, note="new truth", repo="abc123"))

    assert res.status == "error"
    assert "nothing was saved" in res.error and "retry" in res.error
    notes = [e["note"] for e in gateway.files["imp_u_TEST"]["abc123"]["entries"]]
    assert notes == ["old truth", "kernel note"], "the newer kernel write must survive"


@pytest.mark.asyncio
async def test_note_writes_send_the_version_they_read(gateway, make_ctx, seed_memory):
    import handlers as h
    seed_memory("imp_u_TEST", "abc123", ["a", "b"])
    seed_memory("imp_u_TEST", "abc123", ["a", "b"])          # version 2
    ctx = make_ctx("imp_u_TEST")

    assert (await h.fn_delete_note(ctx, h.DeleteNoteParams(position=1, repo="abc123"))).status == "success"
    assert (await h.fn_add_note(ctx, h.AddNoteParams(note="c", repo="abc123"))).status == "success"
    assert gateway.files["imp_u_TEST"]["abc123"]["version"] == 4


@pytest.mark.asyncio
async def test_load_memories_skips_repos_without_notes(gateway, make_ctx,
                                                       seed_index, seed_memory):
    """An index-only repo has nothing to read — it must not cost a repo() call."""
    import app
    seed_index("imp_u_TEST", "indexonly")
    seed_index("imp_u_TEST", "noted")
    seed_memory("imp_u_TEST", "noted", ["a fact"])

    out = await app.load_memories(make_ctx("imp_u_TEST"))

    assert [d["_repo_key"] for d in out] == ["noted"]
    assert out[0]["_version"] == 1
    assert [k for _, m, k in gateway.calls if m == "repo"] == ["noted"]


@pytest.mark.asyncio
async def test_inventory_reads_the_listing_once(gateway, make_ctx, seed_index, seed_memory):
    """Callers needing indexes AND notes share one gateway listing."""
    import panels_common
    seed_index("imp_u_TEST", "abc123")
    seed_memory("imp_u_TEST", "abc123", ["a fact"])
    await panels_common._inventory(make_ctx("imp_u_TEST"))
    assert [m for _, m, _ in gateway.calls].count("repos") == 1


def test_no_module_touches_redis():
    """Redis is only a cache on this platform; this app keeps nothing there."""
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parent.parent
    pattern = re.compile(r"^\s*(import|from)\s+redis\b|imperal:(repo_|user_memory)", re.M)
    hits = [str(p.relative_to(root)) for p in root.rglob("*.py")
            if p.name != pathlib.Path(__file__).name and pattern.search(p.read_text())]
    assert hits == []


# ── the code graph in the vault (gateway /v1/memory/code/*) ──

@pytest.mark.asyncio
async def test_code_reads_go_through_the_gateway_as_the_acting_user(gw):
    calls, routes = gw
    routes[("GET", "/v1/memory/code/repos")] = httpx.Response(200, json={"repos": [{"repo_key": "r1"}], "machines": []})
    routes[("GET", "/v1/memory/code/search")] = httpx.Response(200, json={"data": {"items": []}, "semantic": "off"})
    routes[("POST", "/v1/memory/code/impact")] = httpx.Response(200, json={"data": {"items": []}})
    routes[("GET", "/v1/memory/code/graph")] = httpx.Response(200, json={"files": []})
    routes[("GET", "/v1/memory/code/contracts")] = httpx.Response(200, json={"links": []})
    c = _client()
    assert (await c.code_repos())["repos"] == [{"repo_key": "r1"}]
    await c.code_search("r1", "cancel", path_glob="*.py")
    assert calls[-1].url.params["q"] == "cancel" and calls[-1].url.params["path_glob"] == "*.py"
    await c.code_impact("r1", symbols=["a"])
    assert json.loads(calls[-1].content) == {"repo_key": "r1", "symbols": ["a"], "paths": [], "depth": 2}
    await c.code_graph("r1", limit=50)
    assert calls[-1].url.params["limit"] == "50"
    await c.code_contracts()
    assert all(r.headers["X-Acting-User"] == "imp_u_OWNER00000" and "user_id" not in r.url.params for r in calls)
