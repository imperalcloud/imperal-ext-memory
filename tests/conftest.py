"""Test harness for imperal-ext-memory.

The extension talks ONLY to the gateway's owner-scoped ``/v1/memory`` (through
``memory_client.memory_api(ctx)``, i.e. ``ctx._gw_namespace``), so tests hand
every ctx a fake MemoryClient backed by an in-memory gateway that implements
the route contract — one vault file per (user, repo_key) holding the code
index and the notes together, a version bumped on every write, 409 on a stale
``if_version`` and facts upserted by ``fact_id``. The whole memory
(``/v1/memory/all``) and its one forget door (``/v1/memory/forget``) are
modelled too: a repo file shows as the place ``repo:<key>``, the facts as the
account's rules, and ``places[uid][place]`` adds every other section (working
memory, conversations, graph, …) — a place there with no repo file is an
orphan. No network, no third-party mocking library.
"""
import os
import sys
from types import SimpleNamespace

import pytest

# Make the ext modules importable (they use bare `import app`, `from app import …`).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from imperal_sdk.errors import APIError  # noqa: E402


class FakeGateway:
    """The vault behind ``/v1/memory``, as the gateway exposes it.

    ``files[uid][repo_key]`` is one repo's vault file:
    ``{"index": dict | None, "entries": list, "version": int}``.
    ``calls`` records ``(uid, method, repo_key)`` so tests can assert what was
    (and was not) asked for.
    """

    def __init__(self):
        self.files: dict[str, dict[str, dict]] = {}
        self.facts: dict[str, list[dict]] = {}
        self.calls: list[tuple[str, str, str]] = []
        # places[uid][place] = {"counts": {...}, "conversations": [...],
        # "skeleton": [...], plus title/root/... for a repo place}
        self.places: dict[str, dict[str, dict]] = {}
        # places a forget claims to remove but leaves behind (→ 409)
        self.stubborn: set[str] = set()

    def file(self, uid: str, repo_key: str) -> dict:
        return self.files.setdefault(uid, {}).setdefault(
            repo_key, {"index": None, "entries": [], "version": 0})


