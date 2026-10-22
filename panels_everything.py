"""Memory & Index · "Everything Webbee holds" — the whole memory, as stored.

One contour of visibility: every place of the user's memory the vault reports
(``GET /v1/memory/all``) is drawn here — the account first, then every repo,
including repos whose code index was deleted but whose working memory, plans
or conversations are still stored. Nothing is filtered: a count key without a
plain name is shown under its raw name, and a place with only a few graph
events still gets its card. Hiding any of it is how a "cleared" memory once
came back in a new session.

Every delete button opens a confirmation first, and the confirmation calls
``forget_memory`` — the vault's one forget door plus a fresh re-read. Like the
note modals, each confirmation is bound to its subject by a short ``token``
(place + total, conversation + message count, …): once the subject is
forgotten or changed, the token stops matching and the stale view state can
not bring the window back. A missing token never matches here — a delete
confirmation must always be about something the user just saw.
"""
from __future__ import annotations

from imperal_sdk import ui

from app import age
from memory_places import (
    all_token,
    conversation_token,
    describe,
    find_conversation,
    find_place,
    find_skeleton,
    flat_counts,
    is_orphan,
    label,
    place_title,
    place_token,
    places,
    skeleton_token,
)
from panels_common import _back, _err, _nav
from panels_modals import _modal

_SECTION = "everything"


def _ask(what: str, key: str, tok: str, proj: str = ""):
    """Open the confirmation for one thing (never the delete itself)."""
    return _nav(section=_SECTION, fwhat=what, fkey=key, fproj=proj, token=tok)


def _forget_button(text: str, what: str, key: str, tok: str, size: str = "sm") -> ui.UINode:
    return ui.Button(label=text, variant="danger", size=size, icon="Trash2",
                     on_click=_ask(what, key, tok))


def counts_rows(counts) -> list[dict]:
    """One row per count key, biggest first; unknown keys under their raw name."""
    rows = sorted(flat_counts(counts).items(), key=lambda kv: kv[1], reverse=True)
    return [{"key": label(k), "value": f"{v:,}"} for k, v in rows]


def _conversations(p: dict) -> list[ui.UINode]:
    out: list[ui.UINode] = []
    for c in p.get("conversations") or []:
        if not isinstance(c, dict) or not c.get("id"):
            continue
        bits = [str(c.get("kind") or "chat"), f"{int(c.get('messages') or 0)} message(s)"]
        if c.get("updated_at"):
            bits.append(f"updated {age(c.get('updated_at'))}")
        if c.get("indexed") is False:
            bits.append("no index row")
        out.append(ui.Stack(direction="h", gap=1, children=[
            ui.Text(content=f"{c.get('title') or c.get('id')} — {' · '.join(bits)}"),
            _forget_button("Delete", "conversation", str(c["id"]), conversation_token(c)),
        ]))
    return out


def _skeleton(p: dict) -> list[ui.UINode]:
    out: list[ui.UINode] = []
    for s in p.get("skeleton") or []:
        if not isinstance(s, dict) or not s.get("app_id"):
            continue
        n = len(s.get("sections") or [])
        out.append(ui.Stack(direction="h", gap=1, children=[
            ui.Text(content=f"{s['app_id']} — {n} section(s)"),
            _forget_button("Delete", "skeleton", str(s["app_id"]), skeleton_token(s)),
        ]))
    return out


def place_card(p: dict) -> ui.UINode:
    """One place in full: what it is, every count, its conversations, its forget."""
    account = p.get("place") == "account"
    body: list[ui.UINode] = []
    if is_orphan(p):
        body.append(ui.Badge(label="code index deleted — memory left over", color="yellow"))
    meta = [{"key": k.capitalize(), "value": str(p[k])}
            for k in ("root", "remote", "machine", "branch") if p.get(k)]
    if not account:
        meta.insert(0, {"key": "Place", "value": str(p.get("place"))})
    if p.get("synced_at"):
        meta.append({"key": "Synced", "value": age(p.get("synced_at"))})
    if meta:
        body.append(ui.KeyValue(items=meta))
    rows = counts_rows(p.get("counts") or {})
    body.append(ui.KeyValue(items=rows) if rows else ui.Text(content="No records."))
    convs = _conversations(p)
    if convs:
        body.append(ui.Section(title=f"Conversations ({len(convs)})", children=convs))
    if account and flat_counts(p.get("counts") or {}).get("law.law"):
        # Rules are listed (and deleted one by one) in their own section.
        body.append(ui.Button(label="See and delete rules one by one", variant="secondary",
                              size="sm", icon="UserCheck",
                              on_click=_nav(section="user_memory", lifecycle="all")))
    apps = _skeleton(p)
    if apps:
        body.append(ui.Section(title=f"Extension data ({len(apps)})", children=apps))
    body.append(_forget_button(
        "Forget all account memory" if account else "Forget everything about this repo",
        "place", str(p.get("place")), place_token(p), size="md"))
    total = int(p.get("total") or 0)
    return ui.Card(title=f"{place_title(p)} — {total:,} record(s)",
                   content=ui.Stack(direction="v", gap=1, children=body))


