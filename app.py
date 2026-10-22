"""Memory & Index · Shared state — read/edit Webbee's memory of the user.

This extension is the USER-FACING window into everything Webbee keeps about a
person in the Tenant Vault. Per repository that is far more than one file:

  code index      structural code map (kernel-written), read-only here
  durable notes   distilled notes (kernel-written), kept with no expiry
  and also        working memory, goals and plans, proven conclusions, saved
                  command outputs, terminal conversations, session snapshots,
                  context-graph events — plus account-level rules,
                  conversations and extension data

All of it is SHOWN as stored (``GET /v1/memory/all``), and every deletion goes
through the vault's one forget door (``POST /v1/memory/forget``), which deletes
across all sections and reports anything left; this app then re-reads the
whole memory to confirm it. Nothing is hidden and nothing is auto-deleted.

It reaches the vault only through the gateway's owner-scoped ``/v1/memory``
(see memory_client.py) and keeps no state or cache of its own.

The index map is READ-ONLY here by design: it is rebuilt deterministically by
the terminal coding agent from the actual source tree, so a hand edit would be
overwritten on the next indexing pass and would only ever misinform the reader.

The durable notes ARE editable — they are prose facts about the repo, and the
person who owns the repo knows better than a distiller LLM whether a note is
still true. Every write goes through the SAME safety pipeline the kernel
distiller uses (scrub_secrets -> neutralize_fence -> 400-char clamp -> LRU
cap), because stored notes are re-injected into the coding brain's prompt on
later turns: unsanitised user text here would be stored prompt-injection with
no shelf life at all.

OWN DATA ONLY. Every call acts as ``ctx.user.imperal_id``, which is
kernel-authoritative and cannot be spoofed, and the gateway takes no user_id,
so a caller can only ever reach their own repos. No admin scope is required precisely because there is no
cross-user surface.
"""
from __future__ import annotations

import asyncio
import logging

from imperal_sdk import Extension
from imperal_sdk.chat import ChatExtension, ActionResult  # noqa: F401 (re-exported)
from imperal_sdk.errors import APIError

from memory_client import memory_api

log = logging.getLogger("memory-index")

# ── Kernel storage contract (mirrored, NOT guessed) ───────────────────
# Source of truth: imperal_kernel/core/repo_memory.py
MAX_ENTRIES = 40                        # core.repo_memory.MAX_ENTRIES
NOTE_CHARS = 400                        # core.repo_memory._NOTE_CHARS

ext = Extension(
    "memory-index", version="1.3.0",
    # Federal-rigor scope surface (I-SCOPES-DECLARED-NOT-WILDCARD): this app
    # reads the caller's own code index and edits the caller's own durable
    # notes — declare exactly that, never a wildcard, for a system app that
    # is auto-available to everyone.
    capabilities=["memory:read", "memory:write"],
    display_name="Memory & Index",
    description=(
        "See and edit what Webbee remembers about your code — the code index "
        "(files, languages, symbols, commit) and the durable notes distilled "
        "while coding — and everything else Webbee holds about you (working "
        "memory, plans, conclusions, saved outputs, conversations), with one "
        "verified way to forget any of it."
    ),
    icon="icon.svg",
    actions_explicit=True,
    system=True,  # Imperal-owned platform app — always accessible, no explicit install.
)

chat = ChatExtension(
    ext,
    "tool_memory_chat",
    description=(
        "Webbee's memory about the user's repositories: the structural code "
        "index and the durable notes learned while coding — readable and "
        "editable from any surface."
    ),
    system_prompt=(
        "Repo memory module. Two DIFFERENT stores, never conflate them:\n\n"
        "1. CODE INDEX (read-only) — rebuilt from the source tree by the "
        "terminal coding agent: file/language counts, symbol counts, key "
        "symbols with file:line, semantic-chunk count, and the exact commit "
        "it was built at. Editing it is meaningless; it is regenerated.\n\n"
        "2. DURABLE NOTES (editable) — prose facts distilled at the tail of a "
        "coding turn (conventions, gotchas, where things live), kept per repo "
        "in the Tenant Vault with no expiry, capped at 40 newest.\n\n"
        "list_repos gives the inventory. get_index / list_notes drill into "
        "one repo. add_note / edit_note / delete_note change notes only — "
        "always echo back what changed. explain_memory answers 'where is this "
        "actually stored and when does it update' with live numbers.\n\n"
        "memory_overview lists EVERYTHING Webbee holds (account and every repo, "
        "including memory left over from repos whose index was deleted); "
        "forget_memory deletes one place / conversation / rule / app's data / "
        "everything through the vault's one forget door and confirms by a fresh "
        "re-read that nothing is left. Never guess what to forget.\n\n"
        "Always state staleness honestly: every answer carries the commit and "
        "how long ago it was written. Never present an index as live truth."
    ),
)


