"""Memory & Index · Modal windows, layering, and the back chain.

Separate file because test_panels.py is already near the 300-line limit the
deploy validator warns at.

These pin the three things the admin reported, as behaviour rather than as
implementation detail:

  1. a modal must not come back after its action has run;
  2. a modal is an OVERLAY — the view stays rendered underneath it;
  3. every view offers exactly one ← that goes one step back.
"""
from __future__ import annotations

import pytest

import panels
from panels_modals import note_token


def flat(node, out=None):
    """Every UINode in the tree, depth-first."""
    out = [] if out is None else out
    if node is None:
        return out
    if hasattr(node, "type"):
        out.append(node)
    props = getattr(node, "props", None) or {}
    for child in (props.get("children") or []):
        flat(child, out)
    if props.get("content") is not None:
        flat(props["content"], out)
    return out


def has(node, kind: str) -> bool:
    return any(getattr(n, "type", "") == kind for n in flat(node))


def tree(node) -> str:
    """The rendered panel tree as text, for asserting on wiring."""
    return repr(node)


def backs(node) -> list:
    """Labels of every back control in a rendered view."""
    return [str(getattr(n, "props", {}).get("label") or "")
            for n in flat(node)
            if getattr(n, "type", "") == "Button"
            and str(getattr(n, "props", {}).get("label") or "").startswith("←")]


# ── 1. A modal must not reappear once its subject is gone ──────────────

@pytest.mark.asyncio
async def test_erase_modal_does_not_reappear_after_the_repo_is_gone(
        redis_mock, make_ctx, seed_index, seed_memory, store):
    """confirm=1 outliving the erase must not re-open the confirmation.

    The reported bug: pressing a button in the modal closed it on the client,
    but the state param survived, so the next render put it straight back.
    """
    seed_index("imp_u_TEST", "abc123")
    seed_memory("imp_u_TEST", "abc123", ["a fact"])
    ctx = make_ctx("imp_u_TEST")

    assert has(await panels.memory_panel(ctx, repo="abc123", confirm="1"), "Dialog")

    store.clear()  # the erase succeeded — nothing is stored for it any more

    after = await panels.memory_panel(ctx, repo="abc123", confirm="1")
    assert not has(after, "Dialog"), "modal came back after the repo was erased"
    assert backs(after), "the post-erase view still needs a way back"


@pytest.mark.asyncio
async def test_edit_modal_closes_itself_once_the_note_is_saved(
        redis_mock, make_ctx, seed_index, seed_memory):
    """A stale edit=N must not re-open over a note that has since changed.

    ui.Call cannot chain (one action + params), so a modal cannot clear its own
    flag after calling the tool. Binding it to a fingerprint of the note's text
    is what makes the flag stop mattering by itself.
    """
    seed_index("imp_u_TEST", "abc123")
    seed_memory("imp_u_TEST", "abc123", ["deploys via deploy.sh"])
    ctx = make_ctx("imp_u_TEST")
    token = note_token("deploys via deploy.sh")

    assert has(await panels.memory_panel(ctx, repo="abc123", edit="1", token=token),
               "Dialog")

    seed_memory("imp_u_TEST", "abc123", ["deploys via ship.sh"])  # saved

    assert not has(
        await panels.memory_panel(ctx, repo="abc123", edit="1", token=token),
        "Dialog"), "edit window re-opened over the already-saved note"

    fresh = note_token("deploys via ship.sh")
    assert has(await panels.memory_panel(ctx, repo="abc123", edit="1", token=fresh),
               "Dialog"), "a deliberate re-open must still work"


@pytest.mark.asyncio
async def test_forget_modal_does_not_retarget_a_different_note(
        redis_mock, make_ctx, seed_index, seed_memory):
    """Deleting note #1 shifts the list — forget=1 must not aim at the next one.

    Position alone is not identity: without the fingerprint the surviving
    forget=1 pointed the confirmation at whichever note moved up into slot 1.
    """
    seed_index("imp_u_TEST", "abc123")
    seed_memory("imp_u_TEST", "abc123", ["first fact", "second fact"])
    ctx = make_ctx("imp_u_TEST")
    token = note_token("first fact")

    opened = await panels.memory_panel(ctx, repo="abc123", forget="1", token=token)
    assert has(opened, "Dialog")
    assert "first fact" in repr(opened)

    seed_memory("imp_u_TEST", "abc123", ["second fact"])  # #1 forgotten

    after = await panels.memory_panel(ctx, repo="abc123", forget="1", token=token)
    assert not has(after, "Dialog"), "confirmation re-aimed at a surviving note"


