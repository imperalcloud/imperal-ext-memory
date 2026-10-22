"""Tests for "Everything Webbee holds" and the one forget door.

What is defended: every place the vault reports is SHOWN (account, indexed
repos, memory left over from deleted repos, unknown sections under their raw
name), every delete goes through ``forget_memory``'s door and is re-read
afterwards, a door that leaves something behind is reported as such, and a
forget confirmation only ever opens for the exact thing the user saw.
"""
from __future__ import annotations

import pytest

import handlers as h
import panels
from memory_places import conversation_token, place_token
from tests.test_modals_and_back import has, tree

UID = "imp_u_TEST"


@pytest.fixture
def seeded(gateway, seed_index, seed_memory):
    """An account, one indexed repo with extra sections, and one orphan."""
    seed_index(UID, "live01", repo_root="/Users/dev/wpanel")
    seed_memory(UID, "live01", ["a note"])
    gateway.facts[UID] = [{"fact_id": "fact_1", "fact": "always deploy via script"}]
    gateway.places[UID] = {
        "account": {
            "counts": {"graph.context_events": 81, "evidence.proven_facts": 39,
                       "brand_new.section": 7},
            "conversations": [{"id": "conv-a", "session_id": "s1", "kind": "chat",
                               "title": "Old chat", "messages": 12, "indexed": False}],
            "skeleton": [{"app_id": "mail", "sections": ["inbox", "drafts"]}],
        },
        "repo:live01": {"counts": {"working.turn_memory": 1514, "working.lyapunov_state": 4},
                        "conversations": [{"id": "conv-t", "kind": "terminal",
                                           "title": "Terminal run", "messages": 40}]},
        "repo:gone99": {"counts": {"goals.targets": 777, "artifacts.artifacts": 13},
                        "title": "oldrepo", "root": "/Users/dev/oldrepo"},
    }
    return gateway


async def _section(ctx, **kw):
    return await panels.memory_panel(ctx, section="everything", **kw)


# ── showing ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_everything_shows_account_repo_and_orphan(seeded, make_ctx):
    out = tree(await _section(make_ctx(UID)))
    assert "Everything Webbee holds" in out
    assert "Your account" in out and "Context graph events" in out and "Rules" in out
    assert "Working memory (turn notes)" in out and "Session stability state" in out
    assert "lyapunov" not in out.lower()   # plain names only in the UI
    assert "oldrepo" in out and "code index deleted — memory left over" in out
    assert "Goals and plan items" in out and "Saved command outputs" in out
    assert "Old chat" in out and "no index row" in out and "Terminal run" in out
    assert "Forget all account memory" in out and "Forget everything about this repo" in out
    assert "'fwhat': 'skeleton'" in out and "'fkey': 'mail'" in out
    assert "'fwhat': 'all'" in out


@pytest.mark.asyncio
async def test_unknown_count_keys_are_shown_raw(seeded, make_ctx):
    out = tree(await _section(make_ctx(UID)))
    assert "brand_new.section" in out


@pytest.mark.asyncio
async def test_overview_and_left_panel_show_left_over_memory(seeded, make_ctx):
    ctx = make_ctx(UID)
    over = tree(await panels.memory_panel(ctx))
    assert "Everything Webbee holds about you" in over
    assert "Memory left from deleted repos" in over and "oldrepo" in over
    left = tree(await panels.repos_panel(ctx))
    assert "Memory left from deleted repos" in left and "oldrepo" in left
    # opening the orphan shows its memory, not "nothing stored"
    view = tree(await panels.memory_panel(ctx, repo="gone99"))
    assert "Goals and plan items" in view


@pytest.mark.asyncio
async def test_empty_account_still_offers_the_whole_memory(gateway, make_ctx):
    gateway.places[UID] = {"account": {"counts": {"working.turn_memory": 3}}}
    out = tree(await panels.memory_panel(make_ctx(UID)))
    assert "No repo memory yet" in out
    assert "'section': 'everything'" in out


# ── confirmations are bound to their subject ──────────────────────────

@pytest.mark.asyncio
async def test_forget_modal_needs_a_matching_token(seeded, make_ctx):
    ctx = make_ctx(UID)
    listing = await ctx._gw_namespace("memory", None).everything()
    orphan = next(p for p in listing["places"] if p["place"] == "repo:gone99")

    assert not has(await _section(ctx, fwhat="place", fkey="repo:gone99"), "Dialog")
    assert not has(await _section(ctx, fwhat="place", fkey="repo:gone99", token="deadbeef"), "Dialog")
    shown = await _section(ctx, fwhat="place", fkey="repo:gone99", token=place_token(orphan))
    assert has(shown, "Dialog")
    assert "forget_memory" in tree(shown) and "'key': 'repo:gone99'" in tree(shown)

    await h.fn_forget_memory(ctx, h.ForgetMemoryParams(what="place", key="repo:gone99"))
    after = await _section(ctx, fwhat="place", fkey="repo:gone99", token=place_token(orphan))
    assert not has(after, "Dialog"), "confirmation came back after its subject was forgotten"


