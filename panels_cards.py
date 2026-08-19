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
from panels_modals import note_token

log = logging.getLogger("memory-index")

_RETENTION_DAYS = REPO_MEM_TTL // 86400


def _num(value) -> int:
    """A count from the index, or 0 — never an exception.

    These dicts come straight out of Redis, so one non-numeric value used to
    take the ENTIRE repo view down: sorting by value raised TypeError comparing
    str to int before anything rendered.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _index_card(d: dict) -> ui.Card:
    """The structural map — read-only by design."""
    langs = d.get("languages") or {}
    kinds = d.get("symbol_kinds") or {}
    lang_txt = ", ".join(f"{k} {v}" for k, v in sorted(
        langs.items(), key=lambda kv: _num(kv[1]), reverse=True)) or "—"
    kind_txt = ", ".join(f"{k} {v}" for k, v in sorted(
        kinds.items(), key=lambda kv: _num(kv[1]), reverse=True)) or "—"

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


def _notes_card(repo_key: str, entries: list) -> ui.Card:
    """Durable notes — every one editable in place, deletable with a warning.

    EDITING IS INLINE, NOT A WINDOW. Each note carries its own collapsible
    editor holding the note's current text. ``ui.Section(collapsible=True)``
    opens and closes in the browser, so revealing the field costs no server
    round-trip at all: nothing re-renders, nothing is fetched, the reader's
    place is kept, and other notes stay exactly as they were. Only pressing
    Save submits — the form posts to ``edit_note`` and just that note comes
    back updated.

    This replaces two earlier attempts, and both failures are worth keeping in
    mind. Swapping the note's row for a form re-rendered the whole section on
    every Edit click. Moving the form into a modal stopped the section
    reloading, but a popup is the wrong shape for "make this text editable" —
    and being driven by view state, it could reappear after its own save.
    A client-side disclosure has neither problem.

    Forget stays a modal on purpose: erasing a distilled note is destructive
    and unrecoverable, so it must be confirmed, not toggled. Its button
    carries a ``token`` — the fingerprint of the note's current text — so the
    confirmation is bound to THAT note and cannot re-aim at another one after
    a delete shifts the list.
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

            tok = note_token(text)
            rows.append(ui.Section(title=f"#{idx} · {meta}", children=[
                ui.Text(content=text),
                ui.Text(content=("cites: " + ", ".join(cites)) if cites else "no file cited"),
                # The editor lives here, collapsed. Opening it is a browser
                # toggle — no request, no re-render — and the field already
                # holds this note's current text, so it is editable the moment
                # it appears. Submitting posts to edit_note and refreshes just
                # this note; nothing else on the panel moves.
                ui.Section(title="✎ Edit this note", collapsible=True, children=[
                    ui.Form(
                        action="edit_note",
                        submit_label="Save",
                        defaults={"repo": repo_key, "position": str(idx)},
                        children=[
                            ui.TextArea(
                                param_name="note",
                                value=text,
                                rows=4,
                                label=f"Note #{idx} (max {NOTE_CHARS} chars)"),
                        ],
                    ),
                ]),
                ui.Stack(direction="h", gap=1, children=[
                    # Forget only re-renders this panel with a param — the
                    # strict confirmation. It never deletes on first click.
                    ui.Button(label="Forget", variant="danger", icon="Trash2",
                              on_click=_nav(repo=repo_key, forget=str(idx),
                                            token=tok)),
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
