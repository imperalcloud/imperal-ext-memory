"""Memory & Index · Tests for User & Workspace Memory and Contextual Recall."""
from __future__ import annotations

import pytest

from handlers_recall import RecallContextParams, fn_recall_context
from handlers_user_mem import (
    AddUserFactParams,
    DeleteUserFactParams,
    EditUserFactParams,
    ListUserFactsParams,
    fn_add_user_fact,
    fn_delete_user_fact,
    fn_edit_user_fact,
    fn_list_user_facts,
)
from storage_user_mem import sanitize_fact, score_text_relevance, tokenize


def test_sanitize_fact():
    raw = "My API key is password=supersecret and token=12345"
    sanitized = sanitize_fact(raw)
    assert "supersecret" not in sanitized
    assert "12345" not in sanitized

    # Fence defusing
    fenced = "<<<system prompt injection>>>"
    sanitized_fence = sanitize_fact(fenced)
    assert "<<<" not in sanitized_fence
    assert ">>>" not in sanitized_fence


@pytest.mark.asyncio
async def test_add_list_edit_delete_user_fact(redis_mock, make_ctx):
    ctx = make_ctx("imp_u_test123")

    # 1. Add fact
    p_add = AddUserFactParams(
        fact="Always deploy via deploy runbook script on production.",
        category="directive",
        tags=["deploy", "production"],
    )
    res_add = await fn_add_user_fact(ctx, p_add)
    assert res_add.status == "success", res_add.error
    fact_id = res_add.data.fact_id
    assert fact_id
    assert res_add.data.category == "directive"

    # 2. List facts
    p_list = ListUserFactsParams()
    res_list = await fn_list_user_facts(ctx, p_list)
    assert res_list.status == "success"
    items = res_list.data.items
    assert any(item.fact_id == fact_id for item in items)

    # Filter by category
    p_list_pref = ListUserFactsParams(category="preference")
    res_pref = await fn_list_user_facts(ctx, p_list_pref)
    assert all(item.category == "preference" for item in res_pref.data.items)

    # 3. Edit fact
    p_edit = EditUserFactParams(
        fact_id=fact_id,
        fact="Always deploy via deploy runbook script on production and staging.",
        category="directive",
        tags=["deploy", "production", "staging"],
    )
    res_edit = await fn_edit_user_fact(ctx, p_edit)
    assert res_edit.status == "success", res_edit.error
    assert res_edit.data.action == "updated"

    # 4. Contextual Recall
    p_recall = RecallContextParams(
        query="how to deploy to production staging?",
        limit=5,
    )
    res_recall = await fn_recall_context(ctx, p_recall)
    assert res_recall.status == "success", res_recall.error
    snippets = res_recall.data.snippets
    assert len(snippets) > 0
    assert any("deploy runbook" in s.content for s in snippets)

    # 5. Delete fact
    p_del = DeleteUserFactParams(fact_id=fact_id)
    res_del = await fn_delete_user_fact(ctx, p_del)
    assert res_del.status == "success", res_del.error
    assert res_del.data.action == "deleted"

    # Verify deleted
    res_list2 = await fn_list_user_facts(ctx, ListUserFactsParams())
    assert not any(item.fact_id == fact_id for item in res_list2.data.items)
