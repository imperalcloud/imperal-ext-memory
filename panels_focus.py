"""Memory & Index · what a clicked graph node actually MEANS.

Clicking any circle used to redraw the very same graph. ``graph_focus_path``
understood file ids only (``f3``), so a click on a language, a symbol kind, a
directory or the repo core resolved to no focus at all and the panel rebuilt an
identical view — and even a file click only silently sprouted child circles.
Nothing ever said, in words, what had just been selected.

Every id the graph can emit is resolved here into a heading, a sentence and
real rows read off the index, plus — for files and symbols — the path the graph
should expand. The id schemes (``repo``, ``L0``, ``K0``, ``d0``, ``f3``,
``f3s2``) are the ones panels_viz.index_graph assigns; the limit constants are
imported from it rather than restated, and test_graph_focus walks EVERY node of
a real built graph to prove nothing here can drift out of step with it.
"""
from __future__ import annotations

from imperal_sdk import ui

from panels_common import _back, _nav
from panels_viz import (_MAX_DIRS, _MAX_FILES, _MAX_KINDS, _MAX_LANGS,
                        _dir_of, _leaf, file_order)


def _int_map(raw) -> dict[str, int]:
    """Positive integer counts only — a malformed value is skipped, not guessed."""
    out: dict[str, int] = {}
    for key, val in (raw or {}).items():
        try:
            num = int(val)
        except (TypeError, ValueError):
            continue
        if str(key).strip() and num > 0:
            out[str(key)] = num
    return out


def lang_order(d: dict) -> list[tuple[str, int]]:
    """Languages in the exact order index_graph gives them L0, L1, … ids."""
    return sorted(_int_map(d.get("languages")).items(),
                  key=lambda kv: -kv[1])[:_MAX_LANGS]


def kind_order(d: dict) -> list[tuple[str, int]]:
    """Symbol kinds in the exact order index_graph gives them K0, K1, … ids."""
    return sorted(_int_map(d.get("symbol_kinds")).items(),
                  key=lambda kv: -kv[1])[:_MAX_KINDS]


def dir_order(d: dict) -> list[tuple[str, int]]:
    """Directories in the order index_graph numbers them — [] when it draws none."""
    shown = file_order(d)[:_MAX_FILES]
    dirs: dict[str, int] = {}
    for path, items in shown:
        dirs[_dir_of(path)] = dirs.get(_dir_of(path), 0) + len(items)
    if not 1 < len(dirs) <= _MAX_DIRS:
        return []
    return sorted(dirs.items(), key=lambda kv: -kv[1])


def _rows(pairs) -> list[dict]:
    return [{"key": str(k), "value": str(v)} for k, v in pairs]


