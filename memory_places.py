"""Memory & Index · The whole memory, as the vault reports it.

``GET /v1/memory/all`` answers with one PLACE per scope of the user's memory:
``account`` (what belongs to the person, not to a repo) and one
``repo:<repo_key>`` per repository — including repos whose code index is
already gone but whose working memory, plans or conversations are still
stored ("orphans", ``indexed_repo: false``). This module turns that answer into
plain words. It never filters: an unknown count key is shown under its raw
name, because hiding something the vault holds is exactly how old memory used
to survive a "clear".

No UI and no gateway calls here, so the panel and the chat tools describe a
place with the same words.
"""
from __future__ import annotations

import ast
import hashlib
import json

# Plain-language names for the vault's ``<section>.<table>`` count keys. A key
# missing from this map is still shown — under its raw name.
LABELS: dict[str, str] = {
    "repos.notes": "Durable notes",
    "repos.files": "Indexed files",
    "repos.code_index": "Code index (legacy map)",
    "repos.carry": "Carried working model",
    "working.working_set": "Working set (files/commands seen)",
    "working.seen_lines": "Seen output lines",
    "working.turn_memory": "Working memory (turn notes)",
    "working.lyapunov_state": "Session stability state",
    "working.blockers": "Blockers",
    "goals.targets": "Goals and plan items",
    "goals.proofs": "Plan proofs",
    "goals.witnesses": "Plan evidence",
    "evidence.proven_facts": "Proven conclusions",
    "evidence.reality_matrix": "Reality matrix (checked hosts)",
    "artifacts.artifacts": "Saved command outputs",
    "conversation_index.snapshots": "Session snapshots",
    "law.law": "Rules",
    "conversation.conversations": "Conversations",
    "graph.context_events": "Context graph events",
    "skeleton.sections": "Extension data",
}


def label(key: str) -> str:
    """The plain name of a count key, or the key itself — never nothing."""
    return LABELS.get(str(key), str(key))


def flat_counts(counts) -> dict[str, int]:
    """``{"section.table": n}`` from either a flat or a nested ``{section: {table: n}}``
    shape, so a forget reply is described the same way as a listing."""
    out: dict[str, int] = {}

    def _walk(prefix: str, value) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                _walk(f"{prefix}.{k}" if prefix else str(k), v)
        elif isinstance(value, list):
            out[prefix] = out.get(prefix, 0) + len(value)
        else:
            try:
                out[prefix] = out.get(prefix, 0) + int(value or 0)
            except (TypeError, ValueError):
                out[prefix] = out.get(prefix, 0) + 1
    _walk("", counts if isinstance(counts, dict) else {})
    return {k: v for k, v in out.items() if k}


def describe(counts, limit: int = 0) -> str:
    """``"Rules 4, Conversations 1, …"`` — biggest first; empty when nothing."""
    rows = sorted(flat_counts(counts).items(), key=lambda kv: kv[1], reverse=True)
    rows = [(k, v) for k, v in rows if v]
    shown = rows[:limit] if limit else rows
    text = ", ".join(f"{label(k)} {v:,}" for k, v in shown)
    if limit and len(rows) > limit:
        text += f" (+{len(rows) - limit} more)"
    return text


def places(listing) -> list[dict]:
    """The places of an ``everything()`` answer: account first, then repos with the
    most records first. Malformed rows are dropped, empty ones are kept."""
    rows = [p for p in ((listing or {}).get("places") or [])
            if isinstance(p, dict) and p.get("place")]
    rows.sort(key=lambda p: (p.get("place") != "account", -int(p.get("total") or 0)))
    return rows


def find_place(listing, place: str) -> dict | None:
    """The place named ``place`` (``account`` / ``repo:<key>``), or None."""
    return next((p for p in places(listing) if p.get("place") == place), None)


def repo_key_of(p: dict) -> str:
    return str(p.get("repo_key") or str(p.get("place") or "").partition(":")[2])


def is_orphan(p: dict) -> bool:
    """Memory of a repo whose code index / notes file is already gone."""
    return str(p.get("place") or "").startswith("repo:") and p.get("indexed_repo") is False


def place_title(p: dict) -> str:
    """Its title, else the root's last segment, else the repo key."""
    if p.get("place") == "account":
        return "Your account"
    if p.get("title"):
        return str(p["title"])
    root = str(p.get("root") or "").rstrip("/")
    return root.rsplit("/", 1)[-1] if root else repo_key_of(p) or str(p.get("place"))


def find_conversation(listing, conv_id: str) -> tuple[dict | None, dict | None]:
    """``(place, conversation)`` holding the conversation ``conv_id``."""
    for p in places(listing):
        for c in p.get("conversations") or []:
            if isinstance(c, dict) and str(c.get("id")) == str(conv_id):
                return p, c
    return None, None


def find_skeleton(listing, app_id: str) -> dict | None:
    for p in places(listing):
        for s in p.get("skeleton") or []:
            if isinstance(s, dict) and str(s.get("app_id")) == str(app_id):
                return s
    return None


def token(*parts) -> str:
    """Short fingerprint binding a confirmation to the exact thing it was opened
    for: once that thing is forgotten (or changed) the token stops matching and
    a stale view state cannot bring the confirmation back."""
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:8]


def place_token(p: dict) -> str:
    return token("place", p.get("place"), p.get("total"))


def conversation_token(c: dict) -> str:
    return token("conversation", c.get("id"), c.get("messages"), c.get("updated_at"))


def skeleton_token(s: dict) -> str:
    return token("skeleton", s.get("app_id"), len(s.get("sections") or []))


def all_token(listing) -> str:
    return token("all", (listing or {}).get("total"), len(places(listing)))


def left_from_error(e: Exception) -> dict | None:
    """The ``left`` map of a 409 "not everything was forgotten". The SDK turns the
    gateway's detail into the error text, so it is parsed back; None when it
    cannot be (the raw text is then reported instead)."""
    text = str(e)
    for parse in (json.loads, ast.literal_eval):
        try:
            d = parse(text)
        except Exception:
            continue
        if isinstance(d, dict):
            left = d.get("left", d)
            return left if isinstance(left, dict) else None
    return None


__all__ = ["LABELS", "label", "flat_counts", "describe", "places", "find_place",
           "repo_key_of", "is_orphan", "place_title", "find_conversation",
           "find_skeleton", "token", "place_token", "conversation_token",
           "skeleton_token", "all_token", "left_from_error"]
