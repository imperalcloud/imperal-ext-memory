"""Cross-repo contract graph, built on the code-index maps from the vault."""
import pytest

import handlers_contract_graph as h


def _seed_pair(seed_index, uid="imp_test"):
    seed_index(
        uid, "producer", repo_root="/src/producer", git_ref="abc123",
        updated_at=100, endpoint_count=1, schema_count=0,
        contract_evidence_complete=True,
        endpoints=[{"method": "POST", "route": "/v1/orders", "handler": "create_order",
                    "path": "api.py", "line": 10, "schema_refs": ["OrderIn", "OrderOut"]}],
        schemas=[])
    seed_index(
        uid, "consumer", repo_root="/src/consumer", git_ref="def456",
        updated_at=90, endpoint_count=0, schema_count=1, endpoints=[],
        contract_evidence_complete=True,
        schemas=[{"name": "OrderIn", "schema_kind": "model", "path": "models.py",
                  "line": 3, "fields": ["sku"]}])


@pytest.mark.asyncio
async def test_contract_graph_links_schema_refs_across_repos(make_ctx, seed_index):
    _seed_pair(seed_index)
    result = await h.fn_get_cross_repo_contract_graph(
        make_ctx("imp_test"), h.ContractGraphParam(query="order"))
    data = result.data
    assert data["repo_count"] == 2
    assert data["endpoint_count"] == 1
    assert data["schema_count"] == 1
    assert data["contracts_complete"] is True
    assert any(x["relation"] == "endpoint_schema_ref" and x["identity"] == "OrderIn"
               for x in data["links"])
    assert all("repo_key" in x and "path" in x and "line" in x
               for x in data["endpoints"] + data["schemas"])


@pytest.mark.asyncio
async def test_contract_graph_repo_filter_matches_key_or_path(make_ctx, seed_index):
    _seed_pair(seed_index)
    result = await h.fn_get_cross_repo_contract_graph(
        make_ctx("imp_test"), h.ContractGraphParam(repo="src/consum"))
    assert [r["repo_key"] for r in result.data["repositories"]] == ["consumer"]


@pytest.mark.asyncio
async def test_contract_graph_is_user_scoped_and_bounded(gateway, make_ctx, seed_index):
    seed_index("imp_owner", "r", endpoints=[], schemas=[], updated_at=1)
    seed_index("imp_other", "theirs", endpoints=[], schemas=[], updated_at=1)
    result = await h.fn_get_cross_repo_contract_graph(
        make_ctx("imp_owner"), h.ContractGraphParam(query="", limit=200))
    assert {uid for uid, _, _ in gateway.calls} == {"imp_owner"}
    assert result.data["repo_count"] == 1
    assert len(result.data["links"]) <= 200


@pytest.mark.asyncio
async def test_contract_graph_without_an_index_says_so(make_ctx):
    result = await h.fn_get_cross_repo_contract_graph(make_ctx(), h.ContractGraphParam())
    assert result.status == "success"
    assert result.data["repo_count"] == 0
    assert "No code index yet" in result.summary


# ── the vault's code catalog: synced repos and the route links between them ──

def _code(monkeypatch, repos, graphs=None, contracts=None):
    from tests import conftest

    async def code_repos(self):
        return {"repos": repos, "machines": []}

    async def code_graph(self, repo_key, limit=2000):
        return (graphs or {}).get(repo_key) or {"files": [], "defs": [], "links": []}

    async def code_contracts(self):
        return contracts or {}
    monkeypatch.setattr(conftest.FakeMemoryClient, "code_repos", code_repos, raising=False)
    monkeypatch.setattr(conftest.FakeMemoryClient, "code_graph", code_graph, raising=False)
    monkeypatch.setattr(conftest.FakeMemoryClient, "code_contracts", code_contracts, raising=False)


@pytest.mark.asyncio
async def test_a_route_link_between_two_synced_repos_is_in_the_graph(monkeypatch, make_ctx):
    _code(monkeypatch, [{"repo_key": "gw", "root_path": "/opt/gw", "files": 3, "synced_at": 1787000000},
                        {"repo_key": "ext", "root_path": "/opt/ext", "files": 2, "synced_at": 1787000000}],
          contracts={"endpoints": [{"repo_key": "gw", "key": "GET /v1/memory/repos", "method": "GET",
                                    "route": "/v1/memory/repos", "handler": "list_repos", "path": "router.py", "line": 9}],
                     "links": [{"from_repo": "ext", "to_repo": "gw", "key": "GET /v1/memory/repos"}]})
    result = await h.fn_get_cross_repo_contract_graph(make_ctx(), h.ContractGraphParam())
    data = result.data
    assert data["repo_count"] == 2 and data["endpoint_count"] == 1
    assert any(x["relation"] == "route_use" and (x["source_repo"], x["target_repo"]) == ("ext", "gw")
               for x in data["links"])


@pytest.mark.asyncio
async def test_a_synced_repos_schemas_and_cross_repo_schema_refs_come_from_the_catalog(monkeypatch, make_ctx):
    _code(monkeypatch, [{"repo_key": "gw", "root_path": "/opt/gw", "files": 3, "synced_at": 1787000000},
                        {"repo_key": "ext", "root_path": "/opt/ext", "files": 2, "synced_at": 1787000000}],
          contracts={"endpoints": [{"repo_key": "ext", "key": "POST /v1/orders", "method": "POST", "route": "/v1/orders",
                                    "handler": "create_order", "path": "api.py", "line": 6, "schema_refs": ["OrderIn"]}],
                     "schemas": [{"repo_key": "gw", "name": "OrderIn", "path": "models.py", "line": 3}],
                     "links": []})
    data = (await h.fn_get_cross_repo_contract_graph(make_ctx(), h.ContractGraphParam())).data
    assert [s["name"] for s in data["schemas"]] == ["OrderIn"]
    assert any(x["relation"] == "endpoint_schema_ref" and (x["source_repo"], x["target_repo"]) == ("ext", "gw")
               for x in data["links"])


@pytest.mark.asyncio
async def test_a_repo_known_only_as_a_json_map_still_renders(monkeypatch, make_ctx, seed_index):
    _code(monkeypatch, [{"repo_key": "gw", "root_path": "/opt/gw", "files": 3, "synced_at": 1787000000}])
    _seed_pair(seed_index)
    result = await h.fn_get_cross_repo_contract_graph(make_ctx("imp_test"), h.ContractGraphParam())
    keys = {r["repo_key"] for r in result.data["repositories"]}
    assert {"producer", "consumer", "gw"} <= keys
