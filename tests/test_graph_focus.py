"""Memory & Index · clicking a circle must MEAN something.

The reported bug: clicking any element inside the graph just showed the same
graph again, so there was no way to tell what had been selected or why. The
cause was a resolver that understood file ids (``f3``) and nothing else, while
the graph drew five other kinds of circle — repo core, languages, symbol kinds,
directories, symbols. Every one of those clicks resolved to nothing and the
panel rebuilt an identical view.

The first test here is the one that matters long-term: it walks EVERY node id
of a really-built graph and demands the resolver explain it. A future tier
added to the graph without a matching branch in panels_focus cannot pass it,
which is exactly the drift that caused the bug.
"""
from __future__ import annotations

import pytest

import panels
from panels_focus import resolve_node


# Declared here rather than imported from test_graph_render: conftest puts the
# extension root on sys.path, not the tests directory, so test modules cannot
# import each other. Self-contained is the right shape for a test anyway.
def flat(node, out=None):
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


def _graph_of(node):
    for n in flat(node):
        if getattr(n, "type", "") == "Graph":
            return n
    return None


def _rich_index(seed_index):
    """A repo with several languages, kinds, directories and files at once.

    Every graph tier has to be present, or the walk below would silently prove
    only the tiers the fixture happens to draw.
    """
    seed_index("imp_u_TEST", "abc123",
               file_count=3110,
               languages={"python": 1429, "typescript": 6, "javascript": 2},
               symbol_kinds={"function": 10081, "class": 2420},
               top_symbols=[
                   "build_audit (function) @ imperal-ext-admin/panels_audit.py:148",
                   "_action_color (function) @ imperal-ext-admin/panels_audit.py:92",
                   "CompareRolesResponse (class) @ imperal-ext-admin/models_rbac.py:103",
                   "main (function) @ probe_stream_terminals.py:17",
               ])


def _cards(node):
    return [n for n in flat(node) if getattr(n, "type", "") == "Card"]


def _titles(node):
    return [str((getattr(n, "props", None) or {}).get("title") or "")
            for n in _cards(node)]


@pytest.mark.asyncio
async def test_every_node_the_graph_draws_can_be_explained(
        redis_mock, make_ctx, seed_index, store):
    """No circle may be a dead end — the bug was five kinds that were.

    Walks the actual nodes of the actual graph, including the symbol circles
    that only appear once a file is focused, and requires a real title and
    real rows for each.
    """
    _rich_index(seed_index)
    ctx = make_ctx("imp_u_TEST")

    view = await panels.memory_panel(ctx, repo="abc123")
    graph = _graph_of(view)
    assert graph is not None

    import json

    from app import INDEX_PREFIX
    idx = json.loads(store[f"{INDEX_PREFIX}imp_u_TEST:abc123"])

    ids = [n["id"] for n in graph.props["nodes"]]
    assert "repo" in ids, "the core circle must exist to be clickable"

    # Focus a file so the symbol tier is drawn, then include those ids too.
    first_file = next(i for i in ids if i.startswith("f") and i[1:].isdigit())
    focused = _graph_of(await panels.memory_panel(
        ctx, repo="abc123", node_id=first_file))
    ids += [n["id"] for n in focused.props["nodes"] if n["id"] not in ids]

    unexplained = []
    for nid in ids:
        info = resolve_node(idx, nid)
        if not info or not info.get("title") or not info.get("rows"):
            unexplained.append(nid)
    assert not unexplained, (
        "circles a user can click that explain nothing — the original bug: "
        f"{unexplained}")

    # Every id kind the graph emits must be represented, or this test is only
    # proving the tiers that happen to be present in the fixture.
    kinds = {resolve_node(idx, nid)["kind"] for nid in ids}
    assert {"repo", "language", "kind", "file", "symbol"} <= kinds, kinds


@pytest.mark.asyncio
async def test_clicking_a_language_answers_in_words_not_another_graph(
        redis_mock, make_ctx, seed_index):
    """A language click must produce a titled card, not a silent redraw."""
    _rich_index(seed_index)
    ctx = make_ctx("imp_u_TEST")

    before = _titles(await panels.memory_panel(ctx, repo="abc123"))
    after = await panels.memory_panel(ctx, repo="abc123", node_id="L0")

    titles = _titles(after)
    new = [t for t in titles if t not in before]
    assert new, f"a click added no card at all: {titles}"
    assert any("python" in t.lower() for t in new), new

    # And the graph is still there: the card explains, it does not replace.
    assert _graph_of(after) is not None


@pytest.mark.asyncio
async def test_only_files_and_symbols_expand_the_graph(
        redis_mock, make_ctx, seed_index, store):
    """`focus` drives expansion, so non-file circles must not claim one.

    A language or kind circle has no single path to expand; if it returned one
    the graph would sprout symbols under an unrelated file.
    """
    _rich_index(seed_index)
    import json

    from app import INDEX_PREFIX
    idx = json.loads(store[f"{INDEX_PREFIX}imp_u_TEST:abc123"])

    for nid in ("repo", "L0", "K0"):
        assert resolve_node(idx, nid).get("focus") == "", nid
    assert resolve_node(idx, "f0").get("focus"), "a file click must expand"


@pytest.mark.asyncio
async def test_every_clicked_view_offers_a_back_step(
        redis_mock, make_ctx, seed_index):
    """The card carries its own ← back, per the standing rule for every view."""
    _rich_index(seed_index)
    out = await panels.memory_panel(
        make_ctx("imp_u_TEST"), repo="abc123", node_id="K0")

    backs = [n for n in flat(out)
             if getattr(n, "type", "") == "Button"
             and "←" in str((getattr(n, "props", None) or {}).get("label") or "")]
    assert len(backs) >= 2, (
        "expected both the repo-level back and the selection-level back, "
        f"found {[(getattr(b, 'props', {}) or {}).get('label') for b in backs]}")


@pytest.mark.asyncio
async def test_a_meaningless_node_id_is_ignored_not_guessed(
        redis_mock, make_ctx, seed_index, store):
    """Out-of-range and junk ids resolve to nothing, and the view stays whole."""
    _rich_index(seed_index)
    import json

    from app import INDEX_PREFIX
    idx = json.loads(store[f"{INDEX_PREFIX}imp_u_TEST:abc123"])

    for nid in ("", None, "L99", "f99", "d99", "K99", "f0s99", "nonsense"):
        assert resolve_node(idx, nid) == {}, nid

    out = await panels.memory_panel(
        make_ctx("imp_u_TEST"), repo="abc123", node_id="L99")
    assert _graph_of(out) is not None, "a junk id must not break the view"
