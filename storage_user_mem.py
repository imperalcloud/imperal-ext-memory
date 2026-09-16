"""Memory & Index · User & Workspace Memory storage layer.

Stores durable user preferences, directives, workflows, and infrastructure facts
in Redis under the key:
    imperal:user_memory:{user_id}

Provides contextual retrieval (BM25 / token-overlap & tag scoring)
to select the most relevant facts for a given prompt/query without bloating the LLM context.
"""
from __future__ import annotations

import json
import logging
import math
import re
import time
from typing import Any

import redis.asyncio as aioredis
from safety import neutralize_fence, scrub_secrets

log = logging.getLogger("memory-index.user_mem")

USER_MEMORY_PREFIX = "imperal:user_memory:"
USER_MEM_TTL = 180 * 86400  # 180 days, refreshed on write
MAX_USER_FACTS = 100
MAX_FACT_CHARS = 500


def sanitize_fact(text: str) -> str:
    """Full write pipeline for a user fact: scrub secrets -> defuse fences -> clamp."""
    if not text:
        return ""
    scrubbed = scrub_secrets(text)
    defused = neutralize_fence(scrubbed)
    return defused[:MAX_FACT_CHARS].strip()


async def load_user_memory(r: aioredis.Redis, uid: str) -> dict:
    """Load user memory with Tenant Vault as primary source and Redis fallback."""
    # VAULT-PRIMARY-READ (ICNLI Hosting Principle, 2026-09-17)
    try:
        import httpx
        from app import VAULT_BASE_URL, VAULT_TIMEOUT
        async with httpx.AsyncClient(timeout=VAULT_TIMEOUT) as client:
            resp = await client.get(f"{VAULT_BASE_URL}/v1/memory/facts", params={"user_id": uid})
            if resp.status_code == 200:
                vault_facts = resp.json().get("facts", [])
                if vault_facts:
                    return {"user_id": uid, "facts": vault_facts}
    except Exception as e:
        log.debug("load_user_memory vault read failed (fail-soft): %s", e)

    key = f"{USER_MEMORY_PREFIX}{uid}"
    try:
        if r:
            raw = await r.get(key)
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict) and isinstance(data.get("facts"), list):
                    return data
    except Exception as e:
        log.warning("Failed to load user memory for %s: %s", uid, e)
    return {"user_id": uid, "facts": []}


async def save_user_memory(r: aioredis.Redis, uid: str, facts: list[dict]) -> None:
    """Persist user facts directly to Tenant Vault as primary, updating Redis live cache."""
    if len(facts) > MAX_USER_FACTS:
        facts = facts[-MAX_USER_FACTS:]

    # VAULT-PRIMARY-WRITE (ICNLI Hosting Principle, 2026-09-17)
    try:
        import httpx
        from app import VAULT_BASE_URL, VAULT_TIMEOUT
        async with httpx.AsyncClient(timeout=VAULT_TIMEOUT) as client:
            resp = await client.post(
                f"{VAULT_BASE_URL}/v1/memory/facts",
                json={"user_id": uid, "facts": facts},
            )
            if resp.status_code != 200:
                log.debug("save_user_memory vault status: %s", resp.status_code)
    except Exception as e:
        log.warning("save_user_memory vault write failed (fail-soft): %s", e)

    key = f"{USER_MEMORY_PREFIX}{uid}"
    try:
        if r:
            payload = json.dumps({"user_id": uid, "facts": facts, "updated_at": int(time.time())})
            await r.set(key, payload, ex=USER_MEM_TTL)
    except Exception as e:
        log.warning("save_user_memory redis cache failed (fail-soft): %s", e)


_STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but",
    "by", "could", "did", "do", "does", "doing", "down", "during", "each", "few", "for", "from",
    "further", "had", "has", "have", "having", "he", "her", "here", "hers", "herself", "him",
    "himself", "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just",
    "me", "more", "most", "my", "myself", "no", "nor", "not", "now", "of", "off", "on", "once",
    "only", "or", "other", "our", "ours", "ourselves", "out", "over", "own", "same", "she",
    "should", "so", "some", "such", "than", "that", "the", "their", "theirs", "them", "themselves",
    "then", "there", "these", "they", "this", "those", "through", "to", "too", "under", "until",
    "up", "very", "was", "we", "were", "what", "when", "where", "which", "while", "who", "whom",
    "why", "with", "would", "you", "your", "yours", "yourself", "yourselves",
    # Russian common stopwords
    "и", "в", "во", "не", "что", "он", "на", "я", "с", "со", "как", "а", "то", "все", "она",
    "так", "его", "но", "да", "ты", "к", "у", "же", "вы", "за", "бы", "по", "только", "ее",
    "мне", "было", "вот", "от", "меня", "еще", "нет", "о", "из", "ему", "теперь", "когда",
    "даже", "ну", "вдруг", "ли", "если", "уже", "или", "ни", "быть", "был", "него", "до",
    "вас", "нибудь", "опять", "уж", "вам", "ведь", "там", "потом", "себя", "ничего", "ей",
    "может", "они", "тут", "где", "есть", "надо", "ней", "для", "мы", "тебя", "их", "чем",
    "была", "сам", "чтоб", "без", "будто", "чего", "раз", "тоже", "себе", "под", "будет",
    "ж", "тогда", "кто", "этот", "того", "потому", "этого", "какой", "совсем", "ним", "здесь",
    "этом", "один", "почти", "мой", "тем", "чтобы", "нее", "сейчас", "были", "куда", "зачем",
    "всех", "никогда", "можно", "при", "наконец", "два", "об", "другой", "хоть", "после",
    "над", "больше", "тот", "через", "эти", "нас", "про", "всего", "них", "какая", "много",
    "разве", "три", "эту", "моя", "впрочем", "хорошо", "свою", "этой", "перед", "иногда",
    "лучше", "чуть", "том", "нельзя", "такой", "им", "более", "всегда", "конечно", "всю", "между",
}


def tokenize(text: str) -> list[str]:
    """Extract lowercased alphanumeric tokens from text, filtering out common stopwords."""
    if not text:
        return []
    words = re.findall(r"[\w-]+", text.lower())
    return [w for w in words if len(w) >= 2 and w not in _STOPWORDS]


def score_text_relevance(query_tokens: list[str], target_text: str, tags: list[str] | None = None) -> float:
    """Compute relevance score between query tokens and target text + tags.

    Uses BM25-like token overlap + exact match boost + tag weighting.
    """
    if not query_tokens or not target_text:
        return 0.0

    target_tokens = tokenize(target_text)
    if not target_tokens:
        return 0.0

    score = 0.0
    text_lower = target_text.lower()
    tag_set = {t.lower() for t in (tags or [])}

    for qt in query_tokens:
        # Exact substring occurrence boost
        if qt in text_lower:
            score += 1.5
        # Token frequency in target text
        tf = target_tokens.count(qt)
        if tf > 0:
            # Sub-linear TF scaling: 1 + ln(tf)
            score += 1.0 + math.log(tf)
        # Direct tag match boost
        if qt in tag_set:
            score += 3.0

    # Normalise slightly by length to prevent huge texts from dominating
    length_penalty = math.log(max(10, len(target_tokens))) / math.log(10)
    return round(score / length_penalty, 3)
