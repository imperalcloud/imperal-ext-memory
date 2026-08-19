"""Memory & Index · Shared panel helpers.

Split out of ``panels.py`` (the deploy validator warns above 300 lines).
Panels register via the ``@ext.panel`` decorator at import time, so
``panels.py`` imports every part — importing it registers all three panels
exactly as before.
"""
from __future__ import annotations

import logging

from imperal_sdk import ui

from app import (
    REPO_MEM_TTL,
    age,
    load_indexes,
    load_memories,
    repo_name,
)

log = logging.getLogger("memory-index")

_RETENTION_DAYS = REPO_MEM_TTL // 86400


# Every piece of view state the memory panel reads out of kwargs. Listed once,
# here, so a new state param cannot be added to the panel without also being
# cleared by every navigation action.
# ``token`` is the fingerprint of the note a modal is about (see
# panels_modals.note_token): it is what stops a stale ``edit=2``/``forget=2``
# from re-opening a modal over a note that has since been saved or deleted.
# "edit" is deliberately ABSENT: editing a note is no longer a view state at
# all. It is an inline collapsible editor the browser opens by itself, so it
# needs no param, no request and no re-render. Only the two destructive
# confirmations still travel as state.
_VIEW_STATE = ("repo", "section", "forget", "confirm", "node_id", "token")


def _nav(_omit: tuple = (), **state):
    """A SELF-DESCRIBING navigation into the memory panel.

    Every view-state param is sent on every click — the ones not named by the
    caller are sent as empty strings rather than omitted. That is the whole
    point: params from a click are merged onto the panel's current state, so an
    omitted param KEEPS its old value. That is how "How is this stored?" broke
    repo clicks — it set section=storage, and a later click carrying only
    repo=... left section=storage in place, so the explainer stayed on screen
    and the repo never opened.

    Sending the full set makes each click describe the whole view instead of a
    delta, which fixes the bug whether or not the host merges — no guessing
    about host behaviour required.

    ``_omit`` drops a key from the payload entirely, for the one case where
    something else owns it: ui.Graph injects the clicked node's id as
    ``node_id``, so that key must not be pinned to "" by the action itself.
    """
    unknown = set(state) - set(_VIEW_STATE)
    if unknown:  # a typo'd param would silently never reach the panel
        raise ValueError(f"unknown view-state param(s): {sorted(unknown)}")
    params = {k: str(state.get(k) or "") for k in _VIEW_STATE if k not in _omit}
    return ui.Call("__panel__memory", **params)


def _back(label: str, action) -> ui.UINode:
    """The one back control, so every view's ← looks and behaves the same.

    Lives here rather than in panels_memory because three different views need
    it now — the repo view, the storage explainer and the clicked-node card.
    """
    return ui.Button(label=f"← {label}", variant="ghost", size="sm",
                     icon="ArrowLeft", on_click=action)


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
