"""Memory & Index · SDL records.

Field names mirror the ACTUAL payload the kernel persists into
``imperal:repo_index_map:{user_id}:{repo_key}`` and
``imperal:repo_memory:{user_id}:{repo_key}`` — federal
I-EXT-RECORD-FIELD-NAMING-SYMMETRIC. Nothing is re-shaped for display: the
handlers hand the stored map through as-is, which is what makes $REF paths
verifiable instead of aspirational.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import model_validator

from imperal_sdk import sdl


def _name(root: str, fallback: str = "") -> str:
    r = (root or "").rstrip("/")
    return r.rsplit("/", 1)[-1] if r else (fallback or "repo")


class RepoRecord(sdl.Entity):
    """One repository Webbee holds memory for, as summarised for the list."""

    repo_key: Optional[str] = None
    repo_root: Optional[str] = None
    file_count: Optional[int] = None
    languages: Optional[dict] = None
    symbol_kinds: Optional[dict] = None
    embedded_chunks: Optional[int] = None
    vectors_ready: Optional[bool] = None
    note_count: Optional[int] = None
    git_ref: Optional[str] = None
    branch: Optional[str] = None
    indexed: Optional[str] = None
    has_index: Optional[bool] = None
    has_notes: Optional[bool] = None

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            key = d.get("repo_key") or ""
            d["id"] = key or d.get("repo_root") or "repo"
            files = d.get("file_count")
            notes = d.get("note_count") or 0
            bits = []
            if files:
                bits.append(f"{files} files")
            if notes:
                bits.append(f"{notes} notes")
            tail = f" — {', '.join(bits)}" if bits else ""
            d.setdefault("title", _name(d.get("repo_root", ""), key) + tail)
            d.setdefault("kind", "repo")
        return d


class RepoListResponse(sdl.EntityList[RepoRecord]):
    pass


class RepoIndexRecord(sdl.Entity):
    """The full structural map of ONE repo, exactly as the kernel stored it."""

    repo_key: Optional[str] = None
    repo_root: Optional[str] = None
    evidence_version: Optional[int] = None
    content_digest: Optional[str] = None
    file_count: Optional[int] = None
    languages: Optional[dict] = None
    symbol_kinds: Optional[dict] = None
    top_symbols: Optional[list] = None
    test_hint_files: Optional[list] = None
    endpoint_count: Optional[int] = None
    schema_count: Optional[int] = None
    contract_evidence_limit: Optional[int] = None
    contract_evidence_complete: Optional[bool] = None
    endpoints: Optional[list] = None
    schemas: Optional[list] = None
    vectors_ready: Optional[bool] = None
    embedded_chunks: Optional[int] = None
    git_ref: Optional[str] = None
    branch: Optional[str] = None
    updated_at: Optional[Any] = None
    indexed: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            key = d.get("repo_key") or ""
            d["id"] = key or d.get("repo_root") or "repo"
            ref = (d.get("git_ref") or "")[:12]
            name = _name(d.get("repo_root", ""), key)
            d.setdefault("title", f"{name} @ {ref}" if ref else name)
            d.setdefault("kind", "repo_index")
        return d


class NoteRecord(sdl.Entity):
    """One durable note about a repo — editable by its owner."""

    note: Optional[str] = None
    citations: Optional[list] = None
    repo_key: Optional[str] = None
    distilled_at: Optional[Any] = None
    distilled_git_ref: Optional[str] = None
    edited_at: Optional[Any] = None
    source: Optional[str] = None
    position: Optional[int] = None
    written: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            txt = str(d.get("note") or "").strip()
            pos = d.get("position")
            d["id"] = d.get("id") or f"{d.get('repo_key', '')}:{pos if pos is not None else 0}"
            d.setdefault("title", (txt[:80] + "…") if len(txt) > 80 else (txt or "note"))
            d.setdefault("kind", "repo_note")
        return d


class NoteListResponse(sdl.EntityList[NoteRecord]):
    pass


class NoteOpRecord(sdl.Entity):
    """Outcome of ONE note write (add / edit / delete).

    Deliberately NOT ``NoteRecord``: a write does not return the stored entity,
    it returns what CHANGED — the resulting text plus the displaced/removed
    one and the surviving count. Typing it truthfully is what lets the narrator
    and the audit ledger describe the mutation without re-reading the store
    (federal V24).
    """

    repo_key: Optional[str] = None
    note: Optional[str] = None
    previous: Optional[str] = None
    removed: Optional[str] = None
    position: Optional[int] = None
    total: Optional[int] = None
    remaining: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            key = d.get("repo_key") or ""
            pos = d.get("position")
            d["id"] = f"{key}:{pos}" if pos is not None else (key or "note-op")
            txt = str(d.get("note") or d.get("removed") or "").strip()
            d.setdefault("title", (txt[:80] + "…") if len(txt) > 80 else (txt or "note"))
            d.setdefault("kind", "repo_note_op")
        return d


class PurgeRecord(sdl.Entity):
    """Outcome of erasing ONE repo's memory — a verified fact, not an intent.

    ``verified`` is the result of a fresh keyspace scan performed AFTER the
    delete, and ``leftover_keys`` names anything that survived it. They are
    modelled as first-class fields precisely so the answer cannot claim a
    clean wipe while something remains: if the re-scan finds a key, the
    record says so and the narrator has to report it.
    """

    repo_key: Optional[str] = None
    repo_label: Optional[str] = None
    had_index: Optional[bool] = None
    had_notes: Optional[bool] = None
    notes_removed: Optional[int] = None
    keys_deleted: Optional[int] = None
    leftover_keys: Optional[list] = None
    verified: Optional[bool] = None

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            key = d.get("repo_key") or ""
            d.setdefault("id", key or "repo-purge")
            label = d.get("repo_label") or key or "repo"
            n = int(d.get("keys_deleted") or 0)
            d.setdefault("title", f"Erased {label} — {n} key{'' if n == 1 else 's'} removed")
            d.setdefault("kind", "repo_purge")
        return d


class MemoryExplainerRecord(sdl.Entity):
    """Where each piece of repo memory lives and when it updates — live numbers."""

    stores: Optional[list] = None
    repo_count: Optional[int] = None
    indexed_repo_count: Optional[int] = None
    note_repo_count: Optional[int] = None
    total_notes: Optional[int] = None
    max_notes_per_repo: Optional[int] = None
    note_char_limit: Optional[int] = None
    retention_days: Optional[int] = None
    orphan_note_repos: Optional[list] = None

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            d.setdefault("id", "memory-explainer")
            d.setdefault("title", "How Webbee's repo memory works")
            d.setdefault("kind", "explainer")
        return d
