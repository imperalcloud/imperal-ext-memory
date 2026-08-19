"""Memory & Index · Center panel — one repo in full.

Split out of ``panels.py`` (the deploy validator warns above 300 lines).
Panels register via the ``@ext.panel`` decorator at import time, so
``panels.py`` imports every part — importing it registers all three panels
exactly as before.
"""
from __future__ import annotations

import logging

from imperal_sdk import ui

from app import _user_id, ext, load_indexes, load_memories, pick, repo_name
from panels_cards import _index_card, _notes_card
from panels_common import _empty, _err

log = logging.getLogger("memory-index")


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
    label = repo_name(root, repo_key)

    # Confirm step: the button re-renders THIS panel with confirm=1, which is
    # what puts the modal on screen. ui.Dialog has no on_cancel parameter, so
    # an explicit way back is required — otherwise the only exit from the
    # modal is the destructive action itself.
    if str(kwargs.get("confirm") or "") in ("1", "true", "yes"):
        note_line = (f"{len(entries)} durable note{'' if len(entries) == 1 else 's'}"
                     if entries else "no durable notes")
        index_line = (f"the code index ({idx.get('file_count') or 0} files)"
                      if idx is not None else "no code index")
        return ui.Stack(direction="v", gap=2, children=[
            ui.Dialog(
                title=f"Erase what Webbee remembers about {label}?",
                destructive=True,
                confirm_label="Erase permanently",
                cancel_label="Keep it",
                on_confirm=ui.Call("delete_repo", repo=repo_key),
                content=ui.Stack(direction="v", gap=2, children=[
                    ui.Text(f"This erases {index_line} and {note_line} — both "
                            f"storage keys for this repository. Afterwards the "
                            f"keyspace is re-scanned to confirm nothing is left."),
                    ui.Alert(type="warning", message=(
                        "The notes cannot be recovered — they are judgement "
                        "distilled over time, not something re-derivable from "
                        "your files. The code index DOES come back on its own "
                        "the next time you open this repo in the terminal "
                        "agent.")),
                    ui.Text(f"Repo key: {repo_key}"),
                ]),
            ),
            ui.Button(label="← Keep it", variant="ghost", size="sm",
                      on_click=ui.Call("__panel__memory", repo=repo_key)),
        ])

    children = [
        ui.Header(text=label,
                  subtitle=root or f"repo key {repo_key}"),
    ]
    if idx is not None:
        children.append(_index_card(idx))
    else:
        children.append(ui.Alert(type="warning", message=(
            "No code index for this repo — only notes. That happens when the notes "
            "were written under an older repo identity (see 'How is this stored?').")))
    children.append(_notes_card(repo_key, entries))
    children.append(ui.Card(
        title="Danger zone",
        content=ui.Stack(direction="v", gap=1, children=[
            ui.Text("Erase this repository from Webbee's memory — the code index "
                    "and every durable note, with nothing left in storage."),
            ui.Button(label="Erase this repo's memory", variant="danger",
                      icon="Trash2",
                      on_click=ui.Call("__panel__memory", repo=repo_key,
                                       confirm="1")),
        ])))
    return ui.Stack(direction="v", gap=2, children=children)
