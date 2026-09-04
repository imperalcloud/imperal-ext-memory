"""Memory & Index · User & Workspace Memory tool handlers.

Tools:
- list_user_facts: list all durable user preferences, directives, infra facts
- add_user_fact: remember a durable fact about user or workspace
- edit_user_fact: modify an existing user fact
- delete_user_fact: remove a fact by ID
"""
from __future__ import annotations

import time
import uuid

from pydantic import BaseModel, Field

import app
from app import ActionResult, _user_id, chat, safe_err
from models_user_mem import UserFactListResponse, UserFactOpRecord, UserFactRecord
from storage_user_mem import (
    MAX_FACT_CHARS,
    MAX_USER_FACTS,
    load_user_memory,
    sanitize_fact,
    save_user_memory,
)


class ListUserFactsParams(BaseModel):
    category: str = Field(
        default="",
        description="Optional filter by category: directive, preference, infra, convention, identity. Empty = all.",
    )


class AddUserFactParams(BaseModel):
    fact: str = Field(description=f"Durable fact or preference to remember (max {MAX_FACT_CHARS} chars)")
    category: str = Field(
        default="preference",
        description="Category: directive, preference, infra, convention, identity",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Optional keywords/tags for contextual search, e.g. ['docker', 'deploy']",
    )


class EditUserFactParams(BaseModel):
    fact_id: str = Field(description="Unique ID of the fact to update")
    fact: str = Field(description=f"Updated fact text (max {MAX_FACT_CHARS} chars)")
    category: str = Field(
        default="",
        description="Updated category (empty keeps existing)",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Updated list of tags (empty keeps existing)",
    )


class DeleteUserFactParams(BaseModel):
    fact_id: str = Field(description="Unique ID of the fact to delete")


@chat.function(
    "list_user_facts",
    action_type="read",
    data_model=UserFactListResponse,
    description="List durable user directives, workspace preferences, and infrastructure facts.",
)
async def fn_list_user_facts(ctx, params: ListUserFactsParams) -> ActionResult:
    """List durable user facts, directives, and workspace preferences."""
    uid = _user_id(ctx)
    if not uid:
        return ActionResult.error("Could not identify the calling user.")

    r = await app.get_redis()
    try:
        mem = await load_user_memory(r, uid)
    finally:
        await r.aclose()

    facts = mem.get("facts", [])
    cat = (params.category or "").strip().lower()
    if cat:
        facts = [f for f in facts if str(f.get("category", "")).lower() == cat]

    records = [UserFactRecord.model_validate(f) for f in facts]
    return ActionResult.success(
        UserFactListResponse(items=records),
        summary=f"Found {len(records)} user memory fact(s).",
    )


@chat.function(
    "add_user_fact",
    action_type="write",
    data_model=UserFactOpRecord,
    effects=["create:user_fact"],
    event="user_fact_added",
    description="Teach Webbee a durable fact or directive about yourself or your workspace (remembered across sessions & surfaces).",
)
async def fn_add_user_fact(ctx, params: AddUserFactParams) -> ActionResult:
    """Teach Webbee a durable fact or directive about yourself or your workspace."""
    uid = _user_id(ctx)
    if not uid:
        return ActionResult.error("Could not identify the calling user.")

    clean_text = sanitize_fact(params.fact)
    if not clean_text:
        return ActionResult.error("Fact text is empty after sanitization.")

    r = await app.get_redis()
    try:
        mem = await load_user_memory(r, uid)
        facts: list[dict] = mem.get("facts", [])
        if len(facts) >= MAX_USER_FACTS:
            facts = facts[-(MAX_USER_FACTS - 1):]

        now = int(time.time())
        fact_id = f"fact_{uuid.uuid4().hex[:10]}"
        new_entry = {
            "fact_id": fact_id,
            "category": (params.category or "preference").strip().lower(),
            "fact": clean_text,
            "tags": [t.strip().lower() for t in params.tags if t.strip()],
            "created_at": now,
            "updated_at": now,
            "source": "chat",
        }
        facts.append(new_entry)
        await save_user_memory(r, uid, facts)
    finally:
        await r.aclose()

    return ActionResult.success(
        UserFactOpRecord.model_validate({
            "fact_id": fact_id,
            "action": "added",
            "category": new_entry["category"],
            "fact": clean_text,
            "total_facts": len(facts),
        }),
        summary=f"Remembered fact under category '{new_entry['category']}'.",
    )


@chat.function(
    "edit_user_fact",
    action_type="write",
    data_model=UserFactOpRecord,
    effects=["update:user_fact"],
    event="user_fact_edited",
    description="Update an existing durable user fact or directive by ID.",
)
async def fn_edit_user_fact(ctx, params: EditUserFactParams) -> ActionResult:
    """Update an existing durable user fact or directive by ID."""
    uid = _user_id(ctx)
    if not uid:
        return ActionResult.error("Could not identify the calling user.")

    clean_text = sanitize_fact(params.fact)
    if not clean_text:
        return ActionResult.error("Fact text is empty after sanitization.")

    target_id = (params.fact_id or "").strip()
    if not target_id:
        return ActionResult.error("fact_id is required.")

    r = await app.get_redis()
    try:
        mem = await load_user_memory(r, uid)
        facts: list[dict] = mem.get("facts", [])
        matched = None
        for f in facts:
            if f.get("fact_id") == target_id:
                matched = f
                break

        if not matched:
            return ActionResult.error(f"User fact '{target_id}' not found.")

        matched["fact"] = clean_text
        if params.category:
            matched["category"] = params.category.strip().lower()
        if params.tags:
            matched["tags"] = [t.strip().lower() for t in params.tags if t.strip()]
        matched["updated_at"] = int(time.time())

        await save_user_memory(r, uid, facts)
    finally:
        await r.aclose()

    return ActionResult.success(
        UserFactOpRecord.model_validate({
            "fact_id": target_id,
            "action": "updated",
            "category": matched.get("category"),
            "fact": clean_text,
            "total_facts": len(facts),
        }),
        summary=f"Updated fact '{target_id}'.",
    )


@chat.function(
    "delete_user_fact",
    action_type="write",
    data_model=UserFactOpRecord,
    effects=["delete:user_fact"],
    event="user_fact_deleted",
    description="Delete a durable user fact by its fact_id.",
)
async def fn_delete_user_fact(ctx, params: DeleteUserFactParams) -> ActionResult:
    """Delete a durable user fact by its fact_id."""
    uid = _user_id(ctx)
    if not uid:
        return ActionResult.error("Could not identify the calling user.")

    target_id = (params.fact_id or "").strip()
    if not target_id:
        return ActionResult.error("fact_id is required.")

    r = await app.get_redis()
    try:
        mem = await load_user_memory(r, uid)
        facts: list[dict] = mem.get("facts", [])
        surviving = [f for f in facts if f.get("fact_id") != target_id]
        if len(surviving) == len(facts):
            return ActionResult.error(f"User fact '{target_id}' not found.")

        await save_user_memory(r, uid, surviving)
    finally:
        await r.aclose()

    return ActionResult.success(
        UserFactOpRecord.model_validate({
            "fact_id": target_id,
            "action": "deleted",
            "total_facts": len(surviving),
        }),
        summary=f"Deleted user memory fact '{target_id}'.",
    )
