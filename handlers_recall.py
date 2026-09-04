"""Memory & Index · Contextual Recall tool handler.

Implements `recall_context`: semantic/keyword query across both User Facts
and Repository Notes/Index to return the most relevant snippets for a prompt.
"""
from __future__ import annotations

import logging
from pydantic import BaseModel, Field

import app
from app import (
    ActionResult,
    _user_id,
    chat,
    load_indexes,
    load_memories,
    safe_err,
)
from models_user_mem import ContextRecallRecord, ContextSnippet
from storage_user_mem import load_user_memory, score_text_relevance, tokenize

log = logging.getLogger("memory-index.recall")


class RecallContextParams(BaseModel):
    query: str = Field(
        description="The topic, question, or user intent to find relevant context for.",
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Max snippets to return across user and repo memory (default 5).",
    )
    include_user_facts: bool = Field(
        default=True,
        description="Include durable user facts and directives in search.",
    )
    include_repo_memory: bool = Field(
        default=True,
        description="Include repository notes and code index in search.",
    )


@chat.function(
    "recall_context",
    action_type="read",
    data_model=ContextRecallRecord,
    description="Contextually retrieve relevant user directives and repo notes matching a query, keeping LLM prompts lean and relevant.",
)
async def fn_recall_context(ctx, params: RecallContextParams) -> ActionResult:
    """Contextually retrieve relevant user directives and repo notes matching a query."""
    uid = _user_id(ctx)
    if not uid:
        return ActionResult.error("Could not identify the calling user.")

    query = (params.query or "").strip()
    if not query:
        return ActionResult.error("Search query cannot be empty.")

    query_tokens = tokenize(query)
    if not query_tokens:
        query_tokens = [w.lower() for w in query.split() if w.strip()]

    scored_snippets: list[dict] = []
    user_facts_searched = 0
    repo_notes_searched = 0

    # 1. Search User Memory facts
    if params.include_user_facts:
        try:
            r = await app.get_redis()
            try:
                mem = await load_user_memory(r, uid)
                facts = mem.get("facts", [])
                user_facts_searched = len(facts)
                for f in facts:
                    text = f.get("fact", "")
                    tags = f.get("tags", [])
                    score = score_text_relevance(query_tokens, text, tags)
                    if score > 0.0:
                        scored_snippets.append({
                            "source_type": "user_fact",
                            "source_id": f.get("fact_id", "fact"),
                            "category": f.get("category", "preference"),
                            "content": text,
                            "score": score,
                            "citation": f"category:{f.get('category', 'preference')}",
                        })
            finally:
                await r.aclose()
        except Exception as e:
            log.warning("User memory recall failed (fail-soft): %s", safe_err(e))

    # 2. Search Repository notes and index
    if params.include_repo_memory:
        try:
            mems = await load_memories(uid)
            indexes = await load_indexes(uid)
            index_by_repo = {idx.get("_repo_key"): idx for idx in indexes}

            for m in mems:
                repo_key = m.get("_repo_key", "")
                entries = m.get("entries", [])
                repo_notes_searched += len(entries)
                repo_idx = index_by_repo.get(repo_key) or {}
                repo_root = repo_idx.get("repo_root", "")

                for e in entries:
                    if not isinstance(e, dict):
                        continue
                    note_text = e.get("note", "")
                    cites = e.get("citations") or []
                    score = score_text_relevance(query_tokens, note_text, cites)
                    if score > 0.0:
                        scored_snippets.append({
                            "source_type": "repo_note",
                            "source_id": repo_key,
                            "category": "repo_knowledge",
                            "content": note_text,
                            "score": score,
                            "citation": ", ".join(cites) if cites else (repo_root or repo_key),
                        })
        except Exception as e:
            log.warning("Repo memory recall failed (fail-soft): %s", safe_err(e))

    # Sort descending by score, take top limit
    scored_snippets.sort(key=lambda x: x["score"], reverse=True)
    top_snippets = scored_snippets[:params.limit]

    snippet_records = [ContextSnippet.model_validate(s) for s in top_snippets]

    return ActionResult.success(
        ContextRecallRecord.model_validate({
            "query": query,
            "snippets": snippet_records,
            "total_recalled": len(snippet_records),
            "user_facts_searched": user_facts_searched,
            "repo_notes_searched": repo_notes_searched,
        }),
        summary=f"Recalled {len(snippet_records)} relevant context snippet(s).",
    )