def _user_id(ctx) -> str:
    """ALWAYS the acting user — these tools never accept a foreign user_id."""
    return ctx.user.imperal_id if getattr(ctx, "user", None) else ""


# ── Safety pipeline ───────────────────────────────────────────────────
# Lives in safety.py (mirrors imperal_kernel/core/repo_memory.py) and is
# re-exported here so callers keep importing it from one place. sanitize_note
# is wrapped rather than aliased: safety.py takes the clamp length as an
# argument to stay dependency-free, while NOTE_CHARS — part of the kernel
# storage contract — belongs to this module.
from safety import neutralize_fence, scrub_secrets  # noqa: E402,F401
from safety import sanitize_note as _sanitize_note  # noqa: E402


def sanitize_note(text: str) -> str:
    """Full write pipeline for one note: scrub -> defuse -> clamp."""
    return _sanitize_note(text, NOTE_CHARS)


# ── Shared read helpers ───────────────────────────────────────────────

# ts()/age() live in timestamps.py: the kernel writes repo memory with
# several timestamp shapes at once (ISO str / epoch int / None), and comparing
# them raw once took the whole panel down. Re-exported here so the existing
# `from app import age` call sites keep working unchanged.
from timestamps import age, ts  # noqa: E402,F401 (re-exported for call sites)


def repo_name(root: str, fallback: str = "") -> str:
    r = (root or "").rstrip("/")
    return r.rsplit("/", 1)[-1] if r else (fallback or "repo")


async def _repo_list(ctx) -> list[dict]:
    """The vault's per-repo listing ({repo_key, index, notes}). Fail-soft: []."""
    try:
        listing = (await memory_api(ctx).repos() or {}).get("repos") or []
    except Exception:
        log.warning("repo listing failed (fail-soft empty)", exc_info=True)
        return []
    return [r for r in listing if isinstance(r, dict) and r.get("repo_key")]


def _indexes(repos: list[dict]) -> list[dict]:
    """Every code-index map in a listing, freshest first."""
    out = [{**r["index"], "_repo_key": r["repo_key"]}
           for r in repos if isinstance(r.get("index"), dict)]
    out.sort(key=lambda d: ts(d.get("updated_at")), reverse=True)
    return out


async def _memories(ctx, repos: list[dict]) -> list[dict]:
    """Every durable note set in a listing, freshest first. Fail-soft: [].

    Only repos the listing reports notes for are fetched: an index-only repo
    has nothing to read, and asking anyway would cost one call per repo.
    """
    keys = [r["repo_key"] for r in repos if (r.get("notes") or 0) > 0]
    out: list[dict] = []
    try:
        api = memory_api(ctx)
        for key, d in zip(keys, await asyncio.gather(*(api.repo(k) for k in keys))):
            if isinstance(d, dict) and isinstance(d.get("entries"), list):
                d["_repo_key"] = key
                d["_version"] = d.get("version")
                out.append(d)
    except Exception:
        log.warning("note read failed (fail-soft empty)", exc_info=True)
        return []

    def _newest(d: dict) -> float:
        # Every candidate goes through ts() FIRST: entries in one repo can mix
        # ISO strings and epoch ints, so even max() over a single note set
        # could raise before this.
        return max((max(ts(e.get("distilled_at")), ts(e.get("edited_at")))
                    for e in d["entries"] if isinstance(e, dict)),
                   default=0.0) if d.get("entries") else 0.0

    out.sort(key=_newest, reverse=True)
    return out


def _graph_map(repo: dict, graph: dict | None) -> dict:
    """A synced repo (the vault's code catalog + its graph) in the code-index map's shape, so every
    reader of a map -- inventory, graph, charts, explain -- shows the vault graph unchanged."""
    graph = graph if isinstance(graph, dict) else {}
    files = [f for f in graph.get("files") or [] if isinstance(f, dict)]
    defs = [d for d in graph.get("defs") or [] if isinstance(d, dict)]
    langs: dict[str, int] = {}
    for f in files:
        if f.get("lang"):
            langs[str(f["lang"])] = langs.get(str(f["lang"]), 0) + 1
    kinds: dict[str, int] = {}
    for d in defs:
        kinds[str(d.get("kind") or "?")] = kinds.get(str(d.get("kind") or "?"), 0) + 1
    sources = [s for s in repo.get("sources") or [] if isinstance(s, dict)]
    return {
        "_repo_key": repo["repo_key"], "_synced": True,
        "repo_root": repo.get("root_path") or "", "file_count": int(repo.get("files") or repo.get("file_count") or 0),
        "def_count": int(repo.get("defs") or 0), "link_count": int(repo.get("links") or 0),
        "languages": langs, "symbol_kinds": kinds,
        "top_symbols": [f"{d.get('qualname')} ({d.get('kind')}) @ {d.get('path')}:{d.get('start_line')}"
                        for d in defs][:60],
        "git_ref": str(repo.get("git_ref") or "")[:40], "branch": repo.get("git_branch") or "",
        "updated_at": repo.get("synced_at") or 0, "embedded_chunks": 0, "vectors_ready": False,
        "machine": repo.get("machine_label") or repo.get("machine") or "",
        "sources": [f"{s.get('kind')}:{s.get('ref')}" if s.get("ref") else str(s.get("kind")) for s in sources],
        "partial_reason": repo.get("partial_reason") or "", "os": repo.get("os") or "",
        "endpoints": [], "schemas": [], "endpoint_count": int(repo.get("endpoint_count") or 0),
        "schema_count": 0, "contract_evidence_complete": not repo.get("partial_reason"),
        "content_digest": repo.get("content_digest") or "",
    }


