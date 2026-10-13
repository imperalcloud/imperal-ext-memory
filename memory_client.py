"""``/v1/memory`` — the acting user's durable memory, through the gateway.

What Webbee remembers (per-repo notes, facts and directives) lives in the
Tenant Vault. This app reaches it only through the gateway's owner-scoped
namespace: the gateway resolves the user from ``X-Acting-User`` and accepts no
user_id, so this app cannot read or write anybody else's memory — and it never
holds the vault's address or token.
"""
from __future__ import annotations

from imperal_sdk._gateway import GatewayClient, require

_BASE = "/v1/memory"


class MemoryClient(GatewayClient):
    """Read and write the acting user's repo notes and facts."""

    async def repo(self, repo_key: str) -> dict:
        """``{"repo_key": ..., "entries": [...]}`` for one repo."""
        return await self._call("GET", f"{_BASE}/repo",
                                params={"repo_key": require(repo_key, "repo_key")},
                                resource="memory")

    async def save_repo(self, repo_key: str, entries: list) -> dict:
        """Replace the notes of one repo."""
        return await self._call("PUT", f"{_BASE}/repo",
                                json={"repo_key": require(repo_key, "repo_key"),
                                      "entries": entries},
                                resource="memory")

    async def facts(self) -> dict:
        """``{"facts": [...]}`` — every fact and directive of the acting user."""
        return await self._call("GET", f"{_BASE}/facts", resource="memory")

    async def save_facts(self, facts: list) -> dict:
        """Upsert facts by ``fact_id``."""
        return await self._call("POST", f"{_BASE}/facts", json={"facts": facts},
                                resource="memory")


def memory_api(ctx) -> MemoryClient:
    """The gateway-backed memory client of this call's acting user."""
    return ctx._gw_namespace("memory", MemoryClient)
