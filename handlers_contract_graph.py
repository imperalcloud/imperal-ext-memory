"""Memory & Index · Account-scoped cross-repository endpoint/schema evidence graph.

Reads the SAME content-addressed Git-source projection persisted by Webbee Code
for every surface — the code-index maps this app already loads from the vault. Runtime/deployment observations are intentionally not mixed
into this graph: they require their own evidence origin and freshness contract.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app import ActionResult, _user_id, age, chat, load_indexes, matches
from models import CrossRepoContractGraphRecord


class ContractGraphParam(BaseModel):
    query: str = Field(default="", max_length=200,
                       description="Optional exact substring over route, method, handler, schema name or field.")
    repo: str = Field(default="", max_length=200,
                      description="Optional repo key/path fragment. Empty searches all indexed repos.")
    kind: str = Field(default="all", description="all, endpoint, schema, or link.")
    limit: int = Field(default=100, ge=1, le=200)


def _hay(item: dict) -> str:
    values = " ".join(str(v) for k, v in item.items() if k not in {"fields", "schema_refs"})
    arrays = " ".join(str(x) for x in (item.get("fields") or item.get("schema_refs") or ()))
    return f"{values} {arrays}"


def _graph(maps: list[dict], params: ContractGraphParam) -> dict:
    want_repo = (params.repo or "").strip().lower()
    query = (params.query or "").strip().lower()
    kind = (params.kind or "all").strip().lower()
    if kind not in {"all", "endpoint", "schema", "link"}:
        kind = "all"
    limit = max(1, min(int(params.limit or 100), 200))
    selected = [d for d in maps if not want_repo or matches(d, want_repo)]
    repos, endpoints, schemas, freshness = [], [], [], []
    for data in selected:
        repo_key = str(data.get("_repo_key") or data.get("repo_key") or "")
        repos.append({"repo_key": repo_key, "repo_root": data.get("repo_root", ""),
                      "git_ref": data.get("git_ref", ""),
                      "content_digest": data.get("content_digest", ""),
                      "evidence_origin": "git_source",
                      "contracts_complete": bool(data.get("contract_evidence_complete", False))})
        freshness.append({"repo_key": repo_key, "git_ref": data.get("git_ref", ""),
                          "updated_at": data.get("updated_at"), "indexed": age(data.get("updated_at"))})
        for raw in data.get("endpoints") or ():
            if isinstance(raw, dict):
                item = {"repo_key": repo_key, **raw}
                if not query or query in _hay(item).lower():
                    endpoints.append(item)
        for raw in data.get("schemas") or ():
            if isinstance(raw, dict):
                item = {"repo_key": repo_key, **raw}
                if not query or query in _hay(item).lower():
                    schemas.append(item)

    links = []
    schemas_by_name: dict[str, list[dict]] = {}
    for schema in schemas:
        schemas_by_name.setdefault(str(schema.get("name") or ""), []).append(schema)
    for endpoint in endpoints:
        for name in endpoint.get("schema_refs") or ():
            for schema in schemas_by_name.get(str(name), ()):
                if schema["repo_key"] != endpoint["repo_key"]:
                    links.append({"relation": "endpoint_schema_ref",
                                  "source_repo": endpoint["repo_key"], "target_repo": schema["repo_key"],
                                  "identity": str(name),
                                  "source": {"path": endpoint.get("path"), "line": endpoint.get("line")},
                                  "target": {"path": schema.get("path"), "line": schema.get("line")}})
    for name, same_name in schemas_by_name.items():
        repo_keys = sorted({m["repo_key"] for m in same_name})
        for pos, left in enumerate(repo_keys):
            for right in repo_keys[pos + 1:]:
                links.append({"relation": "schema_name_match", "source_repo": left,
                              "target_repo": right, "identity": name})
    by_endpoint: dict[tuple[str, str], set[str]] = {}
    for endpoint in endpoints:
        identity = (str(endpoint.get("method") or ""), str(endpoint.get("route") or ""))
        by_endpoint.setdefault(identity, set()).add(endpoint["repo_key"])
    for (method, route), repo_keys_set in by_endpoint.items():
        repo_keys = sorted(repo_keys_set)
        for pos, left in enumerate(repo_keys):
            for right in repo_keys[pos + 1:]:
                links.append({"relation": "endpoint_identity", "source_repo": left,
                              "target_repo": right, "identity": f"{method} {route}"})
    links.sort(key=lambda x: (x["relation"], x["identity"], x["source_repo"], x["target_repo"]))
    endpoints.sort(key=lambda x: (x["repo_key"], x.get("route", ""), x.get("method", "")))
    schemas.sort(key=lambda x: (x["repo_key"], x.get("name", "")))
    complete = all(repo.get("contracts_complete") for repo in repos)
    return {"repo_count": len(repos), "endpoint_count": len(endpoints),
            "schema_count": len(schemas), "link_count": len(links),
            "contracts_complete": complete, "repositories": repos,
            "endpoints": endpoints[:limit] if kind in {"all", "endpoint"} else [],
            "schemas": schemas[:limit] if kind in {"all", "schema"} else [],
            "links": links[:limit] if kind in {"all", "link"} else [],
            "freshness": freshness}


@chat.function(
    "get_cross_repo_contract_graph", action_type="read", data_model=CrossRepoContractGraphRecord,
    description=("Read the authenticated user's cross-repository HTTP endpoint and schema graph: "
                 "exact routes, handlers, models/tables, Git-source provenance, freshness, and deterministic "
                 "cross-repo links. Works identically from panel, Telegram, and terminal."),
)
async def fn_get_cross_repo_contract_graph(ctx, params: ContractGraphParam) -> ActionResult:
    """Read the caller's cross-repository HTTP contract graph.

    Returns the exact routes, handlers, models/tables and Git provenance Webbee
    has indexed, plus the deterministic links between repositories, so a change
    on one side of an HTTP boundary can be traced to the code on the other.
    Identical on every surface (panel, Telegram, terminal).
    """
    if not _user_id(ctx):
        return ActionResult.error("Could not identify the calling user.")
    maps = await load_indexes(ctx)
    data = _graph(maps, params)
    if not maps:
        summary = "No code index yet. Open repositories in Webbee Code to build the account graph."
    else:
        completeness = "complete" if data["contracts_complete"] else "bounded/legacy"
        summary = (f"Cross-repo contract graph: {data['repo_count']} repo(s), "
                   f"{data['endpoint_count']} endpoint(s), {data['schema_count']} schema(s), "
                   f"{data['link_count']} exact link(s) · {completeness} Git-source evidence.")
    return ActionResult.success(data=data, summary=summary)
