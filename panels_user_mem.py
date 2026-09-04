"""Memory & Index · User & Workspace Memory UI views, cards & modals.

Renders:
  - User directives, preferences, workspace conventions, infra facts
  - In-place collapsible addition & editing (no disruptive reloads)
  - Confirmation modal for fact deletion (with token binding)
  - Category filters and contextual search simulation
"""
from __future__ import annotations

import hashlib
from typing import Any

from imperal_sdk import ui

from app import safe_err
from panels_common import _nav
from panels_modals import _back_button, _modal
from storage_user_mem import MAX_FACT_CHARS, MAX_USER_FACTS


def fact_token(text: str) -> str:
    """Short stable fingerprint of a fact's text."""
    return hashlib.sha1(str(text or "").encode("utf-8")).hexdigest()[:8]


def user_memory_card(facts: list[dict], selected_cat: str = "") -> ui.UINode:
    """Card displaying durable user directives and workspace facts with inline controls."""
    cats = ["all", "directive", "preference", "infra", "convention", "identity"]

    filter_buttons = []
    for c in cats:
        val = "" if c == "all" else c
        is_active = (selected_cat == val) or (not selected_cat and c == "all")
        filter_buttons.append(
            ui.Button(
                label=c.capitalize(),
                variant="primary" if is_active else "ghost",
                size="sm",
                on_click=_nav(section="user_memory", cat=val),
            )
        )

    header_row = ui.Stack(
        direction="h",
        gap=1,
        children=[
            ui.Text(content="Categories:"),
            *filter_buttons,
        ],
    )

    children: list[ui.UINode] = [
        ui.Alert(
            type="info",
            message=(
                f"Webbee remembers up to {MAX_USER_FACTS} durable user facts, directives, "
                f"and infrastructure conventions across all surfaces (terminal, panel, Telegram). "
                f"Facts are injected contextually to keep prompts lean."
            ),
        ),
        header_row,
        ui.Section(
            title="+ Teach Webbee a new user fact / directive",
            collapsible=True,
            children=[
                ui.Form(
                    action="add_user_fact",
                    submit_label="Remember Fact",
                    children=[
                        ui.Input(
                            param_name="category",
                            label="Category (directive / preference / infra / convention / identity)",
                            value=selected_cat or "preference",
                        ),
                        ui.TextArea(
                            param_name="fact",
                            label=f"Fact text (max {MAX_FACT_CHARS} chars)",
                            rows=3,
                        ),
                    ],
                ),
            ],
        ),
    ]

    visible = facts
    if selected_cat:
        visible = [f for f in facts if str(f.get("category", "")).lower() == selected_cat.lower()]

    if not visible:
        children.append(
            ui.Empty(
                message=(
                    f"No user facts stored under '{selected_cat}'." if selected_cat
                    else "No user facts or directives stored yet. Add rules, preferences or infra facts above!"
                ),
                icon="BrainCircuit",
            )
        )
    else:
        for idx, f in enumerate(visible, start=1):
            fid = f.get("fact_id", f"fact_{idx}")
            cat = str(f.get("category", "preference")).upper()
            txt = str(f.get("fact", ""))
            tags = f.get("tags") or []
            tags_str = ", ".join(f"#{t}" for t in tags) if tags else ""
            subtitle = f"[{cat}] {tags_str}".strip()
            tok = fact_token(txt)

            children.append(
                ui.Section(
                    title=f"#{idx} · {subtitle}",
                    children=[
                        ui.Text(content=txt),
                        ui.Section(
                            title="✎ Edit fact",
                            collapsible=True,
                            children=[
                                ui.Form(
                                    action="edit_user_fact",
                                    submit_label="Save Changes",
                                    defaults={"fact_id": fid},
                                    children=[
                                        ui.Input(
                                            param_name="category",
                                            label="Category",
                                            value=f.get("category", "preference"),
                                        ),
                                        ui.TextArea(
                                            param_name="fact",
                                            label=f"Fact text (max {MAX_FACT_CHARS} chars)",
                                            value=txt,
                                            rows=3,
                                        ),
                                    ],
                                ),
                            ],
                        ),
                        ui.Stack(
                            direction="h",
                            gap=1,
                            children=[
                                ui.Button(
                                    label="✕ Delete fact",
                                    variant="danger",
                                    size="xs",
                                    on_click=_nav(section="user_memory", cat=selected_cat, delete_fact=fid, token=tok),
                                ),
                            ],
                        ),
                    ],
                )
            )

    return ui.Card(
        title="User & Workspace Memory",
        content=ui.Stack(direction="v", gap=2, children=children),
    )


def add_user_fact_modal(cat: str = "") -> ui.UINode:
    """Modal for adding a new user memory fact."""
    return _modal(
        title="Add user directive or workspace fact",
        size="md",
        confirm_label="Save fact",
        cancel_label="← Cancel",
        on_close=_nav(section="user_memory", cat=cat),
        content=ui.Stack(
            direction="v",
            gap=2,
            children=[
                _back_button("", "← Back to User Memory"),
                ui.Form(
                    action="add_user_fact",
                    submit_label="Save Fact",
                    defaults={"category": cat or "preference"},
                    children=[
                        ui.Select(
                            param_name="category",
                            label="Category",
                            options=[
                                {"value": "directive", "label": "Directive (strict rule)"},
                                {"value": "preference", "label": "Preference (style/workflow)"},
                                {"value": "infra", "label": "Infra (servers, ports, domains)"},
                                {"value": "convention", "label": "Convention (code style, naming)"},
                                {"value": "identity", "label": "Identity (user info, role)"},
                            ],
                            value=cat or "preference",
                        ),
                        ui.TextArea(
                            param_name="fact",
                            label=f"Fact or rule (max {MAX_FACT_CHARS} chars)",
                            placeholder="e.g. Always deploy via deploy runbook and verify health check.",
                            rows=3,
                        ),
                    ],
                ),
            ],
        ),
    )


def delete_user_fact_modal(fact_id: str, fact_text: str, cat: str = "") -> ui.UINode:
    """Strict confirmation modal for deleting a durable user fact."""
    preview = fact_text if len(fact_text) <= 150 else fact_text[:150] + "…"
    return _modal(
        title="Delete user memory fact?",
        destructive=True,
        size="md",
        confirm_label="Delete permanently",
        cancel_label="← Keep it",
        on_confirm=ui.Call("delete_user_fact", fact_id=fact_id),
        on_close=_nav(section="user_memory", cat=cat),
        content=ui.Stack(
            direction="v",
            gap=2,
            children=[
                _back_button("", "← Back to User Memory"),
                ui.Text(content="This fact will be permanently removed from what Webbee remembers about you:"),
                ui.Card(title="Fact content", content=ui.Text(content=preview)),
                ui.Alert(
                    type="warning",
                    message="Once deleted, Webbee will no longer consider this rule or preference in future conversations.",
                ),
            ],
        ),
    )
