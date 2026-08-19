"""Memory & Index · Index + notes cards for the memory panel.

Split out of ``panels.py`` (the deploy validator warns above 300 lines).
Panels register via the ``@ext.panel`` decorator at import time, so
``panels.py`` imports every part — importing it registers all three panels
exactly as before.
"""
from __future__ import annotations

import logging

from imperal_sdk import ui

from app import MAX_ENTRIES, NOTE_CHARS, REPO_MEM_TTL, age, repo_name
from panels_common import _nav

log = logging.getLogger("memory-index")

_RETENTION_DAYS = REPO_MEM_TTL // 86400


def _index_card(d: dict) -> ui.Card:
    """The structural map — read-only by design."""
    langs = d.get("languages") or {}
    kinds = d.get("symbol_kinds") or {}
    lang_txt = ", ".join(f"{k} {v}" for k, v in sorted(
        langs.items(), key=lambda kv: kv[1], reverse=True)) or "—"
    kind_txt = ", ".join(f"{k} {v}" for k, v in sorted(
        kinds.items(), key=lambda kv: kv[1], reverse=True)) or "—"

    rows = [
        {"key": "Path on disk", "value": d.get("repo_root") or "—"},
        {"key": "Repo key", "value": d.get("_repo_key") or "—"},
        {"key": "Indexed at commit", "value": (d.get("git_ref") or "—")[:12]},
        {"key": "Branch", "value": d.get("branch") or "—"},
        {"key": "Files", "value": str(d.get("file_count") or 0)},
        {"key": "Languages", "value": lang_txt},
        {"key": "Symbols", "value": kind_txt},
        {"key": "Semantic chunks", "value": str(d.get("embedded_chunks") or 0)},
        {"key": "Semantic search", "value": "ready" if d.get("vectors_ready") else "not ready"},
        {"key": "Endpoints / schemas",
         "value": f"{d.get('endpoint_count') or 0} / {d.get('schema_count') or 0}"},
        {"key": "Last rebuilt", "value": age(d.get("updated_at"))},
    ]

    content = [
        ui.Alert(type="info", message=(
            "Read-only: this map is rebuilt from your source tree every time the "
            "terminal agent indexes the repo, so any manual edit would be discarded.")),
        ui.KeyValue(items=rows),
    ]

    tops = [str(s) for s in (d.get("top_symbols") or [])][:20]
    if tops:
        content.append(ui.Section(title="Key symbols", children=[
            ui.List(items=[ui.ListItem(id=f"sym-{i}", title=s) for i, s in enumerate(tops)]),
        ]))

    return ui.Card(title="Code index", content=ui.Stack(direction="v", gap=2, children=content))


def _notes_card(repo_key: str, entries: list, editing: int = 0) -> ui.Card:
    """Durable notes — every one editable and deletable by its owner.

    ``editing`` is the 1-based position currently being edited: that note
    renders as a form pre-filled with its own text instead of a read-only
    block. The Edit button used to call ``edit_note`` directly with the text
    it already had, which dutifully saved the note unchanged and reported
    "was: X now: X" — a no-op that looked like a broken button. A write tool
    cannot prompt for input, so the panel has to supply the field first.
    """
    children = [
        ui.Alert(type="info", message=(
            f"Editable. Notes are distilled at the end of a coding turn, kept for "
            f"{_RETENTION_DAYS} days (refreshed on every write), and capped at the "
            f"{MAX_ENTRIES} newest per repo.")),
    ]

    if not entries:
        children.append(ui.Empty(
            message=("No notes for this repo yet — they appear automatically as "
                     "Webbee works in this repository."),
            icon="BrainCircuit"))
    else:
        rows = []
        for idx, e in enumerate(entries, start=1):
            if not isinstance(e, dict):
                continue
            text = str(e.get("note") or "")
            cites = [str(c) for c in (e.get("citations") or [])]
            written = age(e.get("edited_at") or e.get("distilled_at"))
            origin = "you edited" if e.get("edited_at") else "distilled"
            ref = str(e.get("distilled_git_ref") or "")[:12]
            meta = f"{origin} {written}" + (f" @ {ref}" if ref else "")

            if idx == editing:
                # value= pre-fills the textarea with the CURRENT text, so the
                # user edits the real note instead of retyping it from scratch.
                rows.append(ui.Section(title=f"#{idx} · editing", children=[
                    ui.Form(
                        action="edit_note",
                        submit_label="Save this note",
                        defaults={"repo": repo_key, "position": idx},
                        children=[
                            ui.TextArea(param_name="note", value=text, rows=6,
                                        label=f"Note #{idx} (max {NOTE_CHARS} chars)",
                                        description="Secrets are stripped automatically "
                                                    "before saving.",
                                        required=True),
                        ],
                    ),
                    ui.Button(label="Cancel", variant="ghost", size="sm",
                              on_click=_nav(repo=repo_key)),
                ]))
                continue

            rows.append(ui.Section(title=f"#{idx} · {meta}", children=[
                ui.Text(content=text),
                ui.Text(content=("cites: " + ", ".join(cites)) if cites else "no file cited"),
                ui.Stack(direction="h", gap=1, children=[
                    # Both controls re-render THIS panel with a parameter —
                    # edit opens the form, forget opens a confirmation modal.
                    # Neither mutates anything on the first click.
                    ui.Button(label="Edit", variant="secondary", icon="Pencil",
                              on_click=_nav(repo=repo_key, edit=str(idx))),
                    ui.Button(label="Forget", variant="danger", icon="Trash2",
                              on_click=_nav(repo=repo_key, forget=str(idx))),
                ]),
            ]))
        children.append(ui.Stack(direction="v", gap=2, children=rows))

    children.append(ui.Section(title="Teach Webbee something", children=[
        ui.Form(
            action="add_note",
            submit_label="Remember this",
            defaults={"repo": repo_key},
            children=[
                ui.TextArea(param_name="note", rows=3,
                            label=f"Fact about this repo (max {NOTE_CHARS} chars)",
                            placeholder="e.g. deploys go through deploy.sh, never edit current/"),
            ],
        ),
    ]))

    return ui.Card(title=f"Durable notes ({len(entries)})",
                   content=ui.Stack(direction="v", gap=2, children=children))
