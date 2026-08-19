"""Tests for the PANEL interaction layer — buttons that must actually do something.

Why this file exists: three bugs shipped in a row that neither the SDK
validator nor the handler tests could catch, because all of them were about a
button's *wiring* rather than a handler's logic —

  * "How is this stored?" called a second slot="center" panel that never
    mounted, so the click did nothing at all;
  * Edit called ``edit_note`` immediately with the text the note already had,
    which saved it unchanged and reported "was: X now: X";
  * Forget called ``delete_note`` on the spot, with no confirmation.

A handler test cannot see any of that: the handlers were correct in all three
cases. So these tests render the panel tree and assert on what the buttons are
wired to. The tree is inspected via ``repr`` — UINode is not a pydantic model,
so its nested actions do not survive a JSON dump, but they are fully visible in
the repr, and that is what the frontend receives.
"""
import pytest

import panels


def tree(node) -> str:
    """The rendered panel tree as text, for asserting on wiring."""
    return repr(node)


# ── 1. "How is this stored?" must open the explainer ──────────────────

@pytest.mark.asyncio
async def test_storage_button_targets_a_panel_that_mounts(redis_mock, make_ctx,
                                                         seed_index):
    """The inventory button must route to a section, NOT to __panel__storage.

    A second slot="center" panel is not reliably mounted as an overlay target,
    which is exactly why the original button appeared dead. Pinning the wiring
    here means a future refactor cannot quietly reintroduce the dead click.
    """
    seed_index("imp_u_TEST", "abc123")
    out = tree(await panels.repos_panel(make_ctx("imp_u_TEST")))

    assert "'section': 'storage'" in out
    assert "__panel__memory" in out
    assert "__panel__storage" not in out


@pytest.mark.asyncio
async def test_memory_panel_renders_the_explainer_section(redis_mock, make_ctx,
                                                          seed_index):
    """section=storage must render the explainer, not a repo view."""
    seed_index("imp_u_TEST", "abc123")
    out = tree(await panels.memory_panel(make_ctx("imp_u_TEST"), section="storage"))

    assert "Where your repo memory lives" in out


@pytest.mark.asyncio
async def test_explainer_works_for_a_user_with_no_memory(redis_mock, make_ctx):
    """The explainer must open even on an empty account.

    It is resolved before any repo lookup precisely so a new user can read
    how storage works before they have any stored repos.
    """
    out = tree(await panels.memory_panel(make_ctx("imp_u_EMPTY"), section="storage"))

    assert "Where your repo memory lives" in out


# ── 2. Edit must open a field, not save the same text ─────────────────

@pytest.mark.asyncio
async def test_edit_renders_a_prefilled_form_instead_of_saving(
        redis_mock, make_ctx, seed_index, seed_memory):
    """edit=<n> must produce a form pre-filled with that note's CURRENT text."""
    seed_index("imp_u_TEST", "abc123")
    seed_memory("imp_u_TEST", "abc123", ["deploys via deploy.sh", "never edit current/"])

    out = tree(await panels.memory_panel(make_ctx("imp_u_TEST"),
                                         repo="abc123", edit="1"))

    assert "'action': 'edit_note'" in out       # a form, submitted by the user
    assert "TextArea" in out                    # with an actual editable field
    assert "deploys via deploy.sh" in out       # pre-filled with the real text
    assert "'position'" in out                  # and carrying the position


@pytest.mark.asyncio
async def test_note_view_does_not_call_edit_note_on_click(
        redis_mock, make_ctx, seed_index, seed_memory):
    """The Edit BUTTON must open the form — never invoke the write directly.

    This is the actual regression guard: the old button called edit_note with
    the unchanged text, which is why it looked like nothing happened.
    """
    seed_index("imp_u_TEST", "abc123")
    seed_memory("imp_u_TEST", "abc123", ["a fact"])

    out = tree(await panels.memory_panel(make_ctx("imp_u_TEST"), repo="abc123"))

    assert "'function': 'edit_note'" not in out
    assert "'edit': '1'" in out or "'edit': 1" in out


@pytest.mark.asyncio
async def test_out_of_range_and_junk_edit_positions_are_ignored(
        redis_mock, make_ctx, seed_index, seed_memory):
    """A bad edit= must render the normal view, never raise.

    Panel params arrive as strings from the frontend, so a non-numeric value
    is a routine input, not an exceptional one.
    """
    seed_index("imp_u_TEST", "abc123")
    seed_memory("imp_u_TEST", "abc123", ["only note"])
    ctx = make_ctx("imp_u_TEST")

    for bad in ("99", "0", "-3", "abc", ""):
        out = tree(await panels.memory_panel(ctx, repo="abc123", edit=bad))
        assert "'action': 'edit_note'" not in out, f"edit={bad!r} opened a form"
        assert "Code index" in out


# ── 3. Forget must ask first ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_forget_shows_a_strict_modal_naming_the_note(
        redis_mock, make_ctx, seed_index, seed_memory):
    """forget=<n> must open a strict dialog quoting the note about to be lost."""
    seed_index("imp_u_TEST", "abc123")
    seed_memory("imp_u_TEST", "abc123", ["deploys via deploy.sh", "second note"])

    out = tree(await panels.memory_panel(make_ctx("imp_u_TEST"),
                                         repo="abc123", forget="1"))

    assert "type='Dialog'" in out
    assert "'destructive': True" in out          # not dismissable by a stray click
    assert "'function': 'delete_note'" in out    # confirm actually forgets
    assert "deploys via deploy.sh" in out        # the user sees WHICH note
    assert "Keep it" in out or "Cancel" in out   # and has a way out


