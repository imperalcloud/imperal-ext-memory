"""Tests for erasing ONE repository's memory (delete_repo).

Split out of ``test_handlers.py``: the deploy validator warns above 300 lines,
and this is a genuinely separate concern — every other test edits notes INSIDE
a repo's memory, while these remove the repo's memory entirely.

What is actually being defended here: the promise that nothing is left behind.
A delete that merely issues DEL and reports its own arguments would pass a
naive test while leaving keys in Redis. So these tests assert on the KEYSPACE
after the call — including the case where a key survives, which must surface
as an error naming it rather than a cheerful success.
"""
import pytest

import app as app_mod
import handlers as h


# ── 5. ERASE A REPO — the guarantee must be verified, not assumed ──────

@pytest.mark.asyncio
async def test_delete_repo_removes_both_key_families(redis_mock, make_ctx,
                                                     seed_index, seed_memory):
    """Index AND notes must both go — they are two separate keys."""
    seed_index("imp_u_TEST", "abc123")
    seed_memory("imp_u_TEST", "abc123", ["a fact", "another"])
    ctx = make_ctx("imp_u_TEST")

    res = await h.fn_delete_repo(ctx, h.DeleteRepoParams(repo="abc123"))
    assert res.status == "success", res.error

    assert f"{app_mod.INDEX_PREFIX}imp_u_TEST:abc123" not in redis_mock.store
    assert f"{app_mod.MEMORY_PREFIX}imp_u_TEST:abc123" not in redis_mock.store
    assert redis_mock.store == {}
    assert res.data["keys_deleted"] == 2
    assert res.data["notes_removed"] == 2
    assert res.data["verified"] is True
    assert not res.data["leftover_keys"]


@pytest.mark.asyncio
async def test_delete_repo_erases_orphaned_notes_without_an_index(
        redis_mock, make_ctx, seed_memory):
    """Note-sets from the OLD repo_key formula have no index — still erasable.

    This is the real reason the tool exists: those orphans are invisible to
    the terminal agent and would otherwise sit in Redis for 90 days.
    """
    seed_memory("imp_u_TEST", "orphan99", ["stale fact"])
    ctx = make_ctx("imp_u_TEST")

    res = await h.fn_delete_repo(ctx, h.DeleteRepoParams(repo="orphan99"))
    assert res.status == "success", res.error
    assert res.data["had_index"] is False
    assert res.data["had_notes"] is True
    assert res.data["keys_deleted"] == 1
    assert res.data["verified"] is True
    assert redis_mock.store == {}


@pytest.mark.asyncio
async def test_delete_repo_touches_only_the_named_repo(redis_mock, make_ctx,
                                                       seed_index, seed_memory):
    """A delete must never widen: the other repos stay byte-for-byte intact."""
    seed_index("imp_u_TEST", "target01")
    seed_memory("imp_u_TEST", "target01", ["doomed"])
    seed_index("imp_u_TEST", "keepme02")
    seed_memory("imp_u_TEST", "keepme02", ["survivor"])
    before = dict(redis_mock.store)
    ctx = make_ctx("imp_u_TEST")

    res = await h.fn_delete_repo(ctx, h.DeleteRepoParams(repo="target01"))
    assert res.status == "success", res.error

    assert redis_mock.store[f"{app_mod.INDEX_PREFIX}imp_u_TEST:keepme02"] == \
        before[f"{app_mod.INDEX_PREFIX}imp_u_TEST:keepme02"]
    assert redis_mock.store[f"{app_mod.MEMORY_PREFIX}imp_u_TEST:keepme02"] == \
        before[f"{app_mod.MEMORY_PREFIX}imp_u_TEST:keepme02"]
    assert len(redis_mock.store) == 2


@pytest.mark.asyncio
async def test_delete_repo_never_crosses_users(redis_mock, make_ctx,
                                               seed_index, seed_memory):
    """Same repo_key under ANOTHER user must survive untouched."""
    seed_index("imp_u_TEST", "shared01")
    seed_memory("imp_u_TEST", "shared01", ["mine"])
    seed_index("imp_u_OTHER", "shared01")
    seed_memory("imp_u_OTHER", "shared01", ["theirs"])

    res = await h.fn_delete_repo(make_ctx("imp_u_TEST"),
                                 h.DeleteRepoParams(repo="shared01"))
    assert res.status == "success", res.error

    assert f"{app_mod.INDEX_PREFIX}imp_u_OTHER:shared01" in redis_mock.store
    assert f"{app_mod.MEMORY_PREFIX}imp_u_OTHER:shared01" in redis_mock.store
    assert f"{app_mod.INDEX_PREFIX}imp_u_TEST:shared01" not in redis_mock.store


@pytest.mark.asyncio
async def test_delete_repo_rejects_unknown_repo_and_names_the_known(
        redis_mock, make_ctx, seed_index):
    """Never delete on a guess: an unmatched selector is an error, not a pick."""
    seed_index("imp_u_TEST", "abc123", repo_root="/Users/dev/realrepo")
    ctx = make_ctx("imp_u_TEST")

    res = await h.fn_delete_repo(ctx, h.DeleteRepoParams(repo="does-not-exist"))
    assert res.status == "error"
    assert "realrepo" in res.error or "abc123" in res.error
    # nothing removed
    assert f"{app_mod.INDEX_PREFIX}imp_u_TEST:abc123" in redis_mock.store


@pytest.mark.asyncio
async def test_delete_repo_reports_leftovers_instead_of_claiming_success(
        redis_mock, make_ctx, seed_index, seed_memory, monkeypatch):
    """If a key SURVIVES the delete, the answer must say so.

    The whole promise is 'nothing is left', so the failure mode that matters
    is a wipe that silently leaves something behind. Simulate a key that
    refuses to die and assert the tool reports it rather than reporting
    success.
    """
    seed_index("imp_u_TEST", "abc123")
    seed_memory("imp_u_TEST", "abc123", ["a fact"])

    real_delete = app_mod.get_redis

    async def _factory():
        r = await real_delete()

        async def _stubborn(*keys):
            # Delete the index but leave the notes key behind.
            n = 0
            for k in keys:
                if k.startswith(app_mod.INDEX_PREFIX) and k in r.store:
                    del r.store[k]
                    n += 1
            return n

        r.delete = _stubborn
        return r

    monkeypatch.setattr(app_mod, "get_redis", _factory)

    res = await h.fn_delete_repo(make_ctx("imp_u_TEST"),
                                 h.DeleteRepoParams(repo="abc123"))
    assert res.status == "error"
    # ActionResult.error() carries no data payload, so the surviving key must
    # be named in the message — otherwise the failure is unactionable.
    assert "NOT confirmed" in res.error
    assert app_mod.MEMORY_PREFIX in res.error
    # and the survivor really is still there
    assert f"{app_mod.MEMORY_PREFIX}imp_u_TEST:abc123" in redis_mock.store
