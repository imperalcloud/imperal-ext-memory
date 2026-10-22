"""Memory & Index · Everything Webbee holds, and the one way to forget it.

``memory_overview`` shows the user's WHOLE memory as the vault reports it: the
account (rules, conversations, conclusions, context graph, extension data) and
every repo — including repos whose code index is already deleted but whose
working memory, plans or conversations are still stored. Nothing is filtered.

``forget_memory`` deletes one thing through the vault's one forget door
(``POST /v1/memory/forget``) and then re-reads the whole memory to confirm it
is gone. A separate module from handlers_purge.py: that one resolves a repo by
name for ``delete_repo``; this one takes the exact keys the overview reports,
for every kind of memory.
"""
from __future__ import annotations

from app import ActionResult, _user_id, chat, safe_err
from forget_ops import FORGET_WHAT, forget_and_verify
from handlers_params import EmptyParams, ForgetMemoryParams
from memory_client import memory_api
from memory_places import (
    describe,
    find_conversation,
    find_place,
    find_skeleton,
    is_orphan,
    place_title,
    places,
)
from models_everything import ForgetRecord, MemoryOverviewRecord


def _place_line(p: dict) -> str:
    where = p.get("place")
    note = " — code index deleted, memory left over" if is_orphan(p) else ""
    convs = len(p.get("conversations") or [])
    conv = f"; {convs} conversation(s) listed" if convs else ""
    return (f"• {place_title(p)} ({where}) — {int(p.get('total') or 0):,} records: "
            f"{describe(p.get('counts') or {}, limit=6) or 'nothing'}{conv}{note}")


@chat.function(
    "memory_overview",
    action_type="read",
    data_model=MemoryOverviewRecord,
    description=("Show EVERYTHING Webbee holds about the user, exactly as stored: the "
                 "account (rules, conversations, conclusions, context graph, extension "
                 "data) and every repository (notes, code index, working memory, plans, "
                 "conclusions, saved command outputs, conversations, session snapshots) "
                 "— including memory left over from repos whose code index was deleted. "
                 "Gives the exact keys forget_memory takes."),
)
async def fn_memory_overview(ctx, params: EmptyParams) -> ActionResult:
    """The whole memory, place by place, with plain counts per section."""
    if not _user_id(ctx):
        return ActionResult.error("Could not identify the calling user.")
    try:
        listing = await memory_api(ctx).everything() or {}
    except Exception as e:
        return ActionResult.error(f"Failed to read your memory: {safe_err(e)}", retryable=True)

    rows = places(listing)
    data = [{**p, "title": place_title(p), "orphan": is_orphan(p)} for p in rows]
    total = int(listing.get("total") or sum(int(p.get("total") or 0) for p in rows))
    orphans = sum(1 for p in rows if is_orphan(p))
    record = MemoryOverviewRecord.model_validate({
        "places": data, "place_count": len(rows), "orphan_count": orphans, "total": total})
    if not rows:
        return ActionResult.success(record, summary="Webbee holds nothing about you — your memory is empty.")
    lines = [_place_line(p) for p in rows[:20]]
    more = f"\n(+{len(rows) - 20} more places)" if len(rows) > 20 else ""
    return ActionResult.success(
        record,
        summary=(f"Webbee holds {total:,} records in {len(rows)} place(s)"
                 f"{f', {orphans} of them left over from deleted repos' if orphans else ''}:\n"
                 + "\n".join(lines) + more))


def _check_params(what: str, key: str, project_id: str) -> str:
    """An error message when the request is not exact enough to delete on."""
    if what not in FORGET_WHAT:
        return f"Unknown kind '{what}'. Use one of: {', '.join(FORGET_WHAT)}."
    if what != "all" and not key:
        return (f"Name exactly which {what} to forget (the key memory_overview shows) "
                "— memory is never deleted on a guessed default.")
    if what == "place" and key != "account" and not key.startswith("repo:"):
        return "A place is 'account' or 'repo:<repo_key>', as memory_overview lists it."
    if what == "evidence" and not project_id:
        return "A conclusion is named by its fact id AND its project_id — give both."
    return ""


def _target(listing: dict, what: str, key: str) -> tuple[str, bool]:
    """(plain name of the thing, whether a fresh read shows it exists). Kinds the
    listing does not show one by one count as existing — the door decides."""
    if what == "all":
        return "everything Webbee holds about you", True
    if what == "place":
        p = find_place(listing, key)
        return (f"everything of {place_title(p)} ({key})" if p else key), p is not None
    if what == "conversation":
        _, c = find_conversation(listing, key)
        return (f"conversation '{(c or {}).get('title') or key}'", c is not None)
    if what == "skeleton":
        return f"the data of extension {key}", find_skeleton(listing, key) is not None
    return f"{what} {key}", True


@chat.function(
    "forget_memory",
    action_type="destructive",
    data_model=ForgetRecord,
    effects=["delete:memory"],
    event="memory_forgotten",
    description=("Permanently forget part of what Webbee holds about the user — one "
                 "repo or the account (every section of it), one conversation and what "
                 "its session left, one rule, one conclusion, a reality matrix, one "
                 "extension's data, a context-graph subject, or everything — through the "
                 "vault's one forget door. A running Webbee session on it is stopped "
                 "first. A fresh read of the whole memory afterwards confirms nothing is "
                 "left. Use the exact keys memory_overview reports. Cannot be undone."),
)
async def fn_forget_memory(ctx, params: ForgetMemoryParams) -> ActionResult:
    """Forget one thing, then verify by re-reading the whole memory."""
    if not _user_id(ctx):
        return ActionResult.error("Could not identify the calling user.")
    what = (params.what or "").strip().lower()
    key = (params.key or "").strip()
    project_id = (params.project_id or "").strip()
    problem = _check_params(what, key, project_id)
    if problem:
        return ActionResult.error(problem)

    try:
        before = await memory_api(ctx).everything() or {}
    except Exception as e:
        return ActionResult.error(f"Failed to read your memory: {safe_err(e)}", retryable=True)
    name, exists = _target(before, what, key)
    if not exists:
        known = ", ".join(p.get("place") for p in places(before)[:10]) or "none"
        return ActionResult.error(f"Nothing named '{key}' is stored for {what}. Places: {known}")

    try:
        result = await forget_and_verify(ctx, what, key, project_id)
    except Exception as e:
        return ActionResult.error(f"Failed to forget {name}: {safe_err(e)}", retryable=True)

    if not result["verified"]:
        # ActionResult.error() carries no data, so what survived is named here.
        return ActionResult.error(
            f"Asked the vault to forget {name}, but not everything is gone — still "
            f"there: {describe(result['left']) or 'unreported records'}. NOT confirmed; "
            f"retry, and if it persists the storage layer needs a look.",
            retryable=True)

    removed = describe(result["forgotten"]) or "nothing was stored"
    stopped = (f" Stopped {len(result['stopped_sessions'])} running Webbee session(s) first."
               if result["stopped_sessions"] else "")
    return ActionResult.success(
        ForgetRecord.model_validate(result),
        summary=(f"Forgot {name}: {removed}.{stopped} A fresh read of your whole memory "
                 f"confirms nothing of it is left ({result['total_after']:,} records remain "
                 f"in total). This cannot be undone."))
