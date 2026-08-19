"""Memory & Index · Erase one repository's memory — verified, not assumed.

A separate module from ``handlers_writes.py`` on purpose: everything there
edits notes INSIDE a repo's memory, while this removes the repo's memory
entirely. Different blast radius, different action_type, different tests.

Why this can honestly promise "nothing is left":

  Repo memory lives in exactly TWO Redis key families and nowhere else —
  ``imperal:repo_index_map:{uid}:{repo_key}`` and
  ``imperal:repo_memory:{uid}:{repo_key}``. That was checked three ways
  before this tool was written: the kernel source that writes them
  (core/repo_index_map.py, core/repo_memory.py), a grep for any SQL table
  behind them (there is none), and a live scan of the running keyspace.
  ``embedded_chunks``/``vectors_ready`` on the index map are a COPIED COUNT
  reported by the terminal client — not a handle to a vector store — so
  there is no third place to clean.

The delete therefore does NOT stop at issuing DEL: ``purge_repo`` re-scans
the keyspace afterwards and reports what survived. If anything did, this
handler says so instead of claiming success.
"""
from __future__ import annotations

from app import (
    ActionResult,
    _user_id,
    chat,
    known_repos,
    load_indexes,
    load_memories,
    pick,
    purge_repo,
    repo_name,
    safe_err,
)
from handlers_params import DeleteRepoParams
from models import PurgeRecord


@chat.function(
    "delete_repo",
    action_type="destructive",
    data_model=PurgeRecord,
    effects=["delete:repo_index", "delete:repo_note"],
    event="repo_memory_erased",
    description=(
        "Permanently erase EVERYTHING Webbee remembers about one repository — "
        "its code index AND all its durable notes — from storage, and verify "
        "afterwards that no key survived. This cannot be undone: the notes are "
        "gone for good, while the code index only comes back if that repo is "
        "opened in the Webbee terminal agent again."),
)
async def fn_delete_repo(ctx, params: DeleteRepoParams) -> ActionResult:
    """Erase one repo's index + notes, then verify the keyspace is clean."""
    uid = _user_id(ctx)
    if not uid:
        return ActionResult.error("Could not identify the calling user.")

    want = (params.repo or "").strip()
    if not want:
        return ActionResult.error(
            "Name the repository to erase — this deletes memory permanently, "
            "so it is never applied to a guessed default.")

    try:
        indexes = await load_indexes(uid)
        memories = await load_memories(uid)
    except Exception as e:
        return ActionResult.error(f"Failed to read repo memory: {safe_err(e)}")

    # Resolve across BOTH stores: a repo may exist only as an index (never
    # any notes) or only as notes (the orphaned sets whose repo_key predates
    # the current formula). Matching one store alone would make the other
    # kind unerasable — precisely the leftovers this tool exists to remove.
    idx = pick(indexes, want)
    mem = pick(memories, want)
    chosen = idx or mem
    if chosen is None:
        pool = indexes + memories
        return ActionResult.error(
            f"No repo matches '{want}'. Known: {known_repos(pool)}"
            if pool else "No repo memory stored yet — nothing to erase.")

    repo_key = str(chosen.get("_repo_key") or "")
    if not repo_key:
        return ActionResult.error("Resolved a repo without a storage key — nothing erased.")

    # Both stores are keyed by repo_key, so resolving from either side is
    # enough to erase the pair.
    label = repo_name(
        (idx or {}).get("repo_root") or (mem or {}).get("repo_root") or "",
        repo_key)

    try:
        result = await purge_repo(uid, repo_key)
    except Exception as e:
        return ActionResult.error(f"Failed to erase repo memory: {safe_err(e)}")

    result["repo_label"] = label
    bits = []
    if result["had_index"]:
        bits.append("code index")
    if result["had_notes"]:
        bits.append(f"{result['notes_removed']} note(s)")
    what = " and ".join(bits) if bits else "nothing (already empty)"

    if not result["verified"]:
        # Never report a clean wipe the re-scan does not support. ActionResult
        # .error() carries no data payload, so the surviving keys are NAMED in
        # the message itself — a bare "something is left" would tell the user
        # the guarantee failed while withholding the one detail that makes it
        # actionable.
        leftovers = result["leftover_keys"]
        shown = ", ".join(sorted(leftovers)[:5])
        more = f" (+{len(leftovers) - 5} more)" if len(leftovers) > 5 else ""
        return ActionResult.error(
            f"Erased {what} for {label}, but the verification scan still finds "
            f"{len(leftovers)} key(s): {shown}{more}. The wipe is NOT confirmed "
            f"— retry, and if they persist the storage layer needs a look.",
            retryable=True)

    return ActionResult.success(
        data=result,
        summary=(f"Erased {what} for {label} ({repo_key[:12]}). "
                 f"{result['keys_deleted']} storage key(s) removed and verified gone — "
                 f"no leftovers. The notes are unrecoverable; the code index rebuilds "
                 f"only if you open this repo in the Webbee terminal agent again."))
