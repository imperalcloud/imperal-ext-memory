"""Memory & Index · Erase one repository's memory — verified, not assumed.

A separate module from ``handlers_writes.py`` on purpose: everything there
edits notes INSIDE a repo's memory, while this removes the repo's memory
entirely. Different blast radius, different action_type, different tests.

Why this can honestly promise "nothing is left":

  Repo memory lives in exactly ONE place: the repo's Tenant Vault file
  ``repos/<repo_key>``, which holds the code index AND the durable notes
  together, and which the gateway's ``DELETE /v1/memory/repo`` removes as a
  whole. ``embedded_chunks``/``vectors_ready`` on the index map are a COPIED
  COUNT reported by the terminal client — not a handle to a vector store —
  so there is no second place to clean.

The delete therefore does NOT stop at asking the vault: ``purge_repo``
re-lists the caller's repos afterwards and reports whether this one is still
there. If it is, this handler says so instead of claiming success.
"""
from __future__ import annotations

from app import (
    ActionResult,
    _user_id,
    chat,
    known_repos,
    load_repo_memory,
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
        "afterwards that nothing survived. This cannot be undone: the notes are "
        "gone for good, while the code index only comes back if that repo is "
        "opened in the Webbee terminal agent again."),
)
async def fn_delete_repo(ctx, params: DeleteRepoParams) -> ActionResult:
    """Erase one repo's index + notes, then verify the vault no longer lists it."""
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

    # Index and notes share one vault file keyed by repo_key, so resolving
    # from either side is enough to erase both.
    label = repo_name(
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
    what = " and ".join(bits) if bits else "nothing (already empty)"

    if not result["verified"]:
        # Never report a clean wipe the re-listing does not support.
        # ActionResult.error() carries no data payload, so what survived is
        # NAMED in the message itself.
        return ActionResult.error(
            f"Asked the vault to erase {what} for {label} ({repo_key}), but a fresh "
            f"listing still shows that repo"
            f"{'' if result['deleted'] else ' and the vault reported nothing deleted'}. "
            f"The wipe is NOT confirmed — retry, and if it persists the storage "
            f"layer needs a look.",
            retryable=True)

    return ActionResult.success(
        data=result,
        summary=(f"Erased {what} for {label} ({repo_key[:12]}). "
                 f"Its vault file is removed and a fresh listing confirms it is gone "
                 f"— nothing left. The notes are unrecoverable; the code index rebuilds "
                 f"only if you open this repo in the Webbee terminal agent again."))
