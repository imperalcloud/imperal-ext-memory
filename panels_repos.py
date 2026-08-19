"""Memory & Index · Left panel — repository inventory.

Split out of ``panels.py`` (the deploy validator warns above 300 lines).
Panels register via the ``@ext.panel`` decorator at import time, so
``panels.py`` imports every part — importing it registers all three panels
exactly as before.
"""
from __future__ import annotations

import logging

from imperal_sdk import ui

from app import _user_id, ext, repo_name
from panels_common import _empty, _err, _inventory

log = logging.getLogger("memory-index")


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
                      # Routed through the memory panel as a section: a second
                      # slot="center" panel is not reliably mounted, so calling
                      # __panel__storage directly did nothing at all on click.
                      on_click=ui.Call("__panel__memory", section="storage")),
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
