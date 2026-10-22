"""Memory & Index · Erase one repository's memory — verified, not assumed.

A separate module from ``handlers_writes.py`` on purpose: everything there
edits notes INSIDE a repo's memory, while this removes the repo's memory
entirely. Different blast radius, different action_type, different tests.

Why this can honestly promise "nothing is left":

  Repo memory does NOT live in one place. Besides the code index and the
  durable notes, a repo leaves working memory, goals and plans, proven
  conclusions, saved command outputs, terminal conversations, session
  snapshots and context-graph events in the Tenant Vault. The gateway's
  ``DELETE /v1/memory/repo`` is the vault's one forget door for the place
  ``repo:<key>``: it takes every section at once, stops a Webbee session still
  running on that repo, and names whatever it could not remove.

The delete therefore does NOT stop at asking the vault: ``purge_repo``
re-reads the caller's WHOLE memory afterwards and reports whether anything of
this repo is still there. If it is, this handler says so instead of claiming
success. A repo is resolved by its index, its notes, or — for memory left over
after its index was deleted — by its place in that whole-memory read.
"""
from __future__ import annotations

from app import (
    ActionResult,
    _user_id,
    chat,
    known_repos,
    load_everything,
    load_repo_memory,
    pick,
    purge_repo,
    repo_name,
    safe_err,
)
from handlers_params import DeleteRepoParams
from memory_places import describe, is_orphan, place_title, places, repo_key_of
from models import PurgeRecord


def _orphans(listing) -> list[dict]:
    """Repo places of the whole memory with no index or notes file any more, in
    the shape ``pick`` resolves (key, path, plus the title as a path fragment)."""
    return [{"_repo_key": repo_key_of(p),
             "repo_root": str(p.get("root") or p.get("title") or ""),
             "_title": place_title(p)}
            for p in places(listing) if is_orphan(p) and repo_key_of(p)]


@chat.function(
    "delete_repo",
    action_type="destructive",
    data_model=PurgeRecord,
    effects=["delete:repo_index", "delete:repo_note"],
    event="repo_memory_erased",
    description=(
        "Permanently erase EVERYTHING Webbee holds about one repository — its "
        "code index, durable notes, working memory, goals and plans, proven "
        "conclusions, saved command outputs, terminal conversations, session "
        "snapshots and context-graph events — through the vault's one forget "
        "door, and verify by a fresh read of the whole memory that nothing "
        "survived. Also erases memory left over from a repo whose index was "
        "already deleted. This cannot be undone: only the code index comes back, "
        "if that repo is opened in the Webbee terminal agent again."),
)
async def fn_delete_repo(ctx, params: DeleteRepoParams) -> ActionResult:
    """Erase everything of one repo, then verify the whole memory no longer has it."""
    uid = _user_id(ctx)
    if not uid:
        return ActionResult.error("Could not identify the calling user.")

    want = (params.repo or "").strip()
    if not want:
        return ActionResult.error(
            "Name the repository to erase — this deletes memory permanently, "
            "so it is never applied to a guessed default.")

    try:
        indexes, memories = await load_repo_memory(ctx)
    except Exception as e:
        return ActionResult.error(f"Failed to read repo memory: {safe_err(e)}")

    # Resolve across every store: a repo may exist only as an index, only as
    # notes (sets whose repo_key predates the current formula), or only as
    # memory left over after its index was deleted (an orphan place). Matching
    # one store alone would make the others unerasable — precisely the
    # leftovers this tool exists to remove.
    idx = pick(indexes, want)
    mem = pick(memories, want)
    orphans = _orphans(await load_everything(ctx)) if not (idx or mem) else []
    orphan = pick(orphans, want) if orphans else None
    chosen = idx or mem or orphan
    if chosen is None:
        pool = indexes + memories + orphans
        return ActionResult.error(
            f"No repo matches '{want}'. Known: {known_repos(pool)}"
            if pool else "No repo memory stored yet — nothing to erase.")

    repo_key = str(chosen.get("_repo_key") or "")
    if not repo_key:
        return ActionResult.error("Resolved a repo without a storage key — nothing erased.")

    # Every section is keyed by repo_key, so resolving from any side is
    # enough to erase all of them.
    label = (orphan or {}).get("_title") or repo_name(
        (idx or {}).get("repo_root") or (mem or {}).get("repo_root") or "",
        repo_key)

    try:
        result = await purge_repo(ctx, repo_key)
    except Exception as e:
        return ActionResult.error(f"Failed to erase repo memory: {safe_err(e)}")

    result["repo_label"] = label
    bits = []
    if result["had_index"]:
        bits.append("code index")
    if result["had_notes"]:
        bits.append(f"{result['notes_removed']} note(s)")
    removed = describe(result.get("forgotten") or {})
    what = (removed or " and ".join(bits)) or "nothing (already empty)"

    if not result["verified"]:
        # Never report a clean wipe the re-read does not support.
        # ActionResult.error() carries no data payload, so what survived is
        # NAMED in the message itself.
        left = describe(result.get("left") or {}) or "records of that repo"
        return ActionResult.error(
            f"Asked the vault to erase everything of {label} ({repo_key}), but a "
            f"fresh read of your whole memory still shows: {left}"
            f"{'' if result['deleted'] else ' (the vault reported nothing deleted)'}. "
            f"The wipe is NOT confirmed — retry, and if it persists the storage "
            f"layer needs a look.",
            retryable=True)

    return ActionResult.success(
        data=result,
        summary=(f"Erased everything Webbee held for {label} ({repo_key[:12]}): {what}. "
                 f"A fresh read of your whole memory confirms nothing of it is left. "
                 f"This is unrecoverable; the code index rebuilds only if you open "
                 f"this repo in the Webbee terminal agent again."))
