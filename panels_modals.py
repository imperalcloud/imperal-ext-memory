"""Memory & Index · Modal windows — overlays, not replacements.

Two bugs are fixed here, and both came from the same wrong assumption.

1. THE MODAL CAME BACK. A modal is rendered from panel state (``confirm=1``,
   ``forget=3``, ``edit=2``). Its cancel button closes the overlay on the
   CLIENT only — the state param survives, so the next render of the panel put
   the very same modal back on screen. ``ui.Call`` cannot chain (it is one
   ``action`` + ``params``, nothing more), so a modal cannot "call the tool and
   then clear the flag". The flag has to stop mattering by itself.

   So every modal here is bound to the CONTENT it is about, via a short token
   of the note's text. After the note is saved (text changed) or forgotten (row
   gone), the token no longer matches anything and the modal simply does not
   render — no stale flag can resurrect it. That also closes a nastier variant:
   deleting note #1 shifts the list up, so a surviving ``forget=1`` used to
   point the confirmation at a DIFFERENT note than the one just deleted.

2. IT RELOADED THE WHOLE SECTION. The old code returned the modal INSTEAD of
   the repo view, so opening Edit blanked everything behind it. ``ui.Modal`` is
   an overlay layered on top of the current panel, so the full view is rendered
   underneath and the modal on top — the content stays put, and the panel only
   changes after a save.
"""
from __future__ import annotations

import hashlib
import inspect

from imperal_sdk import ui

from app import NOTE_CHARS
from panels_common import _nav

_PREVIEW = 300


# ``ui.Dialog`` ON PURPOSE, not ``ui.Modal``.
#
# The panel host runs a NEWER SDK than a dev machine may have. There, Dialog is
# documented as a deprecated alias — but it is a FULL one: it forwards every
# kwarg (on_close, size, subtitle, dismissible) into Modal and deliberately
# keeps emitting ``type="Dialog"`` so older renderers keep drawing it. On an
# older SDK ``ui.Modal`` does not exist at all and Dialog takes only its five
# original arguments, where passing size= or on_close= raises TypeError before
# anything renders.
#
# So Dialog is the one call that behaves on BOTH: it gains on_close where the
# host supports it, emits the same node type either way, and is the wire type
# already proven to render by the extensions live in this host. Betting on
# Modal instead would mean shipping a component whose rendering was never
# verified here — exactly the mistake that made the first graph draw nothing.
_MODAL_FN = ui.Dialog
try:
    _MODAL_PARAMS = set(inspect.signature(_MODAL_FN).parameters)
    _MODAL_VARKW = any(p.kind is inspect.Parameter.VAR_KEYWORD
                       for p in inspect.signature(_MODAL_FN).parameters.values())
except (TypeError, ValueError):  # pragma: no cover - defensive
    _MODAL_PARAMS, _MODAL_VARKW = set(), True


def _modal(**kwargs) -> ui.UINode:
    """Build a modal window using only the kwargs this SDK understands."""
    if not _MODAL_VARKW:
        kwargs = {k: v for k, v in kwargs.items() if k in _MODAL_PARAMS}
    return _MODAL_FN(**kwargs)


def _back_button(repo_key: str, label: str = "← Back") -> ui.UINode:
    """An explicit way out, INSIDE the modal body.

    The footer's cancel button and the ✕ are client-side dismissals, and on an
    older SDK there is no ``on_close`` to pair with them — so the only exit
    that always reaches the server (and therefore always clears the view
    state) is a real button in the content.
    """
    return ui.Button(label=label, variant="ghost", size="sm",
                     on_click=_nav(repo=repo_key))


def note_token(text: str) -> str:
    """Short stable fingerprint of a note's text.

    Not security, just identity: it answers "is this still the same note I was
    asked about?" after a write or a delete has reshuffled the list.
    """
    return hashlib.sha1(str(text or "").encode("utf-8")).hexdigest()[:8]


def _preview(text: str) -> str:
    t = str(text or "")
    return t if len(t) <= _PREVIEW else t[:_PREVIEW] + "…"