class FakeMemoryClient:
    """MemoryClient's surface, acting for ONE user — no route takes a user_id."""

    def __init__(self, gw: FakeGateway, uid: str):
        self._gw = gw
        self._uid = uid

    def _mine(self) -> dict:
        return self._gw.files.setdefault(self._uid, {})

    def _log(self, method: str, repo_key: str = ""):
        self._gw.calls.append((self._uid, method, repo_key))

    async def repos(self) -> dict:
        self._log("repos")
        return {"repos": [{"repo_key": k, "index": f["index"], "notes": len(f["entries"])}
                          for k, f in self._mine().items()]}

    async def repo(self, repo_key: str) -> dict:
        self._log("repo", repo_key)
        f = self._mine().get(repo_key) or {"entries": [], "version": 0}
        return {"repo_key": repo_key, "entries": [dict(e) for e in f["entries"]],
                "version": f["version"]}

    async def save_repo(self, repo_key: str, entries: list, if_version=None) -> dict:
        self._log("save_repo", repo_key)
        f = self._gw.file(self._uid, repo_key)
        if if_version is not None and if_version != f["version"]:
            raise APIError("version conflict", 409)
        f["entries"] = [dict(e) for e in entries]
        f["version"] += 1
        return {"ok": True, "count": len(entries)}

    async def delete_repo(self, repo_key: str) -> dict:
        self._log("delete_repo", repo_key)
        place = f"repo:{repo_key}"
        before = self._place_counts().get(place, {})
        if place in self._gw.stubborn:
            raise APIError(str({"error": "not everything was forgotten", "left": before}), 409)
        deleted = self._mine().pop(repo_key, None) is not None
        deleted = self._gw.places.get(self._uid, {}).pop(place, None) is not None or deleted
        return {"repo_key": repo_key, "deleted": deleted, "ok": True,
                "forgotten": before, "left": {}}

    # ── the whole memory ────────────────────────────────────────────────
    def _place_counts(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for k, f in self._mine().items():
            c = out.setdefault(f"repo:{k}", {})
            if f["entries"]:
                c["repos.notes"] = len(f["entries"])
            if f["index"]:
                c["repos.code_index"] = 1
        facts = self._gw.facts.get(self._uid, [])
        if facts:
            out.setdefault("account", {})["law.law"] = len(facts)
        for place, extra in self._gw.places.get(self._uid, {}).items():
            c = out.setdefault(place, {})
            for k, v in (extra.get("counts") or {}).items():
                c[k] = c.get(k, 0) + v
            convs = len(extra.get("conversations") or [])
            if convs:
                c["conversation.conversations"] = convs
        return {p: {k: v for k, v in c.items() if v} for p, c in out.items()}

    async def everything(self) -> dict:
        self._log("everything")
        rows = []
        for place, counts in self._place_counts().items():
            extra = self._gw.places.get(self._uid, {}).get(place, {})
            row = {"place": place, "counts": counts, "total": sum(counts.values()),
                   "conversations": [dict(c) for c in extra.get("conversations") or []]}
            if place == "account":
                row["skeleton"] = [dict(s) for s in extra.get("skeleton") or []]
            else:
                key = place.split(":", 1)[1]
                f = self._mine().get(key)
                row.update({k: extra[k] for k in ("title", "root", "remote", "machine", "branch")
                            if k in extra})
                row["repo_key"] = key
                row["indexed_repo"] = f is not None
                if f and f.get("index") and "root" not in row:
                    row["root"] = f["index"].get("repo_root") or ""
            if row["total"] or row["conversations"]:
                rows.append(row)
        return {"places": rows, "total": sum(r["total"] for r in rows)}

    async def forget(self, what: str, key: str = "", project_id: str = "") -> dict:
        self._log("forget", f"{what}:{key}")
        counts = self._place_counts()
        mine_places = self._gw.places.setdefault(self._uid, {})
        touched = list(counts) if what == "all" else [key] if what == "place" else []
        stuck = [p for p in touched if p in self._gw.stubborn and p in counts]
        if stuck:   # the door names what it could not take, deletes nothing here
            left = {k: v for p in stuck for k, v in counts[p].items()}
            raise APIError(str({"error": "not everything was forgotten", "left": left}), 409)
        forgotten: dict = {}
        if what == "all":
            for c in counts.values():
                for k, v in c.items():
                    forgotten[k] = forgotten.get(k, 0) + v
            self._mine().clear()
            mine_places.clear()
            self._gw.facts[self._uid] = []
        elif what == "place":
            forgotten = dict(counts.get(key, {}))
            if key == "account":
                self._gw.facts[self._uid] = []
            else:
                self._mine().pop(key.split(":", 1)[-1], None)
            mine_places.pop(key, None)
        elif what == "conversation":
            for extra in mine_places.values():
                keep = [c for c in extra.get("conversations") or [] if c.get("id") != key]
                if len(keep) != len(extra.get("conversations") or []):
                    extra["conversations"] = keep
                    forgotten = {"conversation.conversations": 1}
        elif what == "skeleton":
            for extra in mine_places.values():
                keep = [s for s in extra.get("skeleton") or [] if s.get("app_id") != key]
                if len(keep) != len(extra.get("skeleton") or []):
                    extra["skeleton"] = keep
                    forgotten = {"skeleton.sections": 1}
        elif what == "law":
            mine = self._gw.facts.get(self._uid, [])
            self._gw.facts[self._uid] = [f for f in mine if f.get("fact_id") != key]
            forgotten = {"law.law": len(mine) - len(self._gw.facts[self._uid])}
        return {"ok": True, "forgotten": forgotten, "left": {},
                "stopped_sessions": ["sess-1"] if what in ("place", "conversation", "all") else [],
                "caches_dropped": 1}

    async def index(self, repo_key: str) -> dict:
        self._log("index", repo_key)
        f = self._mine().get(repo_key) or {}
        return {"repo_key": repo_key, "map": f.get("index")}

    async def facts(self) -> dict:
        self._log("facts")
        return {"facts": [dict(f) for f in self._gw.facts.get(self._uid, [])]}

    async def save_facts(self, facts: list) -> dict:
        self._log("save_facts")
        mine = self._gw.facts.setdefault(self._uid, [])
        by_id = {f.get("fact_id"): i for i, f in enumerate(mine)}
        for f in facts:
            if f.get("fact_id") in by_id:
                mine[by_id[f.get("fact_id")]] = dict(f)
            else:
                mine.append(dict(f))
        return {"ok": True}

    async def delete_fact(self, fact_id: str) -> dict:
        self._log("delete_fact")
        mine = self._gw.facts.get(self._uid, [])
        keep = [f for f in mine if f.get("fact_id") != fact_id]
        if len(keep) == len(mine):
            raise APIError("law not found", 404)
        self._gw.facts[self._uid] = keep
        return {"fact_id": fact_id, "deleted": True}


@pytest.fixture
def gateway():
    """The fake vault. Tests seed it directly with kernel-shaped payloads."""
    return FakeGateway()


@pytest.fixture
def make_ctx(gateway):
    """Minimal ctx stand-in: ctx.user.imperal_id plus the gateway namespace."""
    def _make(imperal_id: str = "imp_u_TEST"):
        return SimpleNamespace(
            user=SimpleNamespace(imperal_id=imperal_id),
            _gw_namespace=lambda name, cls: FakeMemoryClient(gateway, imperal_id))
    return _make


@pytest.fixture
def seed_index(gateway):
    """Seed ONE kernel-shaped index map. Mirrors core/repo_index_map.py payload."""
    def _seed(uid="imp_u_TEST", repo_key="abc123", **fields):
        payload = {
            "repo_root": fields.pop("repo_root", f"/Users/dev/{repo_key}"),
            "file_count": fields.pop("file_count", 0),
            "languages": fields.pop("languages", {"python": 1}),
            "symbol_kinds": fields.pop("symbol_kinds", {"function": 1}),
            "embedded_chunks": fields.pop("embedded_chunks", 0),
            "vectors_ready": fields.pop("vectors_ready", True),
            "git_ref": fields.pop("git_ref", "deadbeefcafe"),
            "branch": fields.pop("branch", "main"),
            "updated_at": fields.pop("updated_at", 1787000000),
        }
        payload.update(fields)
        gateway.file(uid, repo_key)["index"] = payload
        return payload
    return _seed


@pytest.fixture
def seed_memory(gateway):
    """Seed ONE kernel-shaped note set (the repo file's ``entries``).

    ``notes`` may be plain strings (wrapped into the kernel's entry dict) or
    full entry dicts, so a test can pin citations/timestamps when it matters.
    """
    def _seed(uid="imp_u_TEST", repo_key="abc123", notes=None):
        entries = []
        for n in (notes or []):
            entries.append(n if isinstance(n, dict) else {"note": n, "citations": []})
        f = gateway.file(uid, repo_key)
        f["entries"] = entries
        f["version"] += 1
        return entries
    return _seed
