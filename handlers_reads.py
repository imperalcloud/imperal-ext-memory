"""Memory & Index · Read tools — inventory, one repo's index, one repo's notes.

Split out of ``handlers.py``: the deploy validator warns on modules over 300
lines, and the four concerns here (params, reads, explainer, writes) are
genuinely separate. ``handlers.py`` re-exports every name, so `import
handlers` and the tests that use it keep working unchanged.
"""
from __future__ import annotations

from app import (
    MAX_ENTRIES,
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
)
from handlers_params import EmptyParams, RepoParams, _notes_payload, _resolve_notes
from models import NoteListResponse, RepoIndexRecord, RepoListResponse


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
