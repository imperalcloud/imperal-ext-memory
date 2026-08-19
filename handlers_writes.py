"""Memory & Index · Write tools — durable notes ONLY (the code index is never writable).

Split out of ``handlers.py``: the deploy validator warns on modules over 300
lines, and the four concerns here (params, reads, explainer, writes) are
genuinely separate. ``handlers.py`` re-exports every name, so `import
handlers` and the tests that use it keep working unchanged.
"""
from __future__ import annotations

import time

from app import (
    MAX_ENTRIES,
    ActionResult,
    _user_id,
    chat,
    known_repos,
    load_indexes,
    load_memories,
    pick,
    safe_err,
    sanitize_note,
    save_entries,
)
from handlers_params import (
    AddNoteParams,
    DeleteNoteParams,
    EditNoteParams,
    _resolve_notes,
)
from models import NoteOpRecord


@chat.function(
    "add_note",
    action_type="write",
    data_model=NoteOpRecord,
    effects=["create:repo_note"],
    event="note_added",
    description=("Teach Webbee a durable fact about a repository — it is remembered across "
                 "machines and surfaces, and used on later coding turns."),
)
async def fn_add_note(ctx, params: AddNoteParams) -> ActionResult:
    """Append one sanitised note to a repo's durable memory."""
    uid = _user_id(ctx)
    if not uid:
        return ActionResult.error("Could not identify the calling user.")
    text = sanitize_note(params.note)
    if not text:
        return ActionResult.error("The note is empty after sanitising — nothing stored.")

    try:
        mems = await load_memories(uid)
        indexes = await load_indexes(uid)
        chosen = pick(mems, params.repo)
        if chosen is None:
            # No note-set yet for this repo: fall back to a known indexed repo.
            idx = pick(indexes, params.repo)
            if idx is None:
                pool = mems + indexes
                return ActionResult.error(
                    f"No repo matches '{params.repo}'. Known: {known_repos(pool)}"
                    if params.repo else
                    "No repos known yet — open one in the Webbee terminal agent first.")
            repo_key, entries = idx.get("_repo_key", ""), []
        else:
            repo_key, entries = chosen.get("_repo_key", ""), list(chosen.get("entries") or [])

        now = int(time.time())
        # Upsert like the kernel distiller: a re-stated fact refreshes, never duplicates.
        norm = " ".join(text.lower().split())
        entries = [e for e in entries
                   if " ".join(str(e.get("note", "")).lower().split()) != norm]
        entries.append({
            "note": text,
            "citations": [sanitize_note(c) for c in (params.citations or []) if c][:5],
            "source": "user",
            "edited_at": now,
            "distilled_at": now,
        })
        evicted = max(0, len(entries) - MAX_ENTRIES)
        await save_entries(uid, repo_key, entries)
    except Exception as e:
        return ActionResult.error(f"Failed to store the note: {safe_err(e)}")

    tail = f" (oldest {evicted} dropped — {MAX_ENTRIES} note cap)" if evicted else ""
    return ActionResult.success(
        data={"repo_key": repo_key, "note": text,
              "total": min(len(entries), MAX_ENTRIES)},
        summary=f"Remembered for repo {repo_key[:12]}: “{text}”{tail}")


@chat.function(
    "edit_note",
    action_type="write",
    data_model=NoteOpRecord,
    effects=["update:repo_note"],
    event="note_edited",
    description=("Correct one durable note by its position number (see list_notes) — the "
                 "text is replaced and marked as edited by you."),
)
async def fn_edit_note(ctx, params: EditNoteParams) -> ActionResult:
    """Replace the text of one existing note."""
    uid = _user_id(ctx)
    if not uid:
        return ActionResult.error("Could not identify the calling user.")
    text = sanitize_note(params.note)
    if not text:
        return ActionResult.error("The new text is empty after sanitising — nothing changed.")

    try:
        chosen, err = await _resolve_notes(uid, params.repo)
        if err:
            return ActionResult.error(err)
        repo_key = chosen.get("_repo_key", "")
        entries = list(chosen.get("entries") or [])
        if not 1 <= params.position <= len(entries):
            return ActionResult.error(
                f"Position {params.position} does not exist — repo {repo_key[:12]} has "
                f"{len(entries)} note(s). Use list_notes to see the numbers.")
        old = str(entries[params.position - 1].get("note") or "")
        entries[params.position - 1] = {
            **entries[params.position - 1],
            "note": text,
            "source": "user-edited",
            "edited_at": int(time.time()),
        }
        await save_entries(uid, repo_key, entries)
    except Exception as e:
        return ActionResult.error(f"Failed to edit the note: {safe_err(e)}")

    return ActionResult.success(
        data={"repo_key": repo_key, "position": params.position,
              "note": text, "previous": old},
        summary=f"Note {params.position} for repo {repo_key[:12]} updated:\n"
                f"was: “{old}”\nnow: “{text}”")


@chat.function(
    "delete_note",
    action_type="write",
    data_model=NoteOpRecord,
    effects=["delete:repo_note"],
    event="note_deleted",
    description=("Make Webbee forget one durable note by its position number "
                 "(see list_notes). The note text is echoed back so nothing vanishes silently."),
)
async def fn_delete_note(ctx, params: DeleteNoteParams) -> ActionResult:
    """Remove one note from a repo's durable memory."""
    uid = _user_id(ctx)
    if not uid:
        return ActionResult.error("Could not identify the calling user.")
    try:
        chosen, err = await _resolve_notes(uid, params.repo)
        if err:
            return ActionResult.error(err)
        repo_key = chosen.get("_repo_key", "")
        entries = list(chosen.get("entries") or [])
        if not 1 <= params.position <= len(entries):
            return ActionResult.error(
                f"Position {params.position} does not exist — repo {repo_key[:12]} has "
                f"{len(entries)} note(s). Use list_notes to see the numbers.")
        removed = str(entries.pop(params.position - 1).get("note") or "")
        await save_entries(uid, repo_key, entries)
    except Exception as e:
        return ActionResult.error(f"Failed to delete the note: {safe_err(e)}")

    return ActionResult.success(
        data={"repo_key": repo_key, "removed": removed, "remaining": len(entries)},
        summary=f"Forgotten for repo {repo_key[:12]}: “{removed}”. "
                f"{len(entries)} note(s) left.")
