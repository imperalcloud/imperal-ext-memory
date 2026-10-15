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