def resolve_node(d: dict, node_id) -> dict:
    """Explain one clicked node. Empty dict when the id means nothing here.

    Returns ``kind``/``title``/``summary``/``rows`` for the card, and ``focus``
    — the file path the graph should expand, which only files and symbols have.
    """
    nid = str(node_id or "").strip()
    if not nid:
        return {}
    order = file_order(d)

    if nid == "repo":
        langs, kinds = lang_order(d), kind_order(d)
        return {
            "kind": "repo", "focus": "",
            "title": "Repository core",
            "summary": ("Everything Webbee has indexed for this repo. The ring "
                        "around it is one circle per language, per symbol kind, "
                        "and per directory that carries indexed code."),
            "rows": _rows([
                ("Files indexed", f"{int(d.get('file_count') or 0):,}"),
                ("Languages", ", ".join(f"{k} {v:,}" for k, v in langs) or "—"),
                ("Symbols", ", ".join(f"{k} {v:,}" for k, v in kinds) or "—"),
                ("Files carrying symbols", f"{len(order):,}"),
                ("Semantic chunks", f"{int(d.get('embedded_chunks') or 0):,}"),
            ]),
        }

    if nid.startswith("L") and nid[1:].isdigit():
        langs = lang_order(d)
        i = int(nid[1:])
        if not 0 <= i < len(langs):
            return {}
        name, count = langs[i]
        total = int(d.get("file_count") or 0)
        share = f"{100 * count / total:.1f}%" if total else "—"
        files = [p for p, _ in order if p.rsplit(".", 1)[-1].lower()
                 in _EXT.get(name.lower(), ())]
        return {
            "kind": "language", "focus": "",
            "title": f"{name} · {count:,} file(s)",
            "summary": ("A language circle: how much of this repo is written in "
                        "it. Size is the file count, so the ring reads as the "
                        "repo's real composition."),
            "rows": _rows([
                ("Files in this language", f"{count:,}"),
                ("Share of the repo", share),
                ("Indexed files matching it", str(len(files)) if files else "—"),
            ]),
        }

    if nid.startswith("K") and nid[1:].isdigit():
        kinds = kind_order(d)
        i = int(nid[1:])
        if not 0 <= i < len(kinds):
            return {}
        name, count = kinds[i]
        named = [s for _, items in order for s in items if s["kind"] == name]
        return {
            "kind": "kind", "focus": "",
            "title": f"{name} · {count:,} symbol(s)",
            "summary": (f"A symbol-kind circle: every {name} Webbee found while "
                        "indexing. This is the repo-wide total — the named "
                        "examples below come from the busiest files."),
            "rows": _rows(
                [(f"Total {name}s", f"{count:,}")]
                + [(s["name"], f"{_leaf(s['path'])}:{s['line']}")
                   for s in named[:8]]),
        }

    if nid.startswith("d") and nid[1:].isdigit():
        dirs = dir_order(d)
        i = int(nid[1:])
        if not 0 <= i < len(dirs):
            return {}
        name, weight = dirs[i]
        inside = [(p, len(items)) for p, items in order[:_MAX_FILES]
                  if _dir_of(p) == name]
        return {
            "kind": "dir", "focus": "",
            "title": name if name != "·" else "Repository root",
            "summary": ("A directory circle. Its children are the indexed files "
                        "inside it — click one to expand that file's symbols."),
            "rows": _rows([("Indexed symbols here", str(weight))]
                          + [(_leaf(p), f"{n} symbol(s)") for p, n in inside]),
        }

    if "s" in nid[1:] and nid.startswith("f"):
        head, _, tail = nid[1:].partition("s")
        if head.isdigit() and tail.isdigit():
            i, j = int(head), int(tail)
            if not 0 <= i < len(order):
                return {}
            path, items = order[i]
            if not 0 <= j < len(items):
                return {}
            sym = items[j]
            return {
                "kind": "symbol", "focus": path,
                "title": f"{sym['name']} · {sym['kind']}",
                "summary": ("One indexed symbol. Webbee can jump straight to it "
                            "in the terminal agent by name."),
                "rows": _rows([
                    ("Kind", sym["kind"]),
                    ("File", path),
                    ("Line", str(sym["line"])),
                    ("Others in this file", str(max(len(items) - 1, 0))),
                ]),
            }

    if nid.startswith("f") and nid[1:].isdigit():
        i = int(nid[1:])
        if not 0 <= i < len(order):
            return {}
        path, items = order[i]
        return {
            "kind": "file", "focus": path,
            "title": _leaf(path),
            "summary": ("A file circle, now expanded: each new circle around it "
                        "is one indexed symbol, and its edge label is the line "
                        "number."),
            "rows": _rows([("Path", path), ("Indexed symbols", str(len(items)))]
                          + [(s["name"], f"{s['kind']} @ line {s['line']}")
                             for s in items[:10]]),
        }

    return {}


# Extension hints, used ONLY to count how many indexed files plausibly belong
# to a language circle. The index stores no per-file language, so this is
# reported as a related count and never as the language's own file total.
_EXT = {
    "python": ("py",), "javascript": ("js", "mjs", "cjs"),
    "typescript": ("ts", "tsx"), "markdown": ("md",), "json": ("json",),
    "shell": ("sh", "bash"), "yaml": ("yml", "yaml"), "css": ("css",),
    "html": ("html", "htm"), "sql": ("sql",), "swift": ("swift",),
}


def focus_card(info: dict, repo_key: str) -> ui.UINode | None:
    """The clicked node, in words — with a ← that clears the selection."""
    if not info:
        return None
    return ui.Card(
        title=info["title"],
        content=ui.Stack(direction="v", gap=2, children=[
            _back("Back to the whole graph", _nav(repo=str(repo_key or ""))),
            ui.Text(content=info["summary"], variant="caption"),
            ui.KeyValue(items=info["rows"]),
        ]),
    )


__all__ = ["lang_order", "kind_order", "dir_order", "resolve_node",
           "focus_card"]
