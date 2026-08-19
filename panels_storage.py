"""Memory & Index · Center panel — where memory actually lives.

Split out of ``panels.py`` (the deploy validator warns above 300 lines).
Panels register via the ``@ext.panel`` decorator at import time, so
``panels.py`` imports every part — importing it registers all three panels
exactly as before.
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
    ext,
    load_indexes,
    load_memories,
)
from panels_common import _err

log = logging.getLogger("memory-index")

_RETENTION_DAYS = REPO_MEM_TTL // 86400


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
