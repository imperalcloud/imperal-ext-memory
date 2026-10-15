"""Tests for erasing ONE repository's memory (delete_repo).

Split out of ``test_handlers.py``: the deploy validator warns above 300 lines,
and this is a genuinely separate concern — every other test edits notes INSIDE
a repo's memory, while these remove the repo's memory entirely.

What is actually being defended here: the promise that nothing is left behind.
A delete that merely asks the vault and reports its own intent would pass a
naive test while leaving the repo file in place. So these tests assert on the
VAULT after the call — including the case where the file survives, which must
surface as an error naming it rather than a cheerful success.
"""
import pytest

import handlers as h


# ── 5. ERASE A REPO — the guarantee must be verified, not assumed ──────

@pytest.mark.asyncio
async def test_delete_repo_removes_index_and_notes(gateway, make_ctx,
                                                   seed_index, seed_memory):
    """Index AND notes must both go — they share the repo's one vault file."""
    seed_index("imp_u_TEST", "abc123")
    seed_memory("imp_u_TEST", "abc123", ["a fact", "another"])
    ctx = make_ctx("imp_u_TEST")

    res = await h.fn_delete_repo(ctx, h.DeleteRepoParams(repo="abc123"))
    assert res.status == "success", res.error

    assert gateway.files["imp_u_TEST"] == {}
    assert res.data["had_index"] is True
    assert res.data["notes_removed"] == 2
    assert res.data["deleted"] is True
    assert res.data["still_listed"] is False
    assert res.data["verified"] is True


@pytest.mark.asyncio
async def test_delete_repo_verifies_with_a_fresh_listing(gateway, make_ctx,
                                                         seed_index, seed_memory):
    """``verified`` must come from a listing taken AFTER the delete."""
    seed_index("imp_u_TEST", "abc123")
    seed_memory("imp_u_TEST", "abc123", ["a fact"])

    await h.fn_delete_repo(make_ctx("imp_u_TEST"), h.DeleteRepoParams(repo="abc123"))

    methods = [m for _, m, _ in gateway.calls]
    assert "delete_repo" in methods
    assert "repos" in methods[methods.index("delete_repo") + 1:], (
        "no listing after the delete — the result would only be the delete's own claim")


@pytest.mark.asyncio
async def test_delete_repo_erases_orphaned_notes_without_an_index(
        gateway, make_ctx, seed_memory):
    """Note-sets from the OLD repo_key formula have no index — still erasable.

    This is the real reason the tool exists: those orphans are invisible to
    the terminal agent and, kept with no expiry, would otherwise stay forever.
    """
    seed_memory("imp_u_TEST", "orphan99", ["stale fact"])
    ctx = make_ctx("imp_u_TEST")

    res = await h.fn_delete_repo(ctx, h.DeleteRepoParams(repo="orphan99"))
    assert res.status == "success", res.error
    assert res.data["had_index"] is False
    assert res.data["had_notes"] is True
    assert res.data["deleted"] is True
    assert res.data["verified"] is True
    assert gateway.files["imp_u_TEST"] == {}


@pytest.mark.asyncio
async def test_delete_repo_touches_only_the_named_repo(gateway, make_ctx,
                                                       seed_index, seed_memory):
    """A delete must never widen: the other repos stay intact."""
    seed_index("imp_u_TEST", "target01")
    seed_memory("imp_u_TEST", "target01", ["doomed"])
    seed_index("imp_u_TEST", "keepme02")
    seed_memory("imp_u_TEST", "keepme02", ["survivor"])
    before = dict(gateway.files["imp_u_TEST"]["keepme02"])
    ctx = make_ctx("imp_u_TEST")

    res = await h.fn_delete_repo(ctx, h.DeleteRepoParams(repo="target01"))
    assert res.status == "success", res.error

    assert list(gateway.files["imp_u_TEST"]) == ["keepme02"]
    assert gateway.files["imp_u_TEST"]["keepme02"] == before


@pytest.mark.asyncio
async def test_delete_repo_never_crosses_users(gateway, make_ctx,
                                               seed_index, seed_memory):
    """Same repo_key under ANOTHER user must survive untouched."""
    seed_index("imp_u_TEST", "shared01")
    seed_memory("imp_u_TEST", "shared01", ["mine"])
    seed_index("imp_u_OTHER", "shared01")
    seed_memory("imp_u_OTHER", "shared01", ["theirs"])

    res = await h.fn_delete_repo(make_ctx("imp_u_TEST"),
                                 h.DeleteRepoParams(repo="shared01"))
    assert res.status == "success", res.error

    assert "shared01" in gateway.files["imp_u_OTHER"]
    assert "shared01" not in gateway.files["imp_u_TEST"]


@pytest.mark.asyncio
async def test_delete_repo_rejects_unknown_repo_and_names_the_known(
        gateway, make_ctx, seed_index):
    """Never delete on a guess: an unmatched selector is an error, not a pick."""
    seed_index("imp_u_TEST", "abc123", repo_root="/Users/dev/realrepo")
    ctx = make_ctx("imp_u_TEST")

    res = await h.fn_delete_repo(ctx, h.DeleteRepoParams(repo="does-not-exist"))
    assert res.status == "error"
    assert "realrepo" in res.error or "abc123" in res.error
    # nothing removed
    assert "abc123" in gateway.files["imp_u_TEST"]
    assert all(m != "delete_repo" for _, m, _ in gateway.calls)


@pytest.mark.asyncio
async def test_delete_repo_reports_a_survivor_instead_of_claiming_success(
        gateway, make_ctx, seed_index, seed_memory, monkeypatch):
    """If the repo SURVIVES the delete, the answer must say so.

    The whole promise is 'nothing is left', so the failure mode that matters
    is a wipe that silently leaves something behind. Simulate a vault that
    claims the delete but keeps the file, and assert the tool reports it
    rather than reporting success.
    """
    seed_index("imp_u_TEST", "abc123")
    seed_memory("imp_u_TEST", "abc123", ["a fact"])

    from tests.conftest import FakeMemoryClient

    async def _claims_but_keeps(self, repo_key):
        return {"repo_key": repo_key, "deleted": True}

    monkeypatch.setattr(FakeMemoryClient, "delete_repo", _claims_but_keeps)

    res = await h.fn_delete_repo(make_ctx("imp_u_TEST"),
                                 h.DeleteRepoParams(repo="abc123"))
    assert res.status == "error"
    # ActionResult.error() carries no data payload, so the survivor must be
    # named in the message — otherwise the failure is unactionable.
    assert "NOT confirmed" in res.error
    assert "abc123" in res.error
    # and the survivor really is still there
    assert "abc123" in gateway.files["imp_u_TEST"]


@pytest.mark.asyncio
async def test_delete_repo_listing_outage_is_not_read_as_gone(
        gateway, make_ctx, seed_index, monkeypatch):
    """The verification listing must not fail soft into 'nothing listed'."""
    seed_index("imp_u_TEST", "abc123")
    ctx = make_ctx("imp_u_TEST")

    from tests.conftest import FakeMemoryClient
    real_repos = FakeMemoryClient.repos
    seen = []

    async def _down_after_first(self):
        seen.append(1)
        if len(seen) > 1:
            raise ConnectionError("gateway down")
        return await real_repos(self)

    monkeypatch.setattr(FakeMemoryClient, "repos", _down_after_first)

    res = await h.fn_delete_repo(ctx, h.DeleteRepoParams(repo="abc123"))
    assert res.status == "error"
    assert res.error.startswith("Failed to erase repo memory")
