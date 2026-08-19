"""Memory & Index · Panels — see, understand and edit Webbee's repo brain.

Three surfaces:

* ``repos``   (left)   — inventory: every repo Webbee holds memory for.
* ``memory``  (center) — one repo in full: the code index, every durable note
                         with edit/delete controls, and an add-note form.
* ``storage`` (center) — the explainer: which Redis key holds what, who writes
                         it, when it updates, what the caps are — with LIVE
                         numbers from this user's own data, not prose claims.

Write controls exist ONLY for durable notes. The code index is regenerated
from the source tree on the next indexing pass, so an edit control there would
promise something the platform silently discards.
"""
from __future__ import annotations

import logging

from imperal_sdk import ui

from app import (
    INDEX_PREFIX,
    MAX_ENTRIES,
    MEMORY_PREFIX,
    NOTE_CHARS,
    REPO_MEM_TTL,
    _user_id,
    age,
    ext,
    load_indexes,
    load_memories,
    pick,
    repo_name,
)

log = logging.getLogger("memory-index")

_RETENTION_DAYS = REPO_MEM_TTL // 86400


def _err(message: str) -> ui.Stack:
    return ui.Stack(children=[ui.Alert(message=message, type="error")])


def _empty(title: str, message: str) -> ui.Stack:
    """Empty state. ui.Empty carries only the message, so the headline is a
    separate ui.Header — the component takes (message, icon, action) and
    silently has no title/description slot."""
    return ui.Stack(direction="v", gap=2, children=[
        ui.Header(text=title, level=3),
        ui.Empty(message=message, icon="BrainCircuit"),
    ])


async def _inventory(uid: str) -> list[dict]:
    """Merge index maps + note sets into one per-repo inventory."""
    indexes = await load_indexes(uid)
    memories = await load_memories(uid)
    by_key: dict[str, dict] = {}

    for d in indexes:
        key = d.get("_repo_key", "")
        by_key[key] = {
            "repo_key": key,
            "repo_root": d.get("repo_root") or "",
            "file_count": d.get("file_count") or 0,
            "languages": d.get("languages") or {},
            "symbol_kinds": d.get("symbol_kinds") or {},
            "embedded_chunks": d.get("embedded_chunks") or 0,
            "vectors_ready": bool(d.get("vectors_ready")),
            "git_ref": (d.get("git_ref") or "")[:12],
            "branch": d.get("branch") or "",
            "indexed": age(d.get("updated_at")),
            "updated_at": d.get("updated_at") or 0,
            "note_count": 0,
            "has_index": True,
            "has_notes": False,
        }

    for m in memories:
        key = m.get("_repo_key", "")
        entries = [e for e in (m.get("entries") or []) if isinstance(e, dict)]
        row = by_key.setdefault(key, {
            "repo_key": key, "repo_root": "", "file_count": 0, "languages": {},
            "symbol_kinds": {}, "embedded_chunks": 0, "vectors_ready": False,
            "git_ref": "", "branch": "", "indexed": "unknown", "updated_at": 0,
            "note_count": 0, "has_index": False, "has_notes": False,
        })
        row["note_count"] = len(entries)
        row["has_notes"] = bool(entries)

    rows = list(by_key.values())
    rows.sort(key=lambda r: (r.get("updated_at") or 0, r.get("note_count") or 0), reverse=True)
    return rows


