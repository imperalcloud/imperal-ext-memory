"""Memory & Index · Chat parameter models + shared note helpers.

Split out of ``handlers.py``: the deploy validator warns on modules over 300
lines, and the four concerns here (params, reads, explainer, writes) are
genuinely separate. ``handlers.py`` re-exports every name, so `import
handlers` and the tests that use it keep working unchanged.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app import (
    NOTE_CHARS,
    age,
    known_repos,
    load_memories,
    pick,
)
from storage_user_mem import citation_text


class EmptyParams(BaseModel):
    """No parameters needed."""


class RepoParams(BaseModel):
    repo: str = Field(
        default="",
        description=("Which repo — its repo_key, or any fragment of its path/name. "
                     "Empty = the most recently touched one."),
    )


class AddNoteParams(BaseModel):
    note: str = Field(description=f"The fact to remember (max {NOTE_CHARS} chars)")
    repo: str = Field(
        default="",
        description="Which repo — repo_key or path fragment. Empty = most recent.")
    citations: list[str] = Field(
        default_factory=list,
        description="Optional file paths this fact is about, e.g. ['app/billing/service.py']")


class EditNoteParams(BaseModel):
    position: int = Field(
        description="Which note to change — its position number from list_notes (1-based)")
    note: str = Field(description=f"The corrected text (max {NOTE_CHARS} chars)")
    repo: str = Field(
        default="",
        description="Which repo — repo_key or path fragment. Empty = most recent.")


class DeleteNoteParams(BaseModel):
    position: int = Field(
        description="Which note to forget — its position number from list_notes (1-based)")
    repo: str = Field(
        default="",
        description="Which repo — repo_key or path fragment. Empty = most recent.")


class DeleteRepoParams(BaseModel):
    repo: str = Field(
        description=("Which repo to erase — its repo_key, or a fragment of its "
                     "path/name. Required: erasing whatever happens to be most "
                     "recent would be a coin flip with the user's memory."))


class ForgetMemoryParams(BaseModel):
    what: str = Field(
        description=("What kind of thing to forget — one of: 'place' (everything of one "
                     "repo, key 'repo:<repo_key>', or of the account, key 'account'), "
                     "'conversation' (one conversation and everything its session left; "
                     "key = conversation id), 'law' (one rule; key = rule/fact id), "
                     "'evidence' (one proven conclusion; key = fact id, plus project_id), "
                     "'reality' (the reality matrix of a project; key = project id, e.g. "
                     "'_tenant'), 'skeleton' (one extension's data; key = app id), "
                     "'graph' (context-graph events of one subject; key = subject id), "
                     "'all' (everything Webbee holds about the user; no key). Required: "
                     "deleting memory is never applied to a guessed default."))
    key: str = Field(
        default="",
        description=("Which one — exactly as memory_overview reports it (a place like "
                     "'repo:55d6d1e4dd1f' or 'account', a conversation id, a rule id, an "
                     "app id, a project id, a subject id). Required for everything "
                     "except what='all'."))
    project_id: str = Field(
        default="",
        description="Only for what='evidence': the project the conclusion belongs to.")


def _entry_written(e: dict) -> str:
    return age(e.get("edited_at") or e.get("distilled_at"))


def _notes_payload(repo_key: str, entries: list) -> list[dict]:
    """Newest first for a reader; position is the 1-based storage index."""
    out = []
    for idx, e in enumerate(entries, start=1):
        if not isinstance(e, dict):
            continue
        out.append({
            "note": str(e.get("note") or ""),
            "citations": [t for t in (citation_text(c) for c in e.get("citations") or []) if t],
            "repo_key": repo_key,
            "distilled_at": e.get("distilled_at"),
            "distilled_git_ref": e.get("distilled_git_ref"),
            "edited_at": e.get("edited_at"),
            "source": e.get("source") or ("edited" if e.get("edited_at") else "distilled"),
            "position": idx,
            "written": _entry_written(e),
        })
    out.reverse()
    return out


async def _resolve_notes(ctx, want: str):
    """(memory_dict, error_message) for a repo selector."""
    mems = await load_memories(ctx)
    if not mems:
        return None, ("No durable notes stored yet. They build up automatically as the "
                      "Webbee terminal agent works in a repository.")
    chosen = pick(mems, want)
    if chosen is None:
        return None, f"No stored notes match '{want}'. Known: {known_repos(mems)}"
    return chosen, None
