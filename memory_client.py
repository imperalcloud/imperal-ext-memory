"""``/v1/memory`` — the acting user's durable memory, through the gateway.

What Webbee remembers (per-repo notes and code index, facts and directives)
lives in the Tenant Vault. This app reaches it only through the gateway's
owner-scoped namespace: the gateway resolves the user from ``X-Acting-User``
and accepts no user_id, so this app cannot read or write anybody else's
memory — and it never holds the vault's address or token.
"""
from __future__ import annotations

from imperal_sdk._gateway import GatewayClient, require

_BASE = "/v1/memory"


class MemoryClient(GatewayClient):
    """Read and write the acting user's repo memory and facts."""

    async def repos(self) -> dict:
        """``{"repos": [{"repo_key", "index", "notes"}]}`` — every repo, its
        full code-index map (or None) and its note count."""
        return await self._call("GET", f"{_BASE}/repos", resource="memory")

    async def repo(self, repo_key: str) -> dict:
        """``{"repo_key": ..., "entries": [...], "version": n}`` for one repo."""
        return await self._call("GET", f"{_BASE}/repo",
                                params={"repo_key": require(repo_key, "repo_key")},
                                resource="memory")

    async def save_repo(self, repo_key: str, entries: list,
                        if_version: int | None = None) -> dict:
        """Replace the notes of one repo. A stale ``if_version`` is refused
        with 409 instead of overwriting a newer write."""
        return await self._call("PUT", f"{_BASE}/repo",
                                json={"repo_key": require(repo_key, "repo_key"),
                                      "entries": entries, "if_version": if_version},
                                resource="memory")

    async def delete_repo(self, repo_key: str) -> dict:
        """Remove one repo's whole vault file — notes AND code index."""
        return await self._call("DELETE", f"{_BASE}/repo",
                                params={"repo_key": require(repo_key, "repo_key")},
                                resource="memory")

    async def index(self, repo_key: str) -> dict:
        """``{"repo_key": ..., "map": {...} | None}`` — one repo's code index."""
        return await self._call("GET", f"{_BASE}/index",
                                params={"repo_key": require(repo_key, "repo_key")},
                                resource="memory")

    # ── the code graph in the vault (gateway /v1/memory/code/*) ─────────────

    async def code_repos(self) -> dict:
        """``{"repos": [...], "machines": [...]}`` -- the code catalog: each synced repository
        (root, machine, sources, freshness, counts, partial reason) and the machines."""
        return await self._call("GET", f"{_BASE}/code/repos", resource="memory")

    async def code_search(self, repo_key: str, q: str, k: int = 20, kind: str | None = None,
                          path_glob: str | None = None) -> dict:
        """Definitions and files of one repo matching ``q`` (BM25)."""
        params = {"repo_key": require(repo_key, "repo_key"), "q": q, "k": k}
        if kind:
            params["kind"] = kind
        if path_glob:
            params["path_glob"] = path_glob
        return await self._call("GET", f"{_BASE}/code/search", params=params, resource="memory")

    async def code_impact(self, repo_key: str, symbols: list | None = None, paths: list | None = None,
                          depth: int = 2) -> dict:
        """What depends on the given symbols / paths of one repo."""
        return await self._call("POST", f"{_BASE}/code/impact",
                                json={"repo_key": require(repo_key, "repo_key"), "symbols": list(symbols or []),
                                      "paths": list(paths or []), "depth": depth}, resource="memory")

    async def code_graph(self, repo_key: str, limit: int = 2000) -> dict:
        """One repo's files, definitions and links (bounded)."""
        return await self._call("GET", f"{_BASE}/code/graph",
                                params={"repo_key": require(repo_key, "repo_key"), "limit": limit},
                                resource="memory")

    async def code_contracts(self) -> dict:
        """The contract graph across the user's repos: endpoints, schemas, route links."""
        return await self._call("GET", f"{_BASE}/code/contracts", resource="memory")

    async def facts(self) -> dict:
        """``{"facts": [...]}`` — every fact and directive of the acting user."""
        return await self._call("GET", f"{_BASE}/facts", resource="memory")

    async def save_facts(self, facts: list) -> dict:
        """Upsert facts by ``fact_id``."""
        return await self._call("POST", f"{_BASE}/facts", json={"facts": facts},
                                resource="memory")

    async def delete_fact(self, fact_id: str) -> dict:
        """Forget one fact (a 404 when there is no such fact)."""
        return await self._call("DELETE", f"{_BASE}/facts/{require(fact_id, 'fact_id')}",
                                resource="memory")


def memory_api(ctx) -> MemoryClient:
    """The gateway-backed memory client of this call's acting user."""
    return ctx._gw_namespace("memory", MemoryClient)
