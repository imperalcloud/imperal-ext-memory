"""Memory & Index · Chat function handlers — FACTS out, narrator phrases (ICNLI).

Read tools describe what Webbee holds; write tools change ONLY durable notes.
The code index is never writable here: it is regenerated from the source tree
on the next indexing pass, so an edit would be silently discarded — offering
the control would be a lie.

Every handler is fail-soft: a Redis outage yields a clear "nothing stored yet"
answer or a plain error, never an exception into the chat turn.
"""
from __future__ import annotations

import time

from pydantic import BaseModel, Field

from app import (
    MAX_ENTRIES,
    NOTE_CHARS,
    REPO_MEM_TTL,
    ActionResult,
    _user_id,
    age,
    chat,
    known_repos,
    load_indexes,
    load_memories,
    pick,
    repo_name,
    safe_err,
    sanitize_note,
    save_entries,
)
from models import (
    MemoryExplainerRecord,
    NoteListResponse,
    NoteOpRecord,
    RepoIndexRecord,
    RepoListResponse,
)


class EmptyParams(BaseModel):
    """No parameters needed."""


class RepoParams(BaseModel):
    repo: str = Field(
        default="",
        description=("Which repo — its repo_key, or any fragment of its path/name. "
                     "Empty = the most recently touched one."),
    )


class AddNoteParams(BaseModel):
    note: str = Field(description=f"The fact to remember (max {NOTE_CHARS} chars)")
    repo: str = Field(
        default="",
        description="Which repo — repo_key or path fragment. Empty = most recent.")
    citations: list[str] = Field(
        default_factory=list,
        description="Optional file paths this fact is about, e.g. ['app/billing/service.py']")


class EditNoteParams(BaseModel):
    position: int = Field(
        description="Which note to change — its position number from list_notes (1-based)")
    note: str = Field(description=f"The corrected text (max {NOTE_CHARS} chars)")
    repo: str = Field(
        default="",
        description="Which repo — repo_key or path fragment. Empty = most recent.")


class DeleteNoteParams(BaseModel):
    position: int = Field(
        description="Which note to forget — its position number from list_notes (1-based)")
    repo: str = Field(
        default="",
        description="Which repo — repo_key or path fragment. Empty = most recent.")


def _entry_written(e: dict) -> str:
    return age(e.get("edited_at") or e.get("distilled_at"))


def _notes_payload(repo_key: str, entries: list) -> list[dict]:
    """Newest first for a reader; position is the 1-based storage index."""
    out = []
    for idx, e in enumerate(entries, start=1):
        if not isinstance(e, dict):
            continue
        out.append({
            "note": str(e.get("note") or ""),
            "citations": e.get("citations") or [],
            "repo_key": repo_key,
            "distilled_at": e.get("distilled_at"),
            "distilled_git_ref": e.get("distilled_git_ref"),
            "edited_at": e.get("edited_at"),
            "source": e.get("source") or ("edited" if e.get("edited_at") else "distilled"),
            "position": idx,
            "written": _entry_written(e),
        })
    out.reverse()
    return out


async def _resolve_notes(uid: str, want: str):
    """(memory_dict, error_message) for a repo selector."""
    mems = await load_memories(uid)
    if not mems:
        return None, ("No durable notes stored yet. They build up automatically as the "
                      "Webbee terminal agent works in a repository.")
    chosen = pick(mems, want)
    if chosen is None:
        return None, f"No stored notes match '{want}'. Known: {known_repos(mems)}"
    return chosen, None


# ── Reads ─────────────────────────────────────────────────────────────

@chat.function(
    "list_repos",
    action_type="read",
    data_model=RepoListResponse,
    description=("List every repository Webbee holds memory for — code index size, "
                 "languages, how many durable notes, and how fresh each one is. "
                 "Works on every surface (panel, Telegram, terminal)."),
)
async def fn_list_repos(ctx, params: EmptyParams) -> ActionResult:
    """Inventory of the caller's repo memory: index + notes, merged per repo."""
    uid = _user_id(ctx)
    if not uid:
        return ActionResult.error("Could not identify the calling user.")
    try:
        indexes = await load_indexes(uid)
        memories = await load_memories(uid)
    except Exception as e:
        return ActionResult.error(f"Failed to read repo memory: {safe_err(e)}")

    notes_by_key = {m["_repo_key"]: m for m in memories}
    rows: list[dict] = []
    for d in indexes:
        key = d.get("_repo_key", "")
        mem = notes_by_key.pop(key, None)
        rows.append({
            "repo_key": key,
            "repo_root": d.get("repo_root"),
            "file_count": d.get("file_count"),
            "languages": d.get("languages"),
            "symbol_kinds": d.get("symbol_kinds"),
            "embedded_chunks": d.get("embedded_chunks"),
            "vectors_ready": d.get("vectors_ready"),
            "note_count": len(mem.get("entries") or []) if mem else 0,
            "git_ref": (d.get("git_ref") or "")[:12],
            "branch": d.get("branch"),
            "indexed": age(d.get("updated_at")),
            "has_index": True,
            "has_notes": bool(mem),
        })
    # Notes with no matching index — real and worth surfacing, not hidden.
    for key, mem in notes_by_key.items():
        rows.append({
            "repo_key": key,
            "note_count": len(mem.get("entries") or []),
            "indexed": "no index",
            "has_index": False,
            "has_notes": True,
        })

    if not rows:
        return ActionResult.success(
            data=[],
            summary=("Nothing stored yet. Open a repo in the Webbee terminal agent — "
                     "the index it builds and the notes it distills show up here."))

    lines = []
    for r in rows[:12]:
        name = repo_name(r.get("repo_root", ""), r.get("repo_key", "?"))
        if r["has_index"]:
            lines.append(f"• {name} — {r.get('file_count') or 0} files, "
                         f"{r.get('note_count') or 0} notes, indexed {r['indexed']}")
        else:
            lines.append(f"• {r['repo_key'][:12]} — {r['note_count']} notes, no code index")
    more = f"\n(+{len(rows) - 12} more)" if len(rows) > 12 else ""
    return ActionResult.success(
        data=rows,
        summary=f"{len(rows)} repo(s) in memory:\n" + "\n".join(lines) + more)


