"""Tests for navigation payloads — no view state may survive a click.

Split out of ``test_panels.py``: the deploy validator counts every python file
and warns above 300 lines, and this is its own concern anyway — the other
panel tests ask "does this button render the right thing", these ask "does a
click describe the WHOLE view".

The regression being pinned: the explainer button set ``section=storage`` and
repo clicks carried only ``repo=...``, so a host that merges params onto the
panel's current state kept the stale section — the explainer stayed on screen
and no repo would open, whichever one was clicked. Every navigation therefore
goes through ``panels_common._nav``, which sends every state key on every
click, blanking the ones the caller did not name.
"""
import pytest

import panels


def tree(node) -> str:
    """The rendered panel tree as text, for asserting on wiring."""
    return repr(node)


# ── 5. View state must never stick between clicks ─────────────────────

@pytest.mark.asyncio
async def test_every_nav_action_is_self_describing(redis_mock, make_ctx,
                                                   seed_index, seed_memory):
    """Each click must send the WHOLE view state, not a delta.

    The regression this pins: the explainer button set section=storage, and a
    later repo click carried only repo=..., so a host that merges params onto
    the panel's current state kept section=storage — the explainer stayed on
    screen and no repo would open, no matter which one was clicked.

    Asserting on the payload (rather than on one rendered view) is what makes
    this durable: a future param added to the panel but forgotten in _nav
    fails here instead of silently sticking in production.
    """
    seed_index("imp_u_TEST", "abc123")
    seed_memory("imp_u_TEST", "abc123", notes=["a note"])

    surfaces = [
        tree(await panels.repos_panel(make_ctx("imp_u_TEST"))),
        tree(await panels.memory_panel(make_ctx("imp_u_TEST"), repo="abc123")),
        tree(await panels.memory_panel(make_ctx("imp_u_TEST"), repo="abc123", forget="1")),
        tree(await panels.memory_panel(make_ctx("imp_u_TEST"), section="storage")),
    ]
    # Every state key the panel reads must appear in the rendered actions, so
    # no click can leave a previous value in place. "edit" is NOT among them:
    # editing is an inline disclosure handled by the browser, so it never
    # travels as view state at all.
    for name, out in zip(("inventory", "repo", "forget", "storage"), surfaces):
        if "__panel__memory" not in out:
            continue
        for key in ("repo", "section", "forget", "confirm"):
            assert f"'{key}'" in out, f"{name} surface omits {key} from its nav payload"


@pytest.mark.asyncio
async def test_repo_click_clears_a_stuck_explainer(redis_mock, make_ctx, seed_index):
    """Opening a repo while the explainer is showing must show the REPO."""
    seed_index("imp_u_TEST", "abc123")

    inventory = tree(await panels.repos_panel(make_ctx("imp_u_TEST")))
    assert "'section': ''" in inventory        # repo rows blank it
    assert "'section': 'storage'" in inventory  # the explainer button sets it

    # A merging host would union the stale section with the new repo param.
    merged = tree(await panels.memory_panel(make_ctx("imp_u_TEST"),
                                            repo="abc123", section=""))
    assert "Where your repo memory lives" not in merged
    assert "Code index" in merged


def test_nav_blanks_every_state_key_but_can_omit_one():
    """_nav is the single place navigation payloads are built — pin it directly.

    Two properties matter: unnamed keys are sent BLANK (that is what stops a
    stale section/edit/forget from surviving a click), and _omit drops a key
    entirely for the one owner that supplies its own — ui.Graph injects the
    clicked node's id as node_id.
    """
    from panels_common import _VIEW_STATE, _nav

    params = _nav(repo="abc123").params["params"]
    assert set(params) == set(_VIEW_STATE)
    assert params["repo"] == "abc123"
    assert all(params[k] == "" for k in _VIEW_STATE if k != "repo")

    omitted = _nav(_omit=("node_id",), repo="abc123").params["params"]
    assert "node_id" not in omitted

    with pytest.raises(ValueError):   # a typo must fail loudly, not vanish
        _nav(repoo="abc123")


@pytest.mark.asyncio
async def test_graph_click_does_not_blank_its_own_node_id(redis_mock, make_ctx,
                                                          seed_index):
    """ui.Graph injects node_id, so ITS action must not pin node_id to ''.

    Scoped to the graph's own on_node_click payload on purpose: every OTHER
    action in the tree does blank node_id, and rightly so — asserting against
    the whole tree would just re-test those.
    """
    seed_index("imp_u_TEST", "abc123",
               top_symbols=["main (function) @ probe.py:48",
                            "build (function) @ tool.py:12"])

    out = tree(await panels.memory_panel(make_ctx("imp_u_TEST"), repo="abc123"))

    assert "type='Graph'" in out
    at = out.index("on_node_click")
    payload = out[at:at + 260]          # the click action, not the whole panel
    assert "'repo': 'abc123'" in payload
    assert "'node_id'" not in payload
