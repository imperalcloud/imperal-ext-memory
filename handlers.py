"""Memory & Index · Chat function handlers — aggregator.

Read tools describe what Webbee holds; write tools change ONLY durable notes.
The code index is never writable here: it is regenerated from the source tree
on the next indexing pass, so an edit would be silently discarded — offering
the control would be a lie.

Every handler is fail-soft: a vault/gateway outage yields a clear "nothing
stored yet" answer or a plain error, never an exception into the chat turn.
A note write that fails is the one exception to "soft": it is reported as an
error, because a lost edit must never look saved.

The implementations live in focused modules (each well under the deploy
validator's 300-line ceiling); this module re-exports them so that importing
``handlers`` still registers every chat function and exposes every name:

  handlers_params   parameter models + shared note helpers
  handlers_reads    list_repos / get_index / list_notes
  handlers_explain  explain_memory
  handlers_writes   add_note / edit_note / delete_note
  handlers_purge    delete_repo — erases everything of one repo, verified
  handlers_everything  memory_overview / forget_memory — the whole memory,
                    and the one verified way to forget any part of it
  handlers_contract_graph  get_cross_repo_contract_graph — endpoints/schemas
                    linked across every indexed repo
"""
from __future__ import annotations

from handlers_params import (  # noqa: F401
    AddNoteParams,
    DeleteNoteParams,
    DeleteRepoParams,
    EditNoteParams,
    EmptyParams,
    ForgetMemoryParams,
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
from handlers_everything import fn_forget_memory, fn_memory_overview  # noqa: F401
from handlers_contract_graph import (  # noqa: F401
    ContractGraphParam,
    fn_get_cross_repo_contract_graph,
)
from handlers_user_mem import (  # noqa: F401
    ListUserFactsParams,
    AddUserFactParams,
    EditUserFactParams,
    DeleteUserFactParams,
    fn_list_user_facts,
    fn_add_user_fact,
    fn_edit_user_fact,
    fn_delete_user_fact,
)
from handlers_recall import (  # noqa: F401
    RecallContextParams,
    fn_recall_context,
)

__all__ = [
    "AddNoteParams", "DeleteNoteParams", "DeleteRepoParams", "EditNoteParams",
    "EmptyParams", "RepoParams", "fn_list_repos", "fn_get_index",
    "fn_list_notes", "fn_explain_memory", "fn_add_note", "fn_edit_note",
    "fn_delete_note", "fn_delete_repo",
    "ForgetMemoryParams", "fn_memory_overview", "fn_forget_memory",
    "ContractGraphParam", "fn_get_cross_repo_contract_graph",
    "ListUserFactsParams", "AddUserFactParams", "EditUserFactParams", "DeleteUserFactParams",
    "fn_list_user_facts", "fn_add_user_fact", "fn_edit_user_fact", "fn_delete_user_fact",
    "RecallContextParams", "fn_recall_context",
]
