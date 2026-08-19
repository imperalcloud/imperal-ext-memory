"""Memory & Index · Center panel — one repo in full.

Split out of ``panels.py`` (the deploy validator warns above 300 lines).
Panels register via the ``@ext.panel`` decorator at import time, so
``panels.py`` imports every part — importing it registers all three panels
exactly as before.
"""
from __future__ import annotations

import logging

from imperal_sdk import ui

from app import _user_id, ext, load_indexes, load_memories, pick
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
