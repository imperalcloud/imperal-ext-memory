"""Memory & Index · Shared state — read/edit Webbee's per-repo brain.

This extension is the USER-FACING window into two kernel-owned Redis stores:

  imperal:repo_index_map:{user_id}:{repo_key}   structural code map (kernel-written)
  imperal:repo_memory:{user_id}:{repo_key}      durable distilled notes (kernel-written)

The index map is READ-ONLY here by design: it is rebuilt deterministically by
the terminal coding agent from the actual source tree, so a hand edit would be
overwritten on the next indexing pass and would only ever misinform the reader.

The durable notes ARE editable — they are prose facts about the repo, and the
person who owns the repo knows better than a distiller LLM whether a note is
still true. Every write goes through the SAME safety pipeline the kernel
distiller uses (scrub_secrets -> neutralize_fence -> 400-char clamp -> LRU
cap), because stored notes are re-injected into the coding brain's prompt on
later turns: unsanitised user text here would be stored prompt-injection with
a 90-day shelf life.

OWN DATA ONLY. Every key is built from ``ctx.user.imperal_id``, which is
kernel-authoritative and cannot be spoofed, so a caller can only ever reach
their own repos. No admin scope is required precisely because there is no
cross-user surface.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time

import redis.asyncio as aioredis

from imperal_sdk import Extension
from imperal_sdk.chat import ChatExtension, ActionResult  # noqa: F401 (re-exported)

log = logging.getLogger("memory-index")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# ── Kernel storage contract (mirrored, NOT guessed) ───────────────────
# Source of truth: imperal_kernel/core/repo_memory.py + core/repo_index_map.py
INDEX_PREFIX = "imperal:repo_index_map:"
MEMORY_PREFIX = "imperal:repo_memory:"
MAX_ENTRIES = 40                        # core.repo_memory.MAX_ENTRIES
NOTE_CHARS = 400                        # core.repo_memory._NOTE_CHARS
REPO_MEM_TTL = 90 * 24 * 60 * 60        # core.repo_memory._REPO_MEM_TTL
SCAN_CAP = 200                          # never walk an unbounded keyspace

ext = Extension(
    "memory-index", version="1.0.0",
    # Federal-rigor scope surface (I-SCOPES-DECLARED-NOT-WILDCARD): this app
    # reads the caller's own code index and edits the caller's own durable
    # notes — declare exactly that, never a wildcard, for a system app that
    # is auto-available to everyone.
    capabilities=["memory:read", "memory:write"],
    display_name="Memory & Index",
    description=(
        "See and edit what Webbee remembers about your code — the code index "
        "(files, languages, symbols, commit) and the durable notes distilled "
        "while coding, with a plain explanation of where each piece is stored "
        "and when it updates."
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
        "for 90 days, refreshed on every write, capped at 40 newest.\n\n"
        "list_repos gives the inventory. get_index / list_notes drill into "
        "one repo. add_note / edit_note / delete_note change notes only — "
        "always echo back what changed. explain_memory answers 'where is this "
        "actually stored and when does it update' with live numbers.\n\n"
        "Always state staleness honestly: every answer carries the commit and "
        "how long ago it was written. Never present an index as live truth."
    ),
)


def _user_id(ctx) -> str:
    """ALWAYS the acting user — these tools never accept a foreign user_id."""
    return ctx.user.imperal_id if getattr(ctx, "user", None) else ""


async def get_redis() -> aioredis.Redis:
    return aioredis.from_url(REDIS_URL, decode_responses=True)


# ── Safety pipeline — mirrors imperal_kernel/core/repo_memory.py ──────
# A note written here is re-injected into the coding brain's prompt on later
# turns. Without these two transforms a panel edit would be a stored
# prompt-injection vector with a 90-day TTL, so they are NOT optional.

_SECRET_URI_USERINFO_RE = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s:@/]+:[^\s@/]+@")
_SECRET_KEYWORD_RE = re.compile(
    r"""(?i)(api[_-]?key|secret|token|password|passwd|authorization|bearer)["']?\s*[:=]\s*["']?[^\s"']+""")
_SECRET_BEARER_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{10,}")
_SECRET_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_SECRET_PREFIXED_KEY_RE = re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{10,}")
_SECRET_GCP_KEY_RE = re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")
_SECRET_RE = re.compile(
    r"AKIA[0-9A-Z]{16}|-----BEGIN[ A-Z]+PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}|sk-[A-Za-z0-9]{20,}")

_FENCE_OPEN_RE = re.compile(r"<{3,}")
_FENCE_CLOSE_RE = re.compile(r">{3,}")


def scrub_secrets(text: str) -> str:
    """Redact common secret/token shapes before persisting a note."""
    s = str(text or "")
    s = _SECRET_URI_USERINFO_RE.sub("[REDACTED]@", s)
    s = _SECRET_BEARER_RE.sub("[REDACTED]", s)
    s = _SECRET_KEYWORD_RE.sub("[REDACTED]", s)
    s = _SECRET_JWT_RE.sub("[REDACTED]", s)
    s = _SECRET_PREFIXED_KEY_RE.sub("[REDACTED]", s)
    s = _SECRET_GCP_KEY_RE.sub("[REDACTED]", s)
    s = _SECRET_RE.sub("[REDACTED]", s)
    return s


def neutralize_fence(text) -> str:
    """Neutralize ``<<< >>>`` DATA-fence delimiters in stored text.

    The coding brain renders stored notes inside a ``<<< >>>`` DATA fence. A
    note containing a newline + ``>>>`` would close that fence early and let
    the remainder render as a top-level directive to a tool-wielding agent.
    Newlines collapse to spaces FIRST so no content can forge a standalone
    delimiter line.
    """
    s = str(text or "")
    s = s.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ")
    s = _FENCE_OPEN_RE.sub("\u2039\u2039\u2039", s)
    s = _FENCE_CLOSE_RE.sub("\u203a\u203a\u203a", s)
    return s


def sanitize_note(text: str) -> str:
    """Full write pipeline for one note: scrub -> defuse -> clamp."""
    return neutralize_fence(scrub_secrets(text)).strip()[:NOTE_CHARS]


# ── Shared read helpers ───────────────────────────────────────────────

def age(ts) -> str:
    """Human staleness. Unknown timestamps say so rather than implying 'now'."""
    if not isinstance(ts, (int, float)) or ts <= 0:
        return "unknown"
    mins = max(0, int((time.time() - ts) // 60))
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins}m ago"
    if mins < 1440:
        return f"{mins // 60}h ago"
    return f"{mins // 1440}d ago"


def repo_name(root: str, fallback: str = "") -> str:
    r = (root or "").rstrip("/")
    return r.rsplit("/", 1)[-1] if r else (fallback or "repo")


async def _scan_json(r: aioredis.Redis, prefix: str, uid: str) -> list[tuple[str, dict]]:
    """(repo_key, payload) for every key under prefix belonging to THIS user."""
    out: list[tuple[str, dict]] = []
    n = 0
    async for key in r.scan_iter(match=f"{prefix}{uid}:*", count=200):
        raw = await r.get(key)
        n += 1
        if raw:
            try:
                d = json.loads(raw)
            except (ValueError, TypeError):
                d = None
            if isinstance(d, dict):
                out.append((key.split(":")[-1], d))
        if n >= SCAN_CAP:
            break
    return out


async def load_indexes(uid: str) -> list[dict]:
    """Every code-index map for this user, freshest first. Fail-soft: []."""
    out: list[dict] = []
    try:
        r = await get_redis()
        try:
            for repo_key, d in await _scan_json(r, INDEX_PREFIX, uid):
                d["_repo_key"] = repo_key
                out.append(d)
        finally:
            await r.aclose()
    except Exception:
        log.warning("index scan failed (fail-soft empty)", exc_info=True)
    out.sort(key=lambda d: d.get("updated_at") or 0, reverse=True)
    return out


async def load_memories(uid: str) -> list[dict]:
    """Every durable note set for this user, freshest first. Fail-soft: []."""
    out: list[dict] = []
    try:
        r = await get_redis()
        try:
            for repo_key, d in await _scan_json(r, MEMORY_PREFIX, uid):
                if isinstance(d.get("entries"), list):
                    d["_repo_key"] = repo_key
                    out.append(d)
        finally:
            await r.aclose()
    except Exception:
        log.warning("memory scan failed (fail-soft empty)", exc_info=True)

    def _newest(d: dict):
        return max((e.get("distilled_at") or e.get("edited_at") or 0)
                   for e in d["entries"]) if d.get("entries") else 0

    out.sort(key=_newest, reverse=True)
    return out


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
        if w in str(d.get("_repo_key", "")).lower() or w in str(d.get("repo_root", "")).lower():
            return d
    return None


def known_repos(items: list[dict]) -> str:
    return ", ".join(
        repo_name(d.get("repo_root", ""), d.get("_repo_key", "?"))
        + f" ({str(d.get('_repo_key', ''))[:12]})"
        for d in items[:8]) or "none"


async def save_entries(uid: str, repo_key: str, entries: list) -> None:
    """Persist note entries under the kernel's own shape, TTL and LRU cap."""
    if len(entries) > MAX_ENTRIES:
        entries = entries[-MAX_ENTRIES:]
    payload = json.dumps({"user_id": uid, "repo_key": repo_key, "entries": entries})
    r = await get_redis()
    try:
        await r.set(f"{MEMORY_PREFIX}{uid}:{repo_key}", payload, ex=REPO_MEM_TTL)
    finally:
        await r.aclose()


@ext.health_check
async def health(ctx) -> dict:
    return {"status": "ok", "version": ext.version}


def safe_err(e: Exception) -> str:
    """Never let an internal Redis URL/host leak into a chat-facing error."""
    s = str(e)
    return "internal storage error" if "://" in s else s