@pytest.mark.asyncio
async def test_note_view_does_not_call_delete_note_on_click(
        redis_mock, make_ctx, seed_index, seed_memory):
    """The Forget BUTTON must open the modal — never delete on the spot."""
    seed_index("imp_u_TEST", "abc123")
    seed_memory("imp_u_TEST", "abc123", ["a fact"])

    out = tree(await panels.memory_panel(make_ctx("imp_u_TEST"), repo="abc123"))

    assert "'function': 'delete_note'" not in out
    assert "'forget': '1'" in out or "'forget': 1" in out


# ── 4. The visual layer must be real, and must degrade ────────────────

@pytest.mark.asyncio
async def test_index_renders_a_clickable_graph_and_charts(
        redis_mock, make_ctx, seed_index):
    """A populated index must produce a Graph and Charts, not just tables."""
    seed_index("imp_u_TEST", "abc123",
               file_count=3107,
               languages={"python": 1426, "typescript": 6},
               symbol_kinds={"function": 10054, "class": 2420},
               top_symbols=[
                   "main (function) @ probe_stream_terminals.py:17",
                   "build_audit (function) @ imperal-ext-admin/panels_audit.py:148",
                   "CompareRolesResponse (class) @ imperal-ext-admin/models_rbac.py:103",
               ])

    out = tree(await panels.memory_panel(make_ctx("imp_u_TEST"), repo="abc123"))

    assert "type='Graph'" in out
    assert "type='Chart'" in out
    assert "on_node_click" in out


@pytest.mark.asyncio
async def test_graph_focuses_the_clicked_file(redis_mock, make_ctx, seed_index):
    """Clicking a file node must focus that file's symbols.

    ui.Graph injects the clicked node's id as node_id, so the panel resolves it
    back to a path. The ids are SHORT ("f0"), not "file::<path>": Cytoscape ids
    end up inside selector strings where ':' '.' '/' are syntax, which is why
    the first version of this graph drew nothing at all.
    """
    seed_index("imp_u_TEST", "abc123",
               top_symbols=[
                   "build_audit (function) @ imperal-ext-admin/panels_audit.py:148",
                   "main (function) @ probe_stream_terminals.py:17",
               ])

    out = tree(await panels.memory_panel(
        make_ctx("imp_u_TEST"), repo="abc123", node_id="f0"))

    assert "Focused: imperal-ext-admin/panels_audit.py" in out
    assert "← Back to full graph" in out


@pytest.mark.asyncio
async def test_graph_node_ids_are_selector_safe(redis_mock, make_ctx, seed_index):
    """No ':' '.' or '/' in any node/edge id — the exact reason it drew nothing."""
    seed_index("imp_u_TEST", "abc123",
               top_symbols=[
                   "catalog_to_options (function) @ imperal-ext-admin/panels_llm_models.py:195",
                   "build_audit (function) @ imperal-ext-admin/panels_audit.py:148",
                   "main (function) @ probe_stream_terminals.py:17",
               ])

    out = tree(await panels.memory_panel(make_ctx("imp_u_TEST"), repo="abc123"))

    assert "'id': 'file::" not in out
    assert "type='Graph'" in out
    # concentric + animate off = lands inside the viewport instead of drifting
    assert "'layout': 'concentric'" in out
    assert "'animate': False" in out


@pytest.mark.asyncio
async def test_thin_index_degrades_instead_of_faking_structure(
        redis_mock, make_ctx, seed_index):
    """An index with no symbols/languages must render WITHOUT inventing a graph."""
    seed_index("imp_u_TEST", "thin01", file_count=0, languages={},
               symbol_kinds={}, top_symbols=[])

    out = tree(await panels.memory_panel(make_ctx("imp_u_TEST"), repo="thin01"))

    assert "type='Graph'" not in out
    assert "Code index" in out          # the honest table still renders


@pytest.mark.asyncio
async def test_unparsable_symbols_are_skipped_not_guessed(redis_mock, make_ctx,
                                                          seed_index):
    """Symbols not matching the kernel's format must be dropped silently.

    Better to draw less than to draw a wrong graph from a guessed format.
    """
    seed_index("imp_u_TEST", "abc123",
               top_symbols=["totally the wrong shape", "also wrong"])

    out = tree(await panels.memory_panel(make_ctx("imp_u_TEST"), repo="abc123"))

    assert "type='Graph'" not in out
    assert "Code index" in out


# ── 6. Exactly ONE center panel may be registered ─────────────────────

def test_only_one_center_panel_is_registered():
    """Two slot="center" panels fight over one surface — the loser goes blank.

    This shipped TWICE. Only one panel can own the center; the one registered
    FIRST takes it, and the other's responses render nowhere:

      * `memory` first  -> repo view worked, the explainer button did nothing.
      * `storage` first -> explainer showed, repo view was empty. That flip was
        caused by nothing more than an import: panels_memory importing
        storage_body pulled panels_storage in earlier.

    So the guard cannot be "don't add a center panel" — it has to be counted,
    because a plain import is enough to change who wins. The explainer is a
    function rendered at section=storage instead.
    """
    import main

    ext = getattr(main, "ext", None) or getattr(main, "app", None)
    centers = [pid for pid, meta in getattr(ext, "_panels", {}).items()
               if meta.get("slot") == "center"]

    assert centers == ["memory"], (
        f"expected exactly one center panel ('memory'), got {centers} — "
        "a second slot='center' panel silently blanks whichever loses the slot"
    )
