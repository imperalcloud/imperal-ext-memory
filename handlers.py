"""Memory & Index · Chat function handlers — aggregator.

Read tools describe what Webbee holds; write tools change ONLY durable notes.
The code index is never writable here: it is regenerated from the source tree
on the next indexing pass, so an edit would be silently discarded — offering
the control would be a lie.

Every handler is fail-soft: a Redis outage yields a clear "nothing stored yet"
answer or a plain error, never an exception into the chat turn.

The implementations live in four focused modules (each well under the deploy
validator's 300-line ceiling); this module re-exports them so that importing
``handlers`` still registers every chat function and exposes every name:

  handlers_params   parameter models + shared note helpers
  handlers_reads    list_repos / get_index / list_notes
  handlers_explain  explain_memory
  handlers_writes   add_note / edit_note / delete_note
  handlers_purge    delete_repo — erases one repo's memory entirely
"""
from __future__ import annotations

from handlers_params import (  # noqa: F401
    AddNoteParams,
    DeleteNoteParams,
    DeleteRepoParams,
    EditNoteParams,
    EmptyParams,
    RepoParams,
    _entry_written,
    _notes_payload,
    _resolve_notes,
)
from handlers_reads import (  # noqa: F401
    fn_get_index,
    fn_list_notes,
    fn_list_repos,
)
from handlers_explain import fn_explain_memory  # noqa: F401
from handlers_writes import (  # noqa: F401
    fn_add_note,
    fn_delete_note,
    fn_edit_note,
)
from handlers_purge import fn_delete_repo  # noqa: F401

__all__ = [
    "AddNoteParams", "DeleteNoteParams", "DeleteRepoParams", "EditNoteParams",
    "EmptyParams", "RepoParams", "fn_list_repos", "fn_get_index",
    "fn_list_notes", "fn_explain_memory", "fn_add_note", "fn_edit_note",
    "fn_delete_note", "fn_delete_repo",
]