def token_matches(entries: list, pos: int, token: str) -> bool:
    """True when ``entries[pos-1]`` is still the note the modal was opened for.

    An absent token means "opened before tokens existed" — treated as a match
    so a stale link degrades into showing the modal, never into acting on the
    wrong note. Position bounds are checked here too, so callers cannot index
    past the end of a list that shrank underneath them.
    """
    if not (1 <= pos <= len(entries)):
        return False
    if not token:
        return True
    return note_token(entries[pos - 1].get("note")) == token


def erase_repo_modal(repo_key: str, label: str, entries: list,
                     idx: dict | None) -> ui.UINode:
    """Strict confirmation for erasing one repo's entire memory."""
    note_line = (f"{len(entries)} durable note{'' if len(entries) == 1 else 's'}"
                 if entries else "no durable notes")
    index_line = (f"the code index ({(idx or {}).get('file_count') or 0} files)"
                  if idx is not None else "no code index")
    return _modal(
        title=f"Erase what Webbee remembers about {label}?",
        destructive=True,
        size="lg",
        confirm_label="Erase permanently",
        cancel_label="← Keep it",
        on_confirm=ui.Call("delete_repo", repo=repo_key),
        # Cancel/✕ must also clear the flag on the SERVER, otherwise the next
        # render of the panel shows this modal again.
        on_close=_nav(repo=repo_key),
        content=ui.Stack(direction="v", gap=2, children=[
            _back_button(repo_key, "← Back to repo"),
            ui.Text(content=(
                f"This erases {index_line} and {note_line} — both storage keys "
                f"for this repository. Afterwards the keyspace is re-scanned to "
                f"confirm nothing is left.")),
            ui.Alert(type="warning", message=(
                "The notes cannot be recovered — they are judgement distilled "
                "over time, not something re-derivable from your files. The "
                "code index DOES come back on its own the next time you open "
                "this repo in the terminal agent.")),
            ui.Text(content=f"Repo key: {repo_key}"),
        ]),
    )


def forget_note_modal(repo_key: str, pos: int, entries: list) -> ui.UINode:
    """Strict confirmation for forgetting ONE note."""
    doomed = str(entries[pos - 1].get("note") or "")
    others = len(entries) - 1
    return _modal(
        title=f"Forget note #{pos}?",
        destructive=True,
        size="lg",
        confirm_label="Forget it",
        cancel_label="← Keep it",
        on_confirm=ui.Call("delete_note", repo=repo_key, position=pos),
        on_close=_nav(repo=repo_key),
        content=ui.Stack(direction="v", gap=2, children=[
            _back_button(repo_key, "← Back to repo"),
            ui.Text(content="This note will be removed from what Webbee knows "
                            "about this repo:"),
            ui.Card(title=f"Note #{pos}",
                    content=ui.Text(content=_preview(doomed))),
            ui.Alert(type="warning", message=(
                "Distilled notes are judgement built up over many coding turns "
                f"— this one cannot be recovered. The other {others} note(s) "
                "for this repo stay untouched." if others else
                "Distilled notes are judgement built up over many coding turns "
                "— this one cannot be recovered, and it is the last note for "
                "this repo.")),
        ]),
    )


def edit_note_modal(repo_key: str, pos: int, entries: list) -> ui.UINode:
    """The editing window: a form pre-filled with the note's current text.

    Not destructive, so it stays dismissible (Esc / backdrop / ✕ all work).
    The form carries its own submit button, hence ``confirm_label=""`` — a
    second confirm button would fire nothing and just look broken.
    """
    text = str(entries[pos - 1].get("note") or "")
    return _modal(
        title=f"Edit note #{pos}",
        subtitle="Saved straight to this repo's memory",
        size="xl",
        confirm_label="",
        cancel_label="← Back",
        on_close=_nav(repo=repo_key),
        content=ui.Stack(direction="v", gap=2, children=[
            _back_button(repo_key, "← Back to repo"),
            ui.Form(
                action="edit_note",
                submit_label="Save this note",
                defaults={"repo": repo_key, "position": pos},
                children=[
                    ui.TextArea(param_name="note", value=text, rows=10,
                                label=f"Note #{pos} (max {NOTE_CHARS} chars)",
                                description="Secrets are stripped automatically "
                                            "before saving.",
                                required=True),
                ],
            ),
            ui.Text(content="Closing without saving leaves the note as it is.",
                    variant="caption"),
        ]),
    )


__all__ = ["note_token", "token_matches", "erase_repo_modal",
           "forget_note_modal", "edit_note_modal"]
