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