@chat.function(
    "get_index",
    action_type="read",
    data_model=RepoIndexRecord,
    description=("Show the code index for ONE repository: file and language breakdown, "
                 "how many functions/classes are indexed, key symbols with file:line, "
                 "semantic-search status, and the exact commit the index was built at."),
)
async def fn_get_index(ctx, params: RepoParams) -> ActionResult:
    """The full structural map Webbee holds for one repository."""
    uid = _user_id(ctx)
    if not uid:
        return ActionResult.error("Could not identify the calling user.")
    try:
        indexes = await load_indexes(uid)
    except Exception as e:
        return ActionResult.error(f"Failed to read the code index: {safe_err(e)}")
    if not indexes:
        return ActionResult.success(
            data={},
            summary=("No code index yet. Open the repo in the Webbee terminal agent — "
                     "the index it builds becomes readable here."))
    chosen = pick(indexes, params.repo)
    if chosen is None:
        return ActionResult.error(
            f"No indexed repo matches '{params.repo}'. Known: {known_repos(indexes)}")

    d = {k: v for k, v in chosen.items() if not k.startswith("_")}
    d["repo_key"] = chosen.get("_repo_key", "")
    d["indexed"] = age(chosen.get("updated_at"))

    langs = ", ".join(f"{k}={v}" for k, v in (d.get("languages") or {}).items()) or "n/a"
    syms = ", ".join(f"{k}={v}" for k, v in (d.get("symbol_kinds") or {}).items()) or "n/a"
    name = repo_name(d.get("repo_root", ""), d["repo_key"])
    return ActionResult.success(
        data=d,
        summary=(f"{name} @ {(d.get('git_ref') or '')[:12] or 'no commit'} "
                 f"({d.get('branch') or 'no branch'}), indexed {d['indexed']}\n"
                 f"• {d.get('file_count') or 0} files — {langs}\n"
                 f"• symbols: {syms}\n"
                 f"• semantic chunks: {d.get('embedded_chunks') or 0} "
                 f"(search {'ready' if d.get('vectors_ready') else 'not ready'})"))


@chat.function(
    "list_notes",
    action_type="read",
    data_model=NoteListResponse,
    description=("Show the durable notes Webbee has learned about a repository — the "
                 "cloud-side WEBBEE.md: conventions, gotchas, where things live. Each "
                 "note carries a position number for editing and when it was written."),
)
async def fn_list_notes(ctx, params: RepoParams) -> ActionResult:
    """Durable notes for one repo, newest first, with edit positions."""
    uid = _user_id(ctx)
    if not uid:
        return ActionResult.error("Could not identify the calling user.")
    try:
        chosen, err = await _resolve_notes(uid, params.repo)
    except Exception as e:
        return ActionResult.error(f"Failed to read notes: {safe_err(e)}")
    if err:
        return (ActionResult.error(err) if params.repo
                else ActionResult.success(data=[], summary=err))

    key = chosen.get("_repo_key", "")
    rows = _notes_payload(key, chosen.get("entries") or [])
    if not rows:
        return ActionResult.success(
            data=[], summary=f"Repo {key[:12]} has no notes stored.")

    lines = []
    for r in rows[:20]:
        cite = f"  [{r['citations'][0]}]" if r["citations"] else ""
        lines.append(f"{r['position']}. {r['note']}{cite}  ({r['written']})")
    more = f"\n(+{len(rows) - 20} older)" if len(rows) > 20 else ""
    return ActionResult.success(
        data=rows,
        summary=(f"{len(rows)} note(s) for repo {key[:12]} "
                 f"(cap {MAX_ENTRIES}, kept {REPO_MEM_TTL // 86400}d):\n"
                 + "\n".join(lines) + more))


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


# ── Writes (notes only) ───────────────────────────────────────────────

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