@ext.panel("repos", slot="left", title="Memory & Index", icon="BrainCircuit", refresh="manual")
async def repos_panel(ctx, **kwargs):
    """Inventory of every repository Webbee holds memory for."""
    uid = _user_id(ctx)
    if not uid:
        return _err("Could not identify you — reopen the panel.")
    try:
        rows = await _inventory(uid)
    except Exception as e:
        log.error("repos panel load error: %s", e)
        return _err("Could not load your repo memory — try again shortly.")

    if not rows:
        return _empty(
            "No repo memory yet",
            "Open a repository in the Webbee terminal agent. The code index it "
            "builds and the notes it distils show up here automatically.")

    indexed = sum(1 for r in rows if r["has_index"])
    noted = sum(1 for r in rows if r["has_notes"])
    total_notes = sum(r["note_count"] for r in rows)

    children = [
        ui.Card(title="What Webbee remembers", content=ui.Stack(direction="v", gap=1, children=[
            ui.Stats(children=[
                ui.Stat(label="Repos", value=str(len(rows))),
                ui.Stat(label="Indexed", value=str(indexed)),
                ui.Stat(label="With notes", value=str(noted)),
                ui.Stat(label="Notes", value=str(total_notes)),
            ]),
            ui.Button(label="How is this stored?", variant="secondary", icon="HelpCircle",
                      on_click=ui.Call("__panel__storage")),
        ])),
    ]

    items = []
    for r in rows:
        badges = []
        if r["has_index"]:
            badges.append(f"{r['file_count']} files")
        if r["has_notes"]:
            badges.append(f"{r['note_count']} notes")
        if not r["has_index"]:
            badges.append("notes only")
        items.append(ui.ListItem(
            id=r["repo_key"],
            title=repo_name(r["repo_root"], r["repo_key"]),
            subtitle=" · ".join(badges) + (f" · indexed {r['indexed']}" if r["has_index"] else ""),
            on_click=ui.Call("__panel__memory", repo=r["repo_key"]),
        ))

    children.append(ui.Section(title="Repositories", children=[ui.List(items=items)]))
    return ui.Stack(direction="v", gap=2, children=children)


def _index_card(d: dict) -> ui.Card:
    """The structural map — read-only by design."""
    langs = d.get("languages") or {}
    kinds = d.get("symbol_kinds") or {}
    lang_txt = ", ".join(f"{k} {v}" for k, v in sorted(
        langs.items(), key=lambda kv: kv[1], reverse=True)) or "—"
    kind_txt = ", ".join(f"{k} {v}" for k, v in sorted(
        kinds.items(), key=lambda kv: kv[1], reverse=True)) or "—"

    rows = [
        {"key": "Path on disk", "value": d.get("repo_root") or "—"},
        {"key": "Repo key", "value": d.get("_repo_key") or "—"},
        {"key": "Indexed at commit", "value": (d.get("git_ref") or "—")[:12]},
        {"key": "Branch", "value": d.get("branch") or "—"},
        {"key": "Files", "value": str(d.get("file_count") or 0)},
        {"key": "Languages", "value": lang_txt},
        {"key": "Symbols", "value": kind_txt},
        {"key": "Semantic chunks", "value": str(d.get("embedded_chunks") or 0)},
        {"key": "Semantic search", "value": "ready" if d.get("vectors_ready") else "not ready"},
        {"key": "Endpoints / schemas",
         "value": f"{d.get('endpoint_count') or 0} / {d.get('schema_count') or 0}"},
        {"key": "Last rebuilt", "value": age(d.get("updated_at"))},
    ]

    content = [
        ui.Alert(type="info", message=(
            "Read-only: this map is rebuilt from your source tree every time the "
            "terminal agent indexes the repo, so any manual edit would be discarded.")),
        ui.KeyValue(items=rows),
    ]

    tops = [str(s) for s in (d.get("top_symbols") or [])][:20]
    if tops:
        content.append(ui.Section(title="Key symbols", children=[
            ui.List(items=[ui.ListItem(id=f"sym-{i}", title=s) for i, s in enumerate(tops)]),
        ]))

    return ui.Card(title="Code index", content=ui.Stack(direction="v", gap=2, children=content))


