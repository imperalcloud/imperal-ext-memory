"""Memory & Index · Panels — see, understand and edit Webbee's repo brain.

Three surfaces:

* ``repos``   (left)   — inventory: every repo Webbee holds memory for.
* ``memory``  (center) — one repo in full: the code index, every durable note
                         with edit/delete controls, and an add-note form.
* ``storage`` (center) — the explainer: which Redis key holds what, who writes
                         it, when it updates, what the caps are — with LIVE
                         numbers from this user's own data, not prose claims.

Write controls exist ONLY for durable notes. The code index is regenerated
from the source tree on the next indexing pass, so an edit control there would
promise something the platform silently discards.

This module is the AGGREGATOR: the panel bodies live in ``panels_*.py`` (the
deploy validator warns above 300 lines per file). Importing this module
imports each part, and the ``@ext.panel`` decorators register all three
panels — so ``import panels`` behaves exactly as it did when this was one
file, and any code doing ``panels.repos_panel`` still resolves.
"""
from __future__ import annotations

from panels_cards import _index_card, _notes_card  # noqa: F401
from panels_common import _empty, _err, _inventory  # noqa: F401
from panels_memory import memory_panel  # noqa: F401
from panels_repos import repos_panel  # noqa: F401
from panels_storage import storage_body, storage_panel  # noqa: F401
from panels_viz import index_charts, index_graph  # noqa: F401

__all__ = ["repos_panel", "memory_panel", "storage_panel", "storage_body",
           "index_graph", "index_charts"]
