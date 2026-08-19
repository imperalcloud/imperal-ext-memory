"""Memory & Index · Panels — see, understand and edit Webbee's repo brain.

Three surfaces:

* ``repos``  (left)   — inventory: every repo Webbee holds memory for.
* ``memory`` (center) — the ONE center surface, switched by ``section=``:
                        a repo in full (code index, graph, durable notes with
                        edit/forget controls, add-note form), or the storage
                        explainer at ``section=storage``.

Exactly one panel may own the center slot: two ``slot="center"`` panels compete
for it and the one registered FIRST wins, silently blanking the other. This
extension shipped that bug twice in a row (see panels_storage.py), so the
explainer is a function rendered inside ``memory``, never its own panel.

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
from panels_storage import storage_body  # noqa: F401
from panels_viz import index_charts, index_graph  # noqa: F401

__all__ = ["repos_panel", "memory_panel", "storage_body",
           "index_graph", "index_charts"]