def leftover_cards(listing) -> list[ui.UINode]:
    """Memory left from deleted repos, for the overview: each with its forget."""
    out = []
    for p in places(listing):
        if not is_orphan(p):
            continue
        out.append(ui.Card(title=place_title(p), content=ui.Stack(direction="v", gap=1, children=[
            ui.Text(content=f"{p.get('place')} · {int(p.get('total') or 0):,} record(s): "
                            f"{describe(p.get('counts') or {}, limit=4) or 'no records'}"),
            ui.Badge(label="code index deleted — memory left over", color="yellow"),
            _forget_button("Forget everything about this repo", "place",
                           str(p.get("place")), place_token(p)),
        ])))
    return out


def _subject(listing: dict, what: str, key: str) -> tuple[str, str, dict] | None:
    """(name, token, counts) of what a confirmation is about; None when gone."""
    if what == "all":
        totals: dict[str, int] = {}
        for p in places(listing):
            for k, v in flat_counts(p.get("counts") or {}).items():
                totals[k] = totals.get(k, 0) + v
        return "everything Webbee holds about you", all_token(listing), totals
    if what == "place":
        p = find_place(listing, key)
        return (place_title(p), place_token(p), p.get("counts") or {}) if p else None
    if what == "conversation":
        _, c = find_conversation(listing, key)
        if c is None:
            return None
        return (f"conversation '{c.get('title') or key}'", conversation_token(c),
                {"conversation.conversations": 1})
    if what == "skeleton":
        s = find_skeleton(listing, key)
        if s is None:
            return None
        return (f"the data of extension {key}", skeleton_token(s),
                {"skeleton.sections": len(s.get("sections") or [])})
    return None


def forget_modal(listing: dict, what: str, key: str, proj: str, tok: str) -> ui.UINode | None:
    """The confirmation for one forget — only while ``tok`` still matches it."""
    subject = _subject(listing, what, key)
    if subject is None or not tok or subject[1] != tok:
        return None
    name, _, counts = subject
    rows = counts_rows(counts)
    extra = (" A running Webbee session on it is stopped first." if what in ("place", "conversation", "all")
             else "")
    return _modal(
        title=f"Forget {name}?",
        destructive=True,
        size="lg",
        confirm_label="Forget permanently",
        cancel_label="← Keep it",
        on_confirm=ui.Call("forget_memory", what=what, key=key, project_id=proj),
        on_close=_nav(section=_SECTION),
        content=ui.Stack(direction="v", gap=2, children=[
            _back("Back to everything", _nav(section=_SECTION)),
            ui.Text(content=(f"This deletes {name} from every section of your memory "
                             f"in the vault.{extra} Afterwards your whole memory is read "
                             f"again to confirm nothing of it is left.")),
            ui.KeyValue(items=rows) if rows else ui.Text(content="No records counted."),
            ui.Alert(type="warning", message="This cannot be undone."),
        ]),
    )


def everything_body(listing: dict | None, kwargs: dict) -> ui.UINode:
    """The whole section: header, stats, account, repos, forget-all, modal."""
    if listing is None:
        return ui.Stack(direction="v", gap=2, children=[
            _back("Back to all repos", _nav()),
            _err("Could not read your memory — try again shortly. Nothing was changed."),
        ])
    rows = places(listing)
    total = int(listing.get("total") or sum(int(p.get("total") or 0) for p in rows))
    orphans = sum(1 for p in rows if is_orphan(p))
    children: list[ui.UINode] = [
        _back("Back to all repos", _nav()),
        ui.Header(text="Everything Webbee holds",
                  subtitle=("Everything stored about you, shown as it is. Each delete goes "
                            "through one forget door and is checked by reading it all again.")),
        ui.Stats(children=[
            ui.Stat(label="Places", value=str(len(rows))),
            ui.Stat(label="Total records", value=f"{total:,}"),
            ui.Stat(label="Left from deleted repos", value=str(orphans)),
        ]),
    ]
    if not rows:
        children.append(ui.Empty(message="Webbee holds nothing about you.", icon="BrainCircuit"))
    children.extend(place_card(p) for p in rows)
    if rows:
        children.append(ui.Card(title="Forget everything", content=ui.Stack(direction="v", gap=1, children=[
            ui.Text(content=("Deletes everything above — every repo, the account, every "
                             "conversation — and stops any running Webbee session.")),
            _forget_button("Forget everything", "all", "", all_token(listing), size="md"),
        ])))
    what = str(kwargs.get("fwhat") or "").strip().lower()
    if what:
        modal = forget_modal(listing, what, str(kwargs.get("fkey") or "").strip(),
                             str(kwargs.get("fproj") or "").strip(),
                             str(kwargs.get("token") or "").strip())
        if modal is not None:
            children.append(modal)
    return ui.Stack(direction="v", gap=2, children=children)


__all__ = ["everything_body", "place_card", "leftover_cards", "forget_modal", "counts_rows"]
