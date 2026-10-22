"""Memory & Index · Center overview — the step BEFORE a single repo.

This exists so "back" has somewhere to go. Every other view in this panel is
reached FROM somewhere (a repo from the list, the explainer from a repo, a
modal from a note), and each of those now renders a ← button. A repo view had
no such target: the panel used to fall back to `pick(indexes, "")`, i.e. the
first repo, so "no repo selected" silently meant "some repo". That is now an
explicit overview, which is both an honest root for the back chain and a
faster way in than reading the sidebar list.

It is also the first place the WHOLE memory shows: a prominent way into
"Everything Webbee holds", and memory left over from repos whose code index
is gone listed in its own group with its forget — never invisible just because
it has no index or notes.
"""
from __future__ import annotations

from imperal_sdk import ui

from app import load_everything
from panels_common import _empty, _inventory, _nav
from panels_everything import leftover_cards


def _lang(row: dict) -> str:
    langs = row.get("languages") or {}
    if not langs:
        return "no languages recorded"
    top = sorted(langs.items(), key=lambda kv: kv[1], reverse=True)[:3]
    return ", ".join(f"{k} {v:,}" for k, v in top)


def _everything_button(listing) -> ui.UINode:
    total = int((listing or {}).get("total") or 0)
    return ui.Button(
        label="Everything Webbee holds about you" + (f" ({total:,} records)" if total else ""),
        variant="primary", icon="Database", on_click=_nav(section="everything"))


async def overview_body(ctx):
    """Every repo Webbee holds memory for, as openable cards — plus the way into
    the whole memory and the memory left over from deleted repos."""
    rows = await _inventory(ctx)
    listing = await load_everything(ctx)   # fail-soft: None hides nothing stored
    leftovers = leftover_cards(listing)
    if not rows and not leftovers:
        return ui.Stack(direction="v", gap=2, children=[
            _empty("No repo memory yet",
                   "Open a repository in the Webbee terminal agent — its code index "
                   "and notes appear here automatically."),
            _everything_button(listing),
        ])

    indexed = sum(1 for r in rows if r.get("has_index"))
    noted = sum(1 for r in rows if r.get("has_notes"))
    notes = sum(int(r.get("note_count") or 0) for r in rows)

    children: list = [
        ui.Header(text="Repo memory", subtitle="Pick a repository to open it in full"),
        _everything_button(listing),
        ui.Stats(children=[
            ui.Stat(label="Repos", value=str(len(rows))),
            ui.Stat(label="With code index", value=str(indexed)),
            ui.Stat(label="With notes", value=str(noted)),
            ui.Stat(label="Notes total", value=str(notes)),
        ]),
    ]

    for row in rows:
        key = str(row.get("repo_key") or "")
        root = str(row.get("repo_root") or "")
        name = root.rstrip("/").split("/")[-1] if root else (key[:12] or "unknown")
        bits = [
            f"{int(row.get('file_count') or 0):,} files",
            f"{int(row.get('note_count') or 0)} note(s)",
            f"indexed {row.get('indexed') or 'unknown'}",
        ]
        if row.get("branch"):
            bits.append(f"branch {row['branch']}")
        children.append(ui.Card(
            title=name,
            content=ui.Stack(direction="v", gap=1, children=[
                ui.Text(content=root or f"repo key {key}"),
                ui.Text(content=" · ".join(bits)),
                ui.Text(content=_lang(row)),
                ui.Button(label="Open this repo", variant="secondary",
                          icon="FolderOpen", size="sm",
                          on_click=_nav(repo=key)),
            ])))

    if leftovers:
        children.append(ui.Section(
            title=f"Memory left from deleted repos ({len(leftovers)})",
            children=leftovers))

    children.append(ui.Button(label="How is this stored?", variant="ghost",
                              size="sm", icon="Database",
                              on_click=_nav(section="storage")))
    return ui.Stack(direction="v", gap=2, children=children)


__all__ = ["overview_body"]
