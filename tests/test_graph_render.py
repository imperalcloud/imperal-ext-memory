"""Memory & Index · the graph must actually RENDER, not merely be well-formed.

Split out of test_modals_and_back.py to stay under the 300-line ceiling the
deploy validator enforces.

Every assertion here encodes a difference against the one graph already proven
to render in this host: node values inside the mapData domain, and a Section
rather than a Card as the wrapper.
"""
from __future__ import annotations

import pytest

import panels


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


@pytest.mark.asyncio
async def test_every_node_size_stays_inside_the_declared_domain(
        redis_mock, make_ctx, seed_index):
    """Node sizes must lie within min_node_size..max_node_size.

    Cytoscape sizes nodes via mapData(size, min, max). A value outside that
    domain is EXTRAPOLATED, not clamped, so one oversized node is enough to
    give the graph degenerate geometry and leave it never painting — a blank
    frame, and an image export with no canvas to export. The repo node used to
    be 100 against a ceiling of 68, which is exactly that bug.
    """
    seed_index("imp_u_TEST", "abc123",
               file_count=3110,
               languages={"python": 1429, "typescript": 6, "javascript": 2},
               symbol_kinds={"function": 10081, "class": 2420},
               top_symbols=[
                   "build_audit (function) @ imperal-ext-admin/panels_audit.py:148",
                   "_action_color (function) @ imperal-ext-admin/panels_audit.py:92",
                   "main (function) @ probe_stream_terminals.py:17",
               ])

    g = _graph_of(await panels.memory_panel(make_ctx("imp_u_TEST"), repo="abc123"))
    assert g is not None, "the repo view must carry a graph"

    lo = g.props["min_node_size"]
    hi = g.props["max_node_size"]
    bad = [(n["id"], n["size"]) for n in g.props["nodes"]
           if not lo <= n["size"] <= hi]
    assert not bad, f"node sizes outside mapData domain {lo}..{hi}: {bad}"


@pytest.mark.asyncio
async def test_graph_is_not_wrapped_in_a_card(redis_mock, make_ctx, seed_index):
    """The graph sits in a Section, like the one graph proven to render here.

    A Card lays its content out through its own wrapper, and a canvas that has
    to measure itself is precisely what suffers from that. The Chart in this
    same panel — which does render — is inside a Section too.
    """
    seed_index("imp_u_TEST", "abc123",
               top_symbols=["main (function) @ probe_stream_terminals.py:17"])

    out = await panels.memory_panel(make_ctx("imp_u_TEST"), repo="abc123")

    # walk down to the Graph, recording its ancestors
    def trail(node, acc=None):
        acc = (acc or []) + [getattr(node, "type", "?")]
        if getattr(node, "type", "") == "Graph":
            return acc
        p = getattr(node, "props", None) or {}
        for c in (p.get("children") or []):
            r = trail(c, acc)
            if r:
                return r
        if p.get("content") is not None:
            return trail(p["content"], acc)
        return None

    chain = trail(out) or []
    assert "Graph" in chain, "no graph rendered"
    assert "Card" not in chain, f"graph is wrapped in a Card: {' > '.join(chain)}"
    assert "Section" in chain, f"graph should sit in a Section: {' > '.join(chain)}"


# The platform states the Graph component's contract as an exact set of props.
# Anything else is undefined behaviour for the renderer, and the deploy check
# cannot catch it: that check reads the arguments of ui.* CALLS, so a prop
# assigned onto .props afterwards is invisible to it. Hence this test.
_GRAPH_CONTRACT = {
    "nodes", "edges", "layout", "height", "min_node_size", "max_node_size",
    "edge_label_visible", "color_by", "on_node_click",
}


@pytest.mark.asyncio
async def test_graph_passes_only_props_the_platform_defines(
        redis_mock, make_ctx, seed_index):
    """No undocumented prop may reach the renderer.

    A previous version injected graph.props["animate"] = False by hand, copied
    from another extension. It passed validation and shipped the frontend a
    prop the platform never promised to understand.
    """
    seed_index("imp_u_TEST", "abc123",
               languages={"python": 1429},
               symbol_kinds={"function": 10081},
               top_symbols=["build_audit (function) @ imperal-ext-admin/panels_audit.py:148"])

    g = _graph_of(await panels.memory_panel(make_ctx("imp_u_TEST"), repo="abc123"))
    assert g is not None

    extra = set(g.props) - _GRAPH_CONTRACT
    assert not extra, f"undocumented Graph prop(s) sent to the renderer: {sorted(extra)}"


@pytest.mark.asyncio
async def test_graph_layout_is_one_the_component_supports(
        redis_mock, make_ctx, seed_index):
    """layout must be one of the five Cytoscape algorithms the SDK lists."""
    seed_index("imp_u_TEST", "abc123",
               top_symbols=["main (function) @ probe_stream_terminals.py:17"])

    g = _graph_of(await panels.memory_panel(make_ctx("imp_u_TEST"), repo="abc123"))
    assert g.props["layout"] in {
        "cose-bilkent", "circle", "grid", "breadthfirst", "concentric"}