def _notes_card(repo_key: str, entries: list) -> ui.Card:
    """Durable notes — every one editable and deletable by its owner."""
    children = [
        ui.Alert(type="info", message=(
            f"Editable. Notes are distilled at the end of a coding turn, kept for "
            f"{_RETENTION_DAYS} days (refreshed on every write), and capped at the "
            f"{MAX_ENTRIES} newest per repo.")),
    ]

    if not entries:
        children.append(ui.Empty(
            message=("No notes for this repo yet — they appear automatically as "
                     "Webbee works in this repository."),
            icon="BrainCircuit"))
    else:
        rows = []
        for idx, e in enumerate(entries, start=1):
            if not isinstance(e, dict):
                continue
            text = str(e.get("note") or "")
            cites = [str(c) for c in (e.get("citations") or [])]
            written = age(e.get("edited_at") or e.get("distilled_at"))
            origin = "you edited" if e.get("edited_at") else "distilled"
            ref = str(e.get("distilled_git_ref") or "")[:12]
            meta = f"{origin} {written}" + (f" @ {ref}" if ref else "")
            rows.append(ui.Section(title=f"#{idx} · {meta}", children=[
                ui.Text(content=text),
                ui.Text(content=("cites: " + ", ".join(cites)) if cites else "no file cited"),
                ui.Stack(direction="h", gap=1, children=[
                    ui.Button(label="Edit", variant="secondary", icon="Pencil",
                              on_click=ui.Call("edit_note",
                                               position=idx, repo=repo_key, note=text)),
                    ui.Button(label="Forget", variant="danger", icon="Trash2",
                              on_click=ui.Call("delete_note", position=idx, repo=repo_key)),
                ]),
            ]))
        children.append(ui.Stack(direction="v", gap=2, children=rows))

    children.append(ui.Section(title="Teach Webbee something", children=[
        ui.Form(
            action="add_note",
            submit_label="Remember this",
            defaults={"repo": repo_key},
            children=[
                ui.TextArea(param_name="note", rows=3,
                            label=f"Fact about this repo (max {NOTE_CHARS} chars)",
                            placeholder="e.g. deploys go through deploy.sh, never edit current/"),
            ],
        ),
    ]))

    return ui.Card(title=f"Durable notes ({len(entries)})",
                   content=ui.Stack(direction="v", gap=2, children=children))


@ext.panel("memory", slot="center", title="Repo memory", icon="BrainCircuit",
           refresh="manual", center_overlay=True)
async def memory_panel(ctx, **kwargs):
    """One repository in full: its code index and its durable notes."""
    uid = _user_id(ctx)
    if not uid:
        return _err("Could not identify you — reopen the panel.")
    want = str(kwargs.get("repo") or "")

    try:
        indexes = await load_indexes(uid)
        memories = await load_memories(uid)
    except Exception as e:
        log.error("memory panel load error: %s", e)
        return _err("Could not load this repo's memory — try again shortly.")

    idx = pick(indexes, want)
    mem = pick(memories, want)
    if idx is None and mem is None:
        return _empty(
            "Nothing stored for this repo",
            "Open it in the Webbee terminal agent — the index and notes appear here.")

    repo_key = (idx or mem).get("_repo_key", "")
    root = (idx or {}).get("repo_root") or ""
    entries = [e for e in ((mem or {}).get("entries") or []) if isinstance(e, dict)]

    children = [
        ui.Header(text=repo_name(root, repo_key),
                  subtitle=root or f"repo key {repo_key}"),
    ]
    if idx is not None:
        children.append(_index_card(idx))
    else:
        children.append(ui.Alert(type="warning", message=(
            "No code index for this repo — only notes. That happens when the notes "
            "were written under an older repo identity (see 'How is this stored?').")))
    children.append(_notes_card(repo_key, entries))
    return ui.Stack(direction="v", gap=2, children=children)


@ext.panel("storage", slot="center", title="How memory is stored", icon="Database",
           refresh="manual", center_overlay=True)