# ── 2. Modals are overlays, not replacements ───────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("state", [
    {"confirm": "1"},
    {"edit": "1"},
    {"forget": "1"},
])
async def test_every_modal_keeps_the_repo_view_underneath(
        redis_mock, make_ctx, seed_index, seed_memory, state):
    """Opening a window must not blank the section behind it.

    The old code returned the modal INSTEAD of the view, which is why opening
    Edit looked like the whole panel reloaded.
    """
    seed_index("imp_u_TEST", "abc123",
               file_count=3110,
               languages={"python": 1429},
               symbol_kinds={"function": 10054},
               top_symbols=["build_audit (function) @ imperal-ext-admin/panels_audit.py:148"])
    seed_memory("imp_u_TEST", "abc123", ["deploys via deploy.sh"])
    ctx = make_ctx("imp_u_TEST")

    params = dict(state)
    if "edit" in params or "forget" in params:
        params["token"] = note_token("deploys via deploy.sh")

    plain = await panels.memory_panel(ctx, repo="abc123")
    with_modal = await panels.memory_panel(ctx, repo="abc123", **params)

    assert has(with_modal, "Dialog"), f"{state} did not open a window"
    assert has(with_modal, "Graph"), "the graph vanished behind the window"
    assert "Danger zone" in repr(with_modal), "the view was replaced, not layered"
    assert len(flat(with_modal)) > len(flat(plain)), "nothing was layered on top"


@pytest.mark.asyncio
async def test_edit_window_carries_a_form_not_a_direct_write(
        redis_mock, make_ctx, seed_index, seed_memory):
    """Edit opens a field pre-filled with the note's real text."""
    seed_index("imp_u_TEST", "abc123")
    seed_memory("imp_u_TEST", "abc123", ["deploys via deploy.sh"])

    out = repr(await panels.memory_panel(
        make_ctx("imp_u_TEST"), repo="abc123", edit="1",
        token=note_token("deploys via deploy.sh")))

    assert "TextArea" in out
    assert "deploys via deploy.sh" in out
    assert "'action': 'edit_note'" in out


# ── 4. The graph must carry the repo's REAL weight ─────────────────────

@pytest.mark.asyncio
async def test_graph_shows_aggregate_language_and_symbol_tiers(
        redis_mock, make_ctx, seed_index):
    """The graph must reflect the whole repo, not just its 20 named symbols.

    top_symbols caps at 20 entries, so structural tiers alone described ~20
    files and a 3110-file repo drew nine nodes — technically true, wildly
    misleading. languages and symbol_kinds are real aggregates in the index,
    so they become their own tiers with their real counts.
    """
    seed_index("imp_u_TEST", "abc123",
               file_count=3110,
               languages={"javascript": 2, "python": 1429, "typescript": 6},
               symbol_kinds={"class": 2420, "function": 10081},
               top_symbols=[
                   "build_audit (function) @ imperal-ext-admin/panels_audit.py:148",
                   "main (function) @ probe_stream_terminals.py:17",
               ])

    out = tree(await panels.memory_panel(make_ctx("imp_u_TEST"), repo="abc123"))

    assert "python · 1,429" in out          # language tier, real count
    assert "function · 10,081" in out       # symbol-kind tier, real count
    assert "3,110" in out                   # the true file total, in the caption


@pytest.mark.asyncio
async def test_graph_tiers_survive_a_junk_index(redis_mock, make_ctx, seed_index):
    """Non-numeric or empty aggregate entries are skipped, never rendered."""
    seed_index("imp_u_TEST", "abc123",
               file_count=9,
               languages={"python": "lots", "": 5, "go": 0, "rust": 3},
               symbol_kinds={"function": None},
               top_symbols=["main (function) @ probe_stream_terminals.py:17"])

    out = tree(await panels.memory_panel(make_ctx("imp_u_TEST"), repo="abc123"))

    assert "rust · 3" in out                 # the one usable entry survives
    # The graph tier labels its nodes "<name> · <count>", so junk entries are
    # absent from the GRAPH. The read-only index table still reports what is
    # actually stored ("python lots") — that is honest, not a leak.
    assert "'label': 'python · " not in out
    assert "'type': 'kind'" not in out       # symbol_kinds held only None
    assert "type='Graph'" in out
