"""Tests for Autonomous Proof-of-Done and Smart Recall Filtering."""
import pytest
from proof_of_done import detect_lifecycle_scope, evaluate_task_resolution
from models_user_mem import UserFactRecord
from handlers_recall import MIN_RELEVANCE_FLOOR


def test_detect_lifecycle_scope_global_invariant():
    # Standing invariant rules
    lc, scope = detect_lifecycle_scope("Все по канонам делай, ничего не ломай!")
    assert lc == "active"
    assert scope == "global"

    lc2, scope2 = detect_lifecycle_scope("Наша панель и ВСЕ что мы трогаем - это ТОЛЬКО imperal и imperal-panel")
    assert lc2 == "active"
    assert scope2 == "global"


def test_detect_lifecycle_scope_task_scoped():
    # Ephemeral blocker
    lc, scope = detect_lifecycle_scope("Агент ОБЯЗАН первым же сообщением выдать честный блокер:")
    assert lc == "active"
    assert scope == "task"

    lc2, scope2 = detect_lifecycle_scope("Исправить фиксацию сообщений в imperal:thread_archive:webbee-terminal:*, чтобы поле session никогда не оставалось пустым.")
    assert lc2 == "active"
    assert scope2 == "task"


def test_evaluate_task_resolution_autonomous():
    # Test directive that was resolved
    fact = {
        "fact_id": "test-blocker-1",
        "fact": "Исправить фиксацию сообщений в imperal:thread_archive:webbee-terminal:*, чтобы поле session никогда не оставалось пустым",
        "category": "directive",
        "scope": "task",
        "lifecycle": "active"
    }

    resolved, proof = evaluate_task_resolution(fact)
    assert resolved is True
    assert proof is not None
    assert proof.get("status") == "resolved"
    assert "artifact" in proof


def test_user_fact_model_lifecycle_fields():
    rec = UserFactRecord(
        fact_id="fact-123",
        fact="Test standing directive",
        category="directive",
        lifecycle="resolved",
        scope="task",
        resolution_proof={"tested": True}
    )
    assert rec.lifecycle == "resolved"
    assert rec.scope == "task"
    assert rec.resolution_proof == {"tested": True}
    assert "user_fact:directive:resolved" in rec.kind

import pytest
from unittest.mock import AsyncMock, MagicMock
from handlers_recall import fn_recall_context, RecallContextParams
from models_user_mem import ContextRecallRecord

@pytest.mark.asyncio
async def test_fn_recall_context_smart_gating(redis_mock, make_ctx):
    import json
    ctx = make_ctx("imp_u_pod_user")
    uid = ctx.user.imperal_id

    # Seed facts directly into fake redis store under USER_MEMORY_PREFIX
    key = f"imperal:user_memory:{uid}"
    redis_mock.store[key] = json.dumps({
        "user_id": uid,
        "facts": [
            {
                "fact_id": "fact-active-inv",
                "fact": "Все по канонам делай, ничего не ломай!",
                "category": "directive",
                "lifecycle": "active",
                "scope": "global",
                "tags": ["canon", "rules"]
            },
            {
                "fact_id": "fact-dead-blocker",
                "fact": "Агент ОБЯЗАН первым же сообщением выдать честный блокер",
                "category": "directive",
                "lifecycle": "resolved",
                "scope": "task",
                "tags": ["blocker"]
            },
            {
                "fact_id": "fact-irrelevant-flight",
                "fact": "Да, посмотри пожалуйста через Google Flights билеты в Рим",
                "category": "preference",
                "lifecycle": "active",
                "scope": "global",
                "tags": ["travel", "flights"]
            }
        ]
    })

    params = RecallContextParams(
        query="как делать разработку и следовать правилам канона?",
        include_user_facts=True,
        include_repo_memory=False,
        include_resolved=False
    )

    res = await fn_recall_context(ctx, params)
    assert res.status == "success"
    data = res.data
    assert isinstance(data, ContextRecallRecord)

    # Active directive must be present
    fact_ids = [snip.source_id for snip in data.snippets]
    assert "fact-active-inv" in fact_ids
    # Resolved blocker must NOT be present
    assert "fact-dead-blocker" not in fact_ids
    # Low-relevance noise (flights) must be pruned by MIN_RELEVANCE_FLOOR
    assert "fact-irrelevant-flight" not in fact_ids