async def storage_panel(ctx, **kwargs):
    """Plain explanation of every store — with this user's live numbers."""
    uid = _user_id(ctx)
    if not uid:
        return _err("Could not identify you — reopen the panel.")
    try:
        indexes = await load_indexes(uid)
        memories = await load_memories(uid)
    except Exception as e:
        log.error("storage panel load error: %s", e)
        return _err("Could not read your storage summary — try again shortly.")

    index_keys = {d.get("_repo_key", "") for d in indexes}
    note_keys = {m.get("_repo_key", "") for m in memories}
    total_notes = sum(len([e for e in (m.get("entries") or []) if isinstance(e, dict)])
                      for m in memories)
    orphans = sorted(note_keys - index_keys)

    stores = [
        ui.Card(title="1. Code index — the structural map",
                content=ui.Stack(direction="v", gap=1, children=[
                    ui.KeyValue(items=[
                        {"key": "Stored at", "value": f"{INDEX_PREFIX}{{your id}}:{{repo key}}"},
                        {"key": "Written by", "value": "the terminal coding agent, while indexing"},
                        {"key": "Updates", "value": "on every indexing pass — fully rebuilt, never patched"},
                        {"key": "Holds", "value": "file/language counts, symbol counts, key symbols "
                                                  "with file:line, semantic-chunk count, the commit"},
                        {"key": "Your repos here", "value": str(len(index_keys))},
                    ]),
                    ui.Text(content="Read-only on purpose: it is derived from your source tree, "
                                    "so a hand edit would vanish on the next pass."),
                ])),
        ui.Card(title="2. Durable notes — what Webbee learned",
                content=ui.Stack(direction="v", gap=1, children=[
                    ui.KeyValue(items=[
                        {"key": "Stored at", "value": f"{MEMORY_PREFIX}{{your id}}:{{repo key}}"},
                        {"key": "Written by", "value": "the distiller, at the tail of a coding turn"},
                        {"key": "Updates", "value": "same fact re-confirmed = refreshed in place, "
                                                    "moved to newest"},
                        {"key": "Kept for", "value": f"{_RETENTION_DAYS} days, renewed on every write"},
                        {"key": "Caps", "value": f"{MAX_ENTRIES} newest notes per repo, "
                                                 f"{NOTE_CHARS} chars each"},
                        {"key": "Your notes", "value": f"{total_notes} across {len(note_keys)} repo(s)"},
                    ]),
                    ui.Text(content="Editable by you. Secrets are stripped and prompt-fence "
                                    "characters defused before anything is saved, because notes "
                                    "are fed back to the coding agent on later turns."),
                ])),
        ui.Card(title="3. Semantic chunks — meaning search",
                content=ui.Stack(direction="v", gap=1, children=[
                    ui.KeyValue(items=[
                        {"key": "Stored", "value": "inside the code index, as vectors"},
                        {"key": "Updates", "value": "together with the index"},
                        {"key": "Used for", "value": "finding code by meaning, not just by name"},
                        {"key": "Your chunks",
                         "value": str(sum(d.get("embedded_chunks") or 0 for d in indexes))},
                    ]),
                ])),
    ]

    children = [
        ui.Header(text="Where your repo memory lives",
                  subtitle="Every store, who writes it, and when it changes"),
        ui.Stats(children=[
            ui.Stat(label="Indexed repos", value=str(len(index_keys))),
            ui.Stat(label="Repos with notes", value=str(len(note_keys))),
            ui.Stat(label="Total notes", value=str(total_notes)),
            ui.Stat(label="Retention", value=f"{_RETENTION_DAYS}d"),
        ]),
    ]
    children.extend(stores)

    children.append(ui.Card(title="Repo identity — why memory can look 'lost'",
                            content=ui.Stack(direction="v", gap=1, children=[
        ui.Text(content=(
            "Both stores are keyed by a repo key derived from the repository's "
            "git remote. A repo without a remote falls back to a hash of its path, "
            "so the same code in a different folder or worktree gets a different "
            "key — and its earlier notes stay under the old one.")),
        (ui.Alert(type="warning", message=(
            f"{len(orphans)} repo(s) have notes but no code index: "
            f"{', '.join(k[:12] for k in orphans[:8])}. Their notes are intact, "
            "just filed under an identity that is not indexed right now."))
         if orphans else
         ui.Alert(type="success", message="Every repo with notes also has a live code index.")),
    ])))

    return ui.Stack(direction="v", gap=2, children=children)


__all__ = ["repos_panel", "memory_panel", "storage_panel"]