@pytest.mark.asyncio
async def test_conversation_modal_binds_to_the_conversation(seeded, make_ctx):
    ctx = make_ctx(UID)
    conv = seeded.places[UID]["account"]["conversations"][0]
    shown = await _section(ctx, fwhat="conversation", fkey="conv-a", token=conversation_token(conv))
    assert has(shown, "Dialog") and "Old chat" in tree(shown)
    conv["messages"] = 13   # it changed after the window was opened
    assert not has(await _section(ctx, fwhat="conversation", fkey="conv-a",
                                  token=conversation_token({**conv, "messages": 12})), "Dialog")


# ── forget_memory ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_forget_memory_place_success_is_reread(seeded, make_ctx):
    res = await h.fn_forget_memory(make_ctx(UID), h.ForgetMemoryParams(what="place", key="repo:gone99"))
    assert res.status == "success", res.error
    assert "repo:gone99" not in seeded.places[UID]
    assert res.data.verified is True and res.data.left == {}
    assert "Goals and plan items 777" in res.summary and "confirms nothing" in res.summary
    methods = [m for _, m, _ in seeded.calls]
    assert "everything" in methods[methods.index("forget") + 1:]


@pytest.mark.asyncio
async def test_forget_memory_conversation_and_rule(seeded, make_ctx):
    ctx = make_ctx(UID)
    res = await h.fn_forget_memory(ctx, h.ForgetMemoryParams(what="conversation", key="conv-t"))
    assert res.status == "success", res.error
    assert seeded.places[UID]["repo:live01"]["conversations"] == []
    res = await h.fn_forget_memory(ctx, h.ForgetMemoryParams(what="law", key="fact_1"))
    assert res.status == "success", res.error
    assert seeded.facts[UID] == []


@pytest.mark.asyncio
async def test_forget_memory_409_names_what_is_left(seeded, make_ctx):
    seeded.stubborn.add("repo:gone99")
    res = await h.fn_forget_memory(make_ctx(UID), h.ForgetMemoryParams(what="place", key="repo:gone99"))
    assert res.status == "error"
    assert "Goals and plan items 777" in res.error and "NOT confirmed" in res.error
    assert res.retryable is True


@pytest.mark.asyncio
async def test_forget_memory_never_guesses(seeded, make_ctx):
    ctx = make_ctx(UID)
    for p in (h.ForgetMemoryParams(what="place"), h.ForgetMemoryParams(what="conversation", key=" "),
              h.ForgetMemoryParams(what="place", key="gone99"), h.ForgetMemoryParams(what="nuke", key="x"),
              h.ForgetMemoryParams(what="evidence", key="f1")):
        assert (await h.fn_forget_memory(ctx, p)).status == "error"
    missing = await h.fn_forget_memory(ctx, h.ForgetMemoryParams(what="place", key="repo:nope"))
    assert missing.status == "error" and "repo:gone99" in missing.error
    assert not any(m == "forget" for _, m, _ in seeded.calls)


@pytest.mark.asyncio
async def test_forget_everything(seeded, make_ctx):
    res = await h.fn_forget_memory(make_ctx(UID), h.ForgetMemoryParams(what="all"))
    assert res.status == "success", res.error
    assert res.data.total_after == 0
    assert (await make_ctx(UID)._gw_namespace("memory", None).everything())["places"] == []


@pytest.mark.asyncio
async def test_memory_overview_lists_every_place(seeded, make_ctx):
    res = await h.fn_memory_overview(make_ctx(UID), h.EmptyParams())
    assert res.status == "success", res.error
    assert res.data.orphan_count == 1 and res.data.place_count == 3
    assert "left over" in res.summary and "repo:gone99" in res.summary


# ── delete_repo verifies against the whole memory ─────────────────────

@pytest.mark.asyncio
async def test_delete_repo_takes_every_section_and_rereads(seeded, make_ctx):
    res = await h.fn_delete_repo(make_ctx(UID), h.DeleteRepoParams(repo="wpanel"))
    assert res.status == "success", res.error
    assert "repo:live01" not in seeded.places[UID] and "live01" not in seeded.files[UID]
    assert res.data["verified"] is True and res.data["left"] == {}
    assert res.data["forgotten"]["working.turn_memory"] == 1514


@pytest.mark.asyncio
async def test_delete_repo_erases_an_orphan_by_key(seeded, make_ctx):
    res = await h.fn_delete_repo(make_ctx(UID), h.DeleteRepoParams(repo="gone99"))
    assert res.status == "success", res.error
    assert "repo:gone99" not in seeded.places[UID]
    assert "oldrepo" in res.summary


@pytest.mark.asyncio
async def test_delete_repo_reports_left_overs_from_the_reread(seeded, make_ctx):
    seeded.stubborn.add("repo:live01")
    res = await h.fn_delete_repo(make_ctx(UID), h.DeleteRepoParams(repo="live01"))
    assert res.status == "error"
    assert "NOT confirmed" in res.error and "Working memory (turn notes)" in res.error
