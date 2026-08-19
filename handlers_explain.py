"""Memory & Index · The 'where is this actually stored' explainer.

Split out of ``handlers.py``: the deploy validator warns on modules over 300
lines, and the four concerns here (params, reads, explainer, writes) are
genuinely separate. ``handlers.py`` re-exports every name, so `import
handlers` and the tests that use it keep working unchanged.
"""
from __future__ import annotations

from app import (
    MAX_ENTRIES,
    NOTE_CHARS,
    REPO_MEM_TTL,
    ActionResult,
    _user_id,
    chat,
    load_indexes,
    load_memories,
    safe_err,
)
from handlers_params import EmptyParams
from models import MemoryExplainerRecord


@chat.function(
    "explain_memory",
    action_type="read",
    data_model=MemoryExplainerRecord,
    description=("Explain exactly where Webbee's memory about your code is stored, what "
                 "each store holds, who writes it and when it updates — with live counts "
                 "from your own account."),
)
async def fn_explain_memory(ctx, params: EmptyParams) -> ActionResult:
    """Plain-language map of the memory subsystem, filled with the caller's real numbers."""
    uid = _user_id(ctx)
    if not uid:
        return ActionResult.error("Could not identify the calling user.")
    try:
        indexes = await load_indexes(uid)
        memories = await load_memories(uid)
    except Exception as e:
        return ActionResult.error(f"Failed to inspect memory: {safe_err(e)}")

    index_keys = {d.get("_repo_key") for d in indexes}
    note_keys = {m.get("_repo_key") for m in memories}
    total_notes = sum(len(m.get("entries") or []) for m in memories)
    orphans = sorted(k for k in note_keys - index_keys if k)

    stores = [
        {
            "name": "Code index",
            "where": "imperal:repo_index_map:{your_id}:{repo_key}",
            "holds": ("File and language counts, how many functions/classes exist, key "
                      "symbols with file:line, semantic-chunk count, the exact commit."),
            "written_by": "The Webbee terminal coding agent, when it indexes a repo.",
            "updates": "Rebuilt from the source tree on each indexing pass.",
            "editable": False,
            "why_not_editable": ("It is derived from your actual files — the next pass "
                                 "would overwrite any edit, so editing could only mislead."),
            "your_count": len(indexes),
        },
        {
            "name": "Durable notes",
            "where": "imperal:repo_memory:{your_id}:{repo_key}",
            "holds": ("Prose facts learned while coding: conventions, architecture, "
                      "build/test commands, gotchas — with file citations."),
            "written_by": ("A distiller that runs at the tail of a coding turn, after the "
                           "answer was already delivered."),
            "updates": (f"Newest {MAX_ENTRIES} kept per repo; a re-confirmed fact replaces "
                        f"its older copy; each note is capped at {NOTE_CHARS} chars and "
                        f"kept {REPO_MEM_TTL // 86400} days, refreshed on every write."),
            "editable": True,
            "why_not_editable": "",
            "your_count": total_notes,
        },
        {
            "name": "Semantic chunks",
            "where": "Vector store, referenced from the code index",
            "holds": "Embedded slices of your code used for meaning-based search.",
            "written_by": "The same indexing pass that builds the code index.",
            "updates": "Regenerated with the index; vectors_ready shows if search is live.",
            "editable": False,
            "why_not_editable": "Derived data — regenerated from your files.",
            "your_count": sum(d.get("embedded_chunks") or 0 for d in indexes),
        },
    ]

    data = {
        "stores": stores,
        "repo_count": len(index_keys | note_keys),
        "indexed_repo_count": len(indexes),
        "note_repo_count": len(memories),
        "total_notes": total_notes,
        "max_notes_per_repo": MAX_ENTRIES,
        "note_char_limit": NOTE_CHARS,
        "retention_days": REPO_MEM_TTL // 86400,
        "orphan_note_repos": orphans,
    }

    orphan_line = ""
    if orphans:
        orphan_line = (f"\n⚠ {len(orphans)} repo(s) have notes but no current index "
                       f"(usually an older checkout path): {', '.join(k[:12] for k in orphans[:5])}")
    return ActionResult.success(
        data=data,
        summary=(f"Your repo memory: {len(indexes)} code index(es), "
                 f"{total_notes} durable note(s) across {len(memories)} repo(s).\n"
                 f"• Code index — rebuilt from your files each indexing pass (read-only)\n"
                 f"• Durable notes — distilled after coding turns, newest {MAX_ENTRIES} per "
                 f"repo, kept {REPO_MEM_TTL // 86400}d (editable)\n"
                 f"• Semantic chunks — regenerated with the index (read-only)"
                 + orphan_line))
