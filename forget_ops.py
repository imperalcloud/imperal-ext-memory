"""Memory & Index · Forgetting — through the vault's one door, then verified.

Everything Webbee keeps about a user is spread over many vault sections
(notes, code index, working memory, plans, conclusions, saved command outputs,
conversations, session snapshots, the context graph, extension data). Deleting
section by section from here would always miss the next section someone adds,
which is how a "cleared" memory once came back in a new session. So every
deletion goes through the gateway's ONE forget door, which takes all sections
of the named thing, stops a Webbee session still running on it, and answers
409 with what is ``left`` when it could not take everything.

This module never trusts that answer alone: after the delete it re-reads the
WHOLE memory (``GET /v1/memory/all``) and checks the thing is really gone. No
caching, no local state, no direct vault access — only the gateway.
"""
from __future__ import annotations

import logging

from imperal_sdk.errors import APIError

from memory_client import memory_api
from memory_places import (
    find_conversation,
    find_place,
    find_skeleton,
    flat_counts,
    left_from_error,
    places,
)

log = logging.getLogger("memory-index")

# What the forget door accepts, and which of them name an item by key.
FORGET_WHAT = ("place", "conversation", "law", "evidence", "reality", "skeleton", "graph", "all")


async def load_everything(ctx) -> dict | None:
    """The whole memory (``GET /v1/memory/all``) for a VIEW. Fail-soft: None on
    an outage, so a reader can say "could not read" instead of "nothing"."""
    try:
        listing = await memory_api(ctx).everything()
    except Exception:
        log.warning("whole-memory read failed (fail-soft None)", exc_info=True)
        return None
    return listing if isinstance(listing, dict) else None


def _reply_or_left(e: APIError) -> dict:
    """A 409 "not everything was forgotten" as a reply: nothing claimed, the
    left-over named (parsed back from the error text, else the text itself)."""
    return {"ok": False, "deleted": False,
            "left": left_from_error(e) or {"unreported": str(e)[:200]}}


async def purge_repo(ctx, repo_key: str) -> dict:
    """Delete EVERY stored trace of one repo for this user, then VERIFY.

    Repo memory does not live in one place: besides the notes and code index it
    spans working memory, plans, conclusions, saved command outputs, terminal
    conversations, session snapshots and context-graph events. The vault's one
    forget door (``DELETE /v1/memory/repo`` is that door for ``repo:<key>``)
    takes them all and reports what it removed and what is ``left``.

    Deliberately three phases — count, delete, re-read — because a delete that
    only reports its own intent is not a guarantee. ``verified`` comes from a
    fresh read of the WHOLE memory AFTER the delete: the place ``repo:<key>``
    must be gone. That read is direct, not fail-soft: an outage there must fail
    the purge, not read as "gone". A 409 is a result, not a crash: it is
    reported as unverified with what was left.
    """
    api = memory_api(ctx)
    place = f"repo:{repo_key}"
    note_count = len((await api.repo(repo_key) or {}).get("entries") or [])
    had_index = isinstance((await api.index(repo_key) or {}).get("map"), dict)
    before = find_place(await api.everything(), place)

    try:
        reply = await api.delete_repo(repo_key) or {}
    except APIError as e:
        if e.status_code != 409:
            raise
        reply = _reply_or_left(e)

    # Re-read everything rather than trust the delete's own return value.
    after = find_place(await api.everything(), place)
    left = flat_counts(reply.get("left") or {})
    if after is not None:
        left = {**flat_counts(after.get("counts") or {}), **left} or {"records": 1}

    forgotten = flat_counts(reply.get("forgotten") or {})
    if not forgotten and before is not None and after is None:
        forgotten = flat_counts(before.get("counts") or {})

    return {
        "repo_key": repo_key,
        "had_index": had_index,
        "had_notes": note_count > 0,
        "notes_removed": note_count,
        "deleted": bool(reply.get("deleted") or reply.get("ok")),
        "forgotten": forgotten,
        "records_removed": sum(forgotten.values()),
        "left": left,
        "still_listed": after is not None,
        "verified": after is None and not left,
    }


def _still_there(listing: dict, what: str, key: str) -> dict | None:
    """What a fresh read still shows of the forgotten thing, as counts; None when
    it is gone (or, for items the listing does not show one by one, unknown)."""
    if what == "place":
        p = find_place(listing, key)
        return flat_counts(p.get("counts") or {}) or {"records": 1} if p else None
    if what == "conversation":
        _, c = find_conversation(listing, key)
        return {"conversation.conversations": 1} if c else None
    if what == "skeleton":
        s = find_skeleton(listing, key)
        return {"skeleton.sections": len(s.get("sections") or []) or 1} if s else None
    if what == "all":
        rest: dict[str, int] = {}
        for p in places(listing):
            for k, v in flat_counts(p.get("counts") or {}).items():
                rest[k] = rest.get(k, 0) + v
        rest = {k: v for k, v in rest.items() if v}
        return rest or None
    return None


async def forget_and_verify(ctx, what: str, key: str = "", project_id: str = "") -> dict:
    """Forget one thing through the vault's door, then re-read the whole memory.

    Returns ``{"what", "key", "ok", "forgotten", "left", "stopped_sessions",
    "caches_dropped", "verified", "total_after"}``. ``verified`` is True only
    when the door reported nothing left AND the fresh read no longer shows the
    thing (a rule is checked against a fresh rule listing). A 409 comes back as
    ``ok: False`` with ``left`` named; any other failure raises.
    """
    api = memory_api(ctx)
    try:
        reply = await api.forget(what, key, project_id) or {}
    except APIError as e:
        if e.status_code != 409:
            raise
        reply = _reply_or_left(e)

    listing = await api.everything() or {}
    left = flat_counts(reply.get("left") or {})
    seen = _still_there(listing, what, key)
    if what == "law" and key:
        facts = (await api.facts() or {}).get("facts") or []
        if any(isinstance(f, dict) and str(f.get("fact_id")) == key for f in facts):
            seen = {"law.law": 1}
    if seen:
        left = {**seen, **left}

    return {
        "what": what, "key": key, "project_id": project_id,
        "ok": bool(reply.get("ok", not left)) and not left,
        # one account item answers with a bare count (rule, conclusion, extension, graph subject)
        "forgotten": (flat_counts(reply.get("forgotten") or {}) if isinstance(reply.get("forgotten"), dict)
                      else ({what: int(reply.get("forgotten") or 0)} if reply.get("forgotten") else {})),
        "left": left,
        "stopped_sessions": list(reply.get("stopped_sessions") or []),
        "caches_dropped": int(reply.get("caches_dropped") or 0),
        "verified": not left,
        "total_after": int(listing.get("total") or 0),
    }


__all__ = ["FORGET_WHAT", "load_everything", "purge_repo", "forget_and_verify"]
