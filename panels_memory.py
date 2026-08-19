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
from panels_common import _empty, _err, _nav
from panels_storage import storage_body
from panels_viz import index_charts, index_graph

log = logging.getLogger("memory-index")


def _pos(value) -> int:
    """Panel params arrive as strings; a non-number means 'not set', not a crash."""
    try:
        return int(str(value or "0").strip())
    except (TypeError, ValueError):
        return 0


def _focus_from_node(node_id) -> str:
    """Turn a clicked graph node id back into a file path to focus on.

    ``ui.Graph`` injects the clicked node's id as ``node_id``. Only file nodes
    are meaningful to focus (``file::<path>``); clicking a symbol or the repo
    node clears the focus rather than drilling into something that has no
    deeper level in the index.
    """
    s = str(node_id or "")
    return s[6:] if s.startswith("file::") else ""


@ext.panel("memory", slot="center", title="Repo memory", icon="BrainCircuit",
           refresh="manual", center_overlay=True)
async def memory_panel(ctx, **kwargs):
    """One repository in full: its code index and its durable notes."""
    uid = _user_id(ctx)
    if not uid:
        return _err("Could not identify you — reopen the panel.")
    want = str(kwargs.get("repo") or "")

    # The explainer renders as a SECTION of this panel, not as its own center
    # panel: a second slot="center" panel is not reliably mounted, which is why
    # the old "How is this stored?" button appeared to do nothing. Handled
    # before any repo lookup so it also works for a user with no memory yet.
    if str(kwargs.get("section") or "") == "storage":
        return await storage_body(uid, back_repo=want)

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

    # Forgetting ONE note is destructive too, so it gets the same treatment as
    # erasing a repo: a strict modal naming the exact text about to be lost.
    # Previously the button fired delete_note immediately — no way back.
    forget_pos = _pos(kwargs.get("forget"))
    if 1 <= forget_pos <= len(entries):
        doomed = str(entries[forget_pos - 1].get("note") or "")
        preview = doomed if len(doomed) <= 300 else doomed[:300] + "…"
        return ui.Stack(direction="v", gap=2, children=[
            ui.Dialog(
                title=f"Forget note #{forget_pos}?",
                destructive=True,
                confirm_label="Forget it",
                cancel_label="Keep it",
                on_confirm=ui.Call("delete_note", repo=repo_key, position=forget_pos),
                content=ui.Stack(direction="v", gap=2, children=[
                    ui.Text(content="This note will be removed from what Webbee "
                                    "knows about this repo:"),
                    ui.Card(title=f"Note #{forget_pos}", content=ui.Text(content=preview)),
                    ui.Alert(type="warning", message=(
                        "Distilled notes are judgement built up over many coding "
                        "turns — this one cannot be recovered. The other "
                        f"{len(entries) - 1} note(s) for this repo stay untouched.")),
                ]),
            ),
            ui.Button(label="Cancel", variant="ghost", size="sm",
                      on_click=_nav(repo=repo_key)),
        ])

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
                      on_click=_nav(repo=repo_key)),
        ])

    children = [
        ui.Header(text=label,
                  subtitle=root or f"repo key {repo_key}"),
    ]
    if idx is not None:
        # Visual first, tables after: the graph and the two charts answer
        # "what IS this repo" at a glance, which the raw key/value rows can
        # only answer by being read line by line. Both degrade to None when
        # the index lacks the fields, so a thin index simply shows less.
        focus = _focus_from_node(kwargs.get("node_id"))
        graph = index_graph(idx, label, focus=focus)
        if graph is not None:
            children.append(graph)
        charts = index_charts(idx)
        if charts is not None:
            children.append(charts)
        children.append(_index_card(idx))
    else:
        children.append(ui.Alert(type="warning", message=(
            "No code index for this repo — only notes. That happens when the notes "
            "were written under an older repo identity (see 'How is this stored?').")))
    children.append(_notes_card(repo_key, entries, editing=_pos(kwargs.get("edit"))))
    children.append(ui.Card(
        title="Danger zone",
        content=ui.Stack(direction="v", gap=1, children=[
            ui.Text("Erase this repository from Webbee's memory — the code index "
                    "and every durable note, with nothing left in storage."),
            ui.Button(label="Erase this repo's memory", variant="danger",
                      icon="Trash2",
                      on_click=_nav(repo=repo_key, confirm="1")),
        ])))
    return ui.Stack(direction="v", gap=2, children=children)
