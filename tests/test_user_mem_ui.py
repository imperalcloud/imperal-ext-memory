"""Memory & Index · Declarative UI Tests for User & Workspace Memory."""
from __future__ import annotations

import pytest

from panels_memory import memory_panel
from panels_repos import repos_panel
from panels_user_mem import add_user_fact_modal, delete_user_fact_modal, user_memory_card


@pytest.mark.asyncio
async def test_user_memory_panel_views(redis_mock, make_ctx):
    ctx = make_ctx("imp_u_test123")

    # 1. Left repos panel includes User & Workspace Facts button
    left_ui = await repos_panel(ctx)
    assert left_ui is not None

    # 2. Memory panel with section="user_memory"
    center_ui = await memory_panel(ctx, section="user_memory")
    assert center_ui is not None
    assert center_ui.type == "Stack"
    # Should contain back button and card
    assert len(center_ui.props.get("children", [])) >= 2

    # 3. Memory panel with delete modal triggered
    center_del_ui = await memory_panel(ctx, section="user_memory", delete_fact="fact_1", token="")
    assert center_del_ui is not None

    # 4. Standalone card rendering
    sample_facts = [
        {
            "fact_id": "fact_1",
            "category": "directive",
            "fact": "Always deploy via deploy script",
            "tags": ["deploy"],
        }
    ]
    card = user_memory_card(sample_facts, selected_cat="directive")
    assert card is not None
    assert card.type == "Card"

    # 5. Modals standalone
    add_modal = add_user_fact_modal(cat="directive")
    assert add_modal is not None
    del_modal = delete_user_fact_modal("fact_1", "Always deploy via deploy script")
    assert del_modal is not None
