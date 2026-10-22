"""Memory & Index · Left panel — repository inventory.

Split out of ``panels.py`` (the deploy validator warns above 300 lines).
Panels register via the ``@ext.panel`` decorator at import time, so
``panels.py`` imports every part — importing it registers all three panels
exactly as before.
"""
from __future__ import annotations

import logging

from imperal_sdk import ui

from app import _user_id, age, ext, load_everything, repo_name
from memory_client import memory_api
from memory_places import describe, is_orphan, place_title, places, repo_key_of
from panels_common import _empty, _err, _inventory, _nav

log = logging.getLogger("memory-index")


@ext.panel("repos", slot="left", title="Memory & Index", icon="BrainCircuit", refresh="manual")
async def repos_panel(ctx, **kwargs):
    """Inventory of every repository Webbee holds memory for."""
    uid = _user_id(ctx)
    if not uid:
        return _err("Could not identify you — reopen the panel.")
    try:
        rows = await _inventory(ctx)
    except Exception as e:
        log.error("repos panel load error: %s", e)
        return _err("Could not load your repo memory — try again shortly.")

    # The whole memory, so memory left over from a deleted repo is listed too
    # (fail-soft: an outage only drops that group, never the inventory).
    listing = await load_everything(ctx)
    everything = ui.Button(label="Everything Webbee holds", variant="primary", icon="Database",
                           on_click=_nav(section="everything"))
    leftovers = [ui.ListItem(
        id=str(p.get("place")), title=place_title(p),
        subtitle=(f"code index deleted — memory left over · {int(p.get('total') or 0):,} records: "
                  f"{describe(p.get('counts') or {}, limit=3)}"),
        on_click=_nav(repo=repo_key_of(p)))
        for p in places(listing) if is_orphan(p)]

    if not rows:
        empty = _empty(
            "No repo memory yet",
            "Open a repository in the Webbee terminal agent. The code index it "
            "builds and the notes it distils show up here automatically.")
        extra = [ui.Section(title="Memory left from deleted repos", children=[ui.List(items=leftovers)])] \
            if leftovers else []
        return ui.Stack(direction="v", gap=2, children=[empty, everything, *extra])

    try:   # the vault's code catalog: where each repo lives, how it is reached, how fresh it is
        catalog = {str(c.get("repo_key")): c for c in ((await memory_api(ctx).code_repos()) or {}).get("repos") or []
                   if isinstance(c, dict)}
    except Exception:
        catalog = {}

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
            everything,
            ui.Button(label="User & Workspace Facts", variant="secondary", icon="UserCheck",
                      on_click=_nav(section="user_memory")),
            ui.Button(label="How is this stored?", variant="secondary", icon="HelpCircle",
                      # Routed through the memory panel as a section: a second
                      # slot="center" panel is not reliably mounted, so calling
                      # __panel__storage directly did nothing at all on click.
                      on_click=_nav(section="storage")),
        ])),
    ]

    items = []
    for r in rows:
        badges = []
        c = catalog.get(r["repo_key"])
        if c is not None:
            # a synced repo: the machine and how it is reached, the graph's counts, how fresh, what is partial
            sources = ", ".join(sorted({str(s.get("kind") or "") for s in c.get("sources") or []
                                        if isinstance(s, dict) and s.get("kind")}))
            badges.append(f"{c.get('machine_label') or 'local'}" + (f" via {sources}" if sources else ""))
            badges.append(f"{c.get('files') or 0} files · {c.get('defs') or 0} defs · {c.get('links') or 0} links")
        elif r["has_index"]:
            badges.append(f"{r['file_count']} files")
        if r["has_notes"]:
            badges.append(f"{r['note_count']} notes")
        if not r["has_index"] and c is None:
            badges.append("notes only")
        when = f" · synced {age(c.get('synced_at'))}" if c is not None else (
            f" · indexed {r['indexed']}" if r["has_index"] else "")
        partial = f" · partial: {str(c.get('partial_reason'))[:80]}" if c is not None and c.get("partial_reason") else ""
        items.append(ui.ListItem(
            id=r["repo_key"],
            title=repo_name((c or {}).get("root_path") or r["repo_root"], r["repo_key"]),
            subtitle=" · ".join(badges) + when + partial,
            on_click=_nav(repo=r["repo_key"]),
        ))

    children.append(ui.Section(title="Repositories", children=[ui.List(items=items)]))
    if leftovers:
        children.append(ui.Section(title="Memory left from deleted repos",
                                   children=[ui.List(items=leftovers)]))
    return ui.Stack(direction="v", gap=2, children=children)
