"""Memory & Index · Center panel — the ONE center surface.

Exactly one panel may own the center slot (two competing ``slot="center"``
panels silently blank whichever loses it), so every view lives here and is
selected by view state:

    (nothing)              → overview: every repo, as openable cards
    repo=<key>             → that repo in full: graph, charts, index, notes
    section=storage        → the storage explainer
    repo=… & confirm=1     → erase-repo confirmation, layered ON TOP
    repo=… & edit=N        → editing window for note N, layered ON TOP
    repo=… & forget=N      → forget-note confirmation, layered ON TOP

MODALS ARE OVERLAYS, NOT REPLACEMENTS. The previous version returned the modal
INSTEAD of the view, so opening Edit blanked the whole section behind it and
felt like a full reload. ``ui.Modal`` layers over the current panel, so the
repo view is built once and the window is appended on top of it — the content
underneath stays exactly where it was, and only a save changes it.

EVERY VIEW HAS A ← BACK. Each one goes exactly one step: a modal back to its
repo, a repo back to the overview, the explainer back to wherever it was
opened from. The overview is the root, which is also why it exists: without it
"no repo" fell back to the first repo, so back had nowhere honest to land.
"""
from __future__ import annotations

import logging

from imperal_sdk import ui

from app import _user_id, ext, load_indexes, load_memories, pick, repo_name
from panels_cards import _index_card, _notes_card
from panels_common import _empty, _err, _nav
from panels_modals import (
    edit_note_modal,
    erase_repo_modal,
    forget_note_modal,
    token_matches,
)
from panels_overview import overview_body
from panels_storage import storage_body
from panels_viz import graph_focus_path, index_charts, index_graph

log = logging.getLogger("memory-index")


def _pos(value) -> int:
    """Panel params arrive as strings; a non-number means 'not set', not a crash."""
    try:
        return int(str(value or "0").strip())
    except (TypeError, ValueError):
        return 0


def _truthy(value) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _back(label: str, action) -> ui.UINode:
    """The one back control, so every view's ← looks and behaves the same."""
    return ui.Button(label=f"← {label}", variant="ghost", size="sm",
                     icon="ArrowLeft", on_click=action)


@ext.panel("memory", slot="center", title="Repo memory", icon="BrainCircuit",
           refresh="manual", center_overlay=True)
async def memory_panel(ctx, **kwargs):
    """Repo memory: overview, one repo in full, the explainer, and its modals."""
    uid = _user_id(ctx)
    if not uid:
        return _err("Could not identify you — reopen the panel.")

    want = str(kwargs.get("repo") or "").strip()
    section = str(kwargs.get("section") or "").strip().lower()

    # ── The explainer ───────────────────────────────────────────────────────
    if section == "storage":
        # storage_body renders its own ← when it knows the repo it came from;
        # opened from the overview there is no repo, so the ← goes there.
        body = await storage_body(uid, back_repo=want)
        if want:
            return body
        return ui.Stack(direction="v", gap=2, children=[
            _back("Back to all repos", _nav()), body])

    # ── The overview (root of the back chain) ───────────────────────────────
    if not want:
        try:
            return await overview_body(uid)
        except Exception as e:
            log.error("overview load error: %s", e)
            return _err("Could not load your repo memory — try again shortly.")

    try:
        indexes = await load_indexes(uid)
        memories = await load_memories(uid)
    except Exception as e:
        log.error("memory panel load error: %s", e)
        return _err("Could not load this repo's memory — try again shortly.")

    idx = pick(indexes, want)
    mem = pick(memories, want)
    if idx is None and mem is None:
        # Also the state right after a successful erase: the repo is genuinely
        # gone, so this is the honest view rather than a stale modal.
        return ui.Stack(direction="v", gap=2, children=[
            _back("Back to all repos", _nav()),
            _empty("Nothing stored for this repo",
                   "Open it in the Webbee terminal agent — the index and notes "
                   "appear here."),
        ])

    repo_key = (idx or mem).get("_repo_key", "")
    root = (idx or {}).get("repo_root") or ""
    entries = [e for e in ((mem or {}).get("entries") or []) if isinstance(e, dict)]
    label = repo_name(root, repo_key)

    # ── The repo view, built ONCE ───────────────────────────────────────────
    children: list = [
        _back("Back to all repos", _nav()),
        ui.Header(text=label, subtitle=root or f"repo key {repo_key}"),
    ]

    if idx is not None:
        # Visual first, tables after: the graph and charts answer "what IS
        # this repo" at a glance, which key/value rows only answer line by
        # line. Both return None on a thin index instead of drawing nothing.
        focus = graph_focus_path(idx, kwargs.get("node_id"))
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

    children.append(_notes_card(repo_key, entries))
    children.append(ui.Card(
        title="Danger zone",
        content=ui.Stack(direction="v", gap=1, children=[
            ui.Text(content="Erase this repository from Webbee's memory — the code "
                            "index and every durable note, with nothing left in "
                            "storage."),
            ui.Button(label="Erase this repo's memory", variant="danger",
                      icon="Trash2",
                      on_click=_nav(repo=repo_key, confirm="1")),
        ])))
    children.append(ui.Button(label="How is this stored?", variant="ghost",
                              size="sm", icon="Database",
                              on_click=_nav(repo=repo_key, section="storage")))

    # ── Windows, layered ON TOP of that view ────────────────────────────────
    # Each is bound to the note it was opened for via `token`, so a state param
    # that outlives its subject (note saved, note deleted, list shifted) simply
    # stops matching and the window does not come back.
    token = str(kwargs.get("token") or "")
    edit_pos = _pos(kwargs.get("edit"))
    forget_pos = _pos(kwargs.get("forget"))

    if _truthy(kwargs.get("confirm")):
        children.append(erase_repo_modal(repo_key, label, entries, idx))
    elif 1 <= edit_pos <= len(entries) and token_matches(entries, edit_pos, token):
        children.append(edit_note_modal(repo_key, edit_pos, entries))
    elif 1 <= forget_pos <= len(entries) and token_matches(entries, forget_pos, token):
        children.append(forget_note_modal(repo_key, forget_pos, entries))

    return ui.Stack(direction="v", gap=2, children=children)


__all__ = ["memory_panel"]
