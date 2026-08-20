"""Mixed timestamp shapes must never break the inventory read.

Live failure (admin@imperal.io, 2026-08-20): opening Memory & Index showed
"Could not load your repo memory — try again shortly". The real error was

    '<' not supported between instances of 'str' and 'int'

The two note sets in that account were written by different generations of the
kernel distiller and carry DIFFERENT timestamp shapes:

    repo 0527e446e3fd  distilled_at = '2026-08-13T22:39:53.324168+00:00'  (str)
    repo f20e613c68f0  distilled_at = 1787212894                          (int)

Sorting "freshest first" compared one against the other and raised, so the
whole panel — index maps included — died on data that was perfectly valid.

Two rules come out of that, and both are tested here:

1. ORDERING NEVER RAISES. A store may legitimately hold several timestamp
   shapes at once (ISO strings, epoch ints, None, junk). Sorting is a
   presentation nicety; it must degrade, never take the read down with it.
2. AN ISO TIMESTAMP IS A REAL TIMESTAMP. ``age()`` used to accept only
   int/float and answered "unknown" for ISO strings, so even a non-crashing
   read would have shown half the notes as undated. Parsing it is the same
   fix as sorting it.
"""
import json

import pytest

import app as app_mod
import handlers as h
import panels_common


ISO = "2026-08-13T22:39:53.324168+00:00"
ISO_EPOCH = 1786775993          # the same instant, seconds since epoch
EPOCH = 1787212894              # newer than ISO_EPOCH


def _seed_mixed(store, uid="imp_u_TEST"):
    """The exact production shape: ISO notes in one repo, epoch in another."""
    store[f"{app_mod.MEMORY_PREFIX}{uid}:iso_repo"] = json.dumps({
        "user_id": uid, "repo_key": "iso_repo", "updated_at": None,
        "entries": [{"note": "written by the older distiller",
                     "citations": [], "distilled_at": ISO, "edited_at": None}],
    })
    store[f"{app_mod.MEMORY_PREFIX}{uid}:epoch_repo"] = json.dumps({
        "user_id": uid, "repo_key": "epoch_repo", "updated_at": None,
        "entries": [{"note": "written by the current distiller",
                     "citations": [], "distilled_at": EPOCH, "edited_at": EPOCH}],
    })


# ── 1. the read must survive mixed shapes ────────────────────────────

@pytest.mark.asyncio
async def test_load_memories_survives_mixed_timestamp_shapes(redis_mock, store):
    """The crash itself: ISO string vs epoch int in one keyspace."""
    _seed_mixed(store)
    out = await app_mod.load_memories("imp_u_TEST")
    assert len(out) == 2, out


@pytest.mark.asyncio
async def test_load_memories_orders_newest_first_across_shapes(redis_mock, store):
    """Not just 'does not crash' — the ISO note really is the older one, and
    ordering must reflect that instead of falling back on dict order."""
    _seed_mixed(store)
    out = await app_mod.load_memories("imp_u_TEST")
    assert [d["_repo_key"] for d in out] == ["epoch_repo", "iso_repo"], out


@pytest.mark.asyncio
async def test_load_indexes_survives_mixed_updated_at(redis_mock, store):
    """Same defect, other store: index maps sort on updated_at."""
    uid = "imp_u_TEST"
    store[f"{app_mod.INDEX_PREFIX}{uid}:a"] = json.dumps(
        {"repo_root": "/x/a", "updated_at": ISO})
    store[f"{app_mod.INDEX_PREFIX}{uid}:b"] = json.dumps(
        {"repo_root": "/x/b", "updated_at": EPOCH})
    out = await app_mod.load_indexes(uid)
    assert [d["_repo_key"] for d in out] == ["b", "a"], out


@pytest.mark.asyncio
async def test_list_repos_reports_both_repos_not_an_error(redis_mock, store, make_ctx):
    """End to end: the tool the panel calls answers with data, not the
    'Could not load your repo memory' the user actually saw."""
    _seed_mixed(store)
    res = await h.fn_list_repos(make_ctx(), h.EmptyParams())
    assert res.status == "success", getattr(res, "error", res)
    assert len(res.data) == 2, res.data


@pytest.mark.asyncio
async def test_inventory_panel_survives_mixed_shapes(redis_mock, store, make_ctx):
    """The panel builds its own inventory rows and sorts them too."""
    _seed_mixed(store)
    rows = await panels_common._inventory("imp_u_TEST")   # takes the uid, not ctx
    assert len(rows) == 2, rows


# ── 2. junk must not be mistaken for a timestamp ─────────────────────

@pytest.mark.asyncio
async def test_unparseable_timestamps_sort_last_and_do_not_raise(redis_mock, store):
    """A malformed value is not newer than everything else just because it is
    a string — it sorts as unknown (oldest), and never raises."""
    uid = "imp_u_TEST"
    store[f"{app_mod.MEMORY_PREFIX}{uid}:junk"] = json.dumps({
        "user_id": uid, "repo_key": "junk", "entries": [
            {"note": "n", "citations": [], "distilled_at": "not-a-date"}]})
    store[f"{app_mod.MEMORY_PREFIX}{uid}:good"] = json.dumps({
        "user_id": uid, "repo_key": "good", "entries": [
            {"note": "n", "citations": [], "distilled_at": EPOCH}]})
    out = await app_mod.load_memories(uid)
    assert [d["_repo_key"] for d in out] == ["good", "junk"], out


# ── 3. an ISO timestamp is a real timestamp ──────────────────────────

def test_age_understands_iso_strings():
    """age() answered 'unknown' for ISO strings, so notes written by the older
    distiller would have shown as undated even once sorting was fixed."""
    assert app_mod.age(ISO) != "unknown"


def test_age_still_honest_about_genuinely_unknown_values():
    """The honesty guard stays: nothing is invented for missing/garbage input."""
    for bad in (None, 0, "", "not-a-date", [], {}):
        assert app_mod.age(bad) == "unknown", bad
