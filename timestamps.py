"""Memory & Index · Timestamp normalisation.

Both Redis stores this extension reads are written by the KERNEL, and
successive generations of the distiller used DIFFERENT timestamp shapes for
the same field:

    imperal:repo_memory:…:0527e446e3fd   distilled_at = '2026-08-13T22:39:53+00:00'
    imperal:repo_memory:…:f20e613c68f0   distilled_at = 1787212894
    …:updated_at                          None

All three are valid, none can be retro-fixed (the kernel owns the writes and
old rows live up to 90 days), so the extension has to cope with the mix.

It did not. Ordering "freshest first" compared a str against an int, Python
raised ``TypeError``, and one account holding both shapes lost the ENTIRE
panel -- code index maps included -- behind "Could not load your repo memory
— try again shortly" (live: admin@imperal.io, 2026-08-20).

Hence this module, deliberately its own file rather than three defensive
patches at the three sort sites: the mixed-shape history is ONE fact about
the data, so it gets ONE place to be handled. Callers just ask for a number.

``app.py`` re-exports both names, so ``from app import age`` keeps working.
"""
from __future__ import annotations

import time
from datetime import datetime


def ts(v) -> float:
    """Any timestamp shape -> comparable epoch seconds. Unknown -> 0.0.

    Never raises. A garbled timestamp is a cosmetic loss (the row sorts
    oldest and reads "unknown"), never a reason to refuse the user's data --
    that trade is the whole point of this module.
    """
    # bool is an int subclass; True would otherwise read as epoch 1.
    if isinstance(v, bool):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v) if v > 0 else 0.0
    if isinstance(v, str) and v.strip():
        s = v.strip()
        try:                                   # epoch stored as a string
            f = float(s)
            return f if f > 0 else 0.0
        except ValueError:
            pass
        try:                                   # ISO-8601, with or without 'Z'
            return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError, OSError):
            return 0.0
    return 0.0


def age(v) -> str:
    """Human staleness. Unknown timestamps say so rather than implying 'now'."""
    t = ts(v)
    if t <= 0:
        return "unknown"
    mins = max(0, int((time.time() - t) // 60))
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins}m ago"
    if mins < 1440:
        return f"{mins // 60}h ago"
    return f"{mins // 1440}d ago"
