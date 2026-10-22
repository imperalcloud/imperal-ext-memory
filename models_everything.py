"""Memory & Index · SDL records for the whole memory and for forgetting.

Separate from ``models.py`` (repo-index records) because these mirror a
different payload: the gateway's ``/v1/memory/all`` places and its
``/v1/memory/forget`` answer, handed through as-is.
"""
from __future__ import annotations

from typing import Optional

from pydantic import model_validator

from imperal_sdk import sdl


class MemoryOverviewRecord(sdl.Entity):
    """Every place of the user's memory (account, repos, left-over repos) with
    its per-section counts — exactly as the vault reports them."""

    places: Optional[list] = None
    place_count: Optional[int] = None
    orphan_count: Optional[int] = None
    total: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            d.setdefault("id", "memory-overview")
            d.setdefault("title", f"Everything Webbee holds — {d.get('total', 0)} records")
            d.setdefault("kind", "memory_overview")
        return d


class ForgetRecord(sdl.Entity):
    """Outcome of one forget — what the vault removed, what a fresh read of the
    whole memory still shows (``left``), and whether that makes it verified."""

    what: Optional[str] = None
    key: Optional[str] = None
    project_id: Optional[str] = None
    forgotten: Optional[dict] = None
    left: Optional[dict] = None
    stopped_sessions: Optional[list] = None
    caches_dropped: Optional[int] = None
    verified: Optional[bool] = None
    total_after: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            target = f"{d.get('what') or '?'} {d.get('key') or ''}".strip()
            d.setdefault("id", f"forget:{target}")
            state = "verified gone" if d.get("verified") else "NOT confirmed"
            d.setdefault("title", f"Forgot {target} — {state}")
            d.setdefault("kind", "memory_forget")
        return d
