"""Memory & Index v1.0.0 · repo index + durable notes — system extension."""
from __future__ import annotations

import sys, os
_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _dir)

# Drop this package's own modules from sys.modules before importing, so a hot
# reimport on the worker picks up the CURRENT release instead of a cached one.
# Matched by prefix, not by a hardcoded name list: the code is split across
# handlers_*.py / panels_*.py, and a fixed list silently goes stale the moment
# a module is added — which would serve the previous release's panels.
_OWN = ("app", "handlers", "models", "panels")
for _m in [k for k in list(sys.modules)
           if k in _OWN or k.startswith(tuple(f"{p}_" for p in _OWN))]:
    del sys.modules[_m]

from app import ext, chat  # noqa: F401
import handlers            # noqa: F401
import panels              # noqa: F401