async def _code_maps(ctx) -> list[dict]:
    """Every repo the vault's code catalog holds, as maps (its graph fetched alongside). Fail-soft: []."""
    try:
        api = memory_api(ctx)
        repos = [r for r in ((await api.code_repos()) or {}).get("repos") or []
                 if isinstance(r, dict) and r.get("repo_key")]
        graphs = await asyncio.gather(*(api.code_graph(r["repo_key"], 400) for r in repos), return_exceptions=True)
    except Exception:
        log.warning("code catalog read failed (fail-soft: the JSON maps only)", exc_info=True)
        return []
    return [_graph_map(r, g if isinstance(g, dict) else None) for r, g in zip(repos, graphs)]


async def _all_indexes(ctx, repos: list[dict]) -> list[dict]:
    """The vault graph of every synced repo, then the old JSON map of each repo not synced yet (it
    stays readable; nothing new writes it), freshest first."""
    synced = await _code_maps(ctx)
    have = {d["_repo_key"] for d in synced}
    out = synced + [d for d in _indexes(repos) if d.get("_repo_key") not in have]
    out.sort(key=lambda d: ts(d.get("updated_at")), reverse=True)
    return out


async def load_indexes(ctx) -> list[dict]:
    """Every code-index map for this user, freshest first: the vault's code graph for synced repos,
    the JSON map for the rest. Fail-soft: []."""
    return await _all_indexes(ctx, await _repo_list(ctx))


async def load_memories(ctx) -> list[dict]:
    """Every durable note set for this user, freshest first. Fail-soft: []."""
    return await _memories(ctx, await _repo_list(ctx))


async def load_repo_memory(ctx) -> tuple[list[dict], list[dict]]:
    """(indexes, memories) from ONE listing — for callers that need both."""
    repos = await _repo_list(ctx)
    return await _all_indexes(ctx, repos), await _memories(ctx, repos)


def matches(d: dict, want: str) -> bool:
    """True when a lowercased selector is a fragment of the repo's key or path."""
    return want in str(d.get("_repo_key", "")).lower() or want in str(d.get("repo_root", "")).lower()


def pick(items: list[dict], want: str) -> dict | None:
    """Resolve a repo selector: exact repo_key, or a fragment of key/path."""
    if not items:
        return None
    w = (want or "").strip().lower()
    if not w:
        return items[0]
    for d in items:
        if w == str(d.get("_repo_key", "")).lower():
            return d
    for d in items:
        if matches(d, w):
            return d
    return None


def known_repos(items: list[dict]) -> str:
    return ", ".join(
        repo_name(d.get("repo_root", ""), d.get("_repo_key", "?"))
        + f" ({str(d.get('_repo_key', ''))[:12]})"
        for d in items[:8]) or "none"


class StaleNotesError(RuntimeError):
    """A note write was refused: the notes changed after they were read."""


async def save_entries(ctx, repo_key: str, entries: list,
                       if_version: int | None = None) -> None:
    """Persist note entries into the Tenant Vault (through the gateway's
    owner-scoped /v1/memory).

    ``if_version`` is the ``_version`` the caller read: if the distiller (or
    another window) wrote in between, the vault refuses with 409 instead of
    silently overwriting that newer write. Failures RAISE — a lost edit must
    never be reported as saved — and a 409 becomes StaleNotesError, whose
    message tells the user nothing was saved and to retry.
    """
    if len(entries) > MAX_ENTRIES:
        entries = entries[-MAX_ENTRIES:]
    try:
        await memory_api(ctx).save_repo(repo_key, entries, if_version)
    except APIError as e:
        if e.status_code == 409:
            raise StaleNotesError(
                "these notes changed since they were read (Webbee or another window "
                "wrote meanwhile), so nothing was saved — retry to apply it to the "
                "current notes") from e
        raise


# load_everything()/purge_repo() live in forget_ops.py (with the forget_memory
# tool's forget_and_verify), re-exported here for the existing call sites.
from forget_ops import load_everything, purge_repo  # noqa: E402,F401


@ext.health_check
async def health(ctx) -> dict:
    return {"status": "ok", "version": ext.version}


def safe_err(e: Exception) -> str:
    """Never let an internal URL/host leak into a chat-facing error."""
    s = str(e)
    return "internal storage error" if "://" in s else s
