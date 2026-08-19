"""Memory & Index · Write-safety pipeline — mirrors imperal_kernel/core/repo_memory.py.

A note stored here is re-injected into the coding brain's prompt on later
turns, for up to 90 days. Without these two transforms a panel edit would be
a stored prompt-injection vector with a long shelf life, so they are NOT
optional and NOT cosmetic.

Kept in its own module (rather than inside ``app.py``) for two reasons: the
deploy validator warns above 300 lines, and this logic is genuinely separate
from storage — it depends on nothing else in the package, which is why the
character limit arrives as an argument instead of being imported from
``app``. That direction of dependency is deliberate: ``app`` owns the kernel
storage contract, and importing it back from here would be a cycle.
"""
from __future__ import annotations

import re

_SECRET_URI_USERINFO_RE = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s:@/]+:[^\s@/]+@")
_SECRET_KEYWORD_RE = re.compile(
    r"""(?i)(api[_-]?key|secret|token|password|passwd|authorization|bearer)["']?\s*[:=]\s*["']?[^\s"']+""")
_SECRET_BEARER_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{10,}")
_SECRET_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_SECRET_PREFIXED_KEY_RE = re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{10,}")
_SECRET_GCP_KEY_RE = re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")
_SECRET_RE = re.compile(
    r"AKIA[0-9A-Z]{16}|-----BEGIN[ A-Z]+PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}|sk-[A-Za-z0-9]{20,}")

_FENCE_OPEN_RE = re.compile(r"<{3,}")
_FENCE_CLOSE_RE = re.compile(r">{3,}")


def scrub_secrets(text: str) -> str:
    """Redact common secret/token shapes before persisting a note."""
    s = str(text or "")
    s = _SECRET_URI_USERINFO_RE.sub("[REDACTED]@", s)
    s = _SECRET_BEARER_RE.sub("[REDACTED]", s)
    s = _SECRET_KEYWORD_RE.sub("[REDACTED]", s)
    s = _SECRET_JWT_RE.sub("[REDACTED]", s)
    s = _SECRET_PREFIXED_KEY_RE.sub("[REDACTED]", s)
    s = _SECRET_GCP_KEY_RE.sub("[REDACTED]", s)
    s = _SECRET_RE.sub("[REDACTED]", s)
    return s


def neutralize_fence(text) -> str:
    """Neutralize ``<<< >>>`` DATA-fence delimiters in stored text.

    The coding brain renders stored notes inside a ``<<< >>>`` DATA fence. A
    note containing a newline + ``>>>`` would close that fence early and let
    the remainder render as a top-level directive to a tool-wielding agent.
    Newlines collapse to spaces FIRST so no content can forge a standalone
    delimiter line.
    """
    s = str(text or "")
    s = s.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ")
    s = _FENCE_OPEN_RE.sub("\u2039\u2039\u2039", s)
    s = _FENCE_CLOSE_RE.sub("\u203a\u203a\u203a", s)
    return s


def sanitize_note(text: str, limit: int) -> str:
    """Full write pipeline for one note: scrub -> defuse -> clamp."""
    return neutralize_fence(scrub_secrets(text)).strip()[:limit]
