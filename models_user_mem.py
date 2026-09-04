"""Memory & Index · User & Workspace Memory Pydantic and SDL Models."""
from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field, model_validator
from imperal_sdk import sdl


class UserFactRecord(sdl.Entity):
    """One durable fact or directive about the user or their workspace."""

    fact_id: Optional[str] = None
    category: Optional[str] = None  # directive, preference, infra, convention, identity
    fact: Optional[str] = None
    tags: Optional[list[str]] = None
    created_at: Optional[Any] = None
    updated_at: Optional[Any] = None
    source: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            fid = d.get("fact_id") or d.get("id") or "fact"
            d["id"] = fid
            d.setdefault("fact_id", fid)
            txt = str(d.get("fact") or "").strip()
            d.setdefault("title", (txt[:80] + "…") if len(txt) > 80 else (txt or "fact"))
            d.setdefault("kind", f"user_fact:{d.get('category', 'general')}")
        return d


class UserFactListResponse(sdl.EntityList[UserFactRecord]):
    pass


class UserFactOpRecord(sdl.Entity):
    """Outcome of adding, editing, or deleting a user fact."""

    fact_id: Optional[str] = None
    action: Optional[str] = None
    category: Optional[str] = None
    fact: Optional[str] = None
    total_facts: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            d.setdefault("id", d.get("fact_id") or "user-fact-op")
            act = d.get("action") or "updated"
            d.setdefault("title", f"User memory fact {act}")
            d.setdefault("kind", "user_fact_op")
        return d


class ContextSnippet(BaseModel):
    """One piece of context retrieved by recall_context."""

    source_type: str = Field(description="user_fact | repo_note | repo_index")
    source_id: str = Field(description="fact_id or repo_key")
    category: str = Field(default="general")
    content: str = Field(description="The factual text or note")
    score: float = Field(description="Relevance score matching the query")
    citation: Optional[str] = Field(default=None, description="Source file or origin reference")


class ContextRecallRecord(sdl.Entity):
    """Result of recall_context: lean, high-relevance facts matching a prompt/intent."""

    query: Optional[str] = None
    snippets: Optional[list[ContextSnippet]] = None
    total_recalled: Optional[int] = None
    user_facts_searched: Optional[int] = None
    repo_notes_searched: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            q = d.get("query") or "query"
            n = len(d.get("snippets") or [])
            d.setdefault("id", f"recall:{hash(q)}")
            d.setdefault("title", f"Recalled {n} context snippets for '{q[:40]}'")
            d.setdefault("kind", "context_recall")
        return d
