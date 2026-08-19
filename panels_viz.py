"""Memory & Index · Visual layer — the index as a graph and charts.

Why a graph rather than more key/value rows: the index IS a graph — a repo
holds directories, directories hold files, files hold symbols — and that shape
is unreadable as a flat list of "top_symbols" strings.

Everything here comes from fields the kernel actually persists in
``imperal:repo_index_map``: ``languages``, ``symbol_kinds``, ``top_symbols``
(each "name (kind) @ path:line"), ``file_count``, ``embedded_chunks``. Nothing
is synthesised — a missing field degrades the visual instead of inventing
structure the index does not have.

NODE IDS ARE PLAIN ``repo`` / ``f3`` / ``f3s2`` ON PURPOSE. The first version
used ``file::imperal-ext-admin/panels_llm_models.py`` and drew nothing:
Cytoscape ids flow into selector strings, where ``:`` ``.`` ``/`` are syntax.
sharelock-v2 — the one graph already working in this panel host — passes plain
ids from its database, and also sets ``animate=False`` so the layout lands
inside the viewport instead of drifting. Both lessons are applied here.
"""
from __future__ import annotations

import logging
import re

from imperal_sdk import ui

from panels_common import _nav

log = logging.getLogger("memory-index")

# "name (kind) @ path/to/file.py:123" — the exact shape core/repo_index_map.py
# writes. An unparsable entry is skipped, never guessed at, so a format change
# degrades the graph instead of drawing something false.
_SYM_RE = re.compile(
    r"^(?P<name>.+?)\s*\((?P<kind>[^)]+)\)\s*@\s*(?P<path>[^:]+):(?P<line>\d+)\s*$")

_MAX_FILES = 22        # keeps the layout inside the viewport, still detailed
_MAX_DIRS = 8
_MAX_FOCUS_SYMS = 12
_MAX_LANGS = 6
_MAX_KINDS = 4

# The renderer's node style is mapData(size, 0, 50, min_node_size,
# max_node_size): the INPUT domain is hard-coded 0..50, and min/max_node_size
# are the pixel diameters it maps onto. So `size` must live in 0..50 — it is
# not a pixel value — while the props below carry the pixels.
_SIZE_MIN = 10.0
_SIZE_MAX = 50.0
_PX_MIN = 18.0
_PX_MAX = 64.0


def parse_symbols(top_symbols) -> list[dict]:
    """Turn raw ``top_symbols`` strings into {name, kind, path, line} dicts."""
    out: list[dict] = []
    for raw in (top_symbols or []):
        m = _SYM_RE.match(str(raw))
        if not m:
            continue
        out.append({
            "name": m.group("name").strip(),
            "kind": m.group("kind").strip(),
            "path": m.group("path").strip(),
            "line": int(m.group("line")),
        })
    return out


def file_order(d: dict) -> list[tuple[str, list[dict]]]:
    """Files by symbol count, then path — DETERMINISTIC on purpose.

    A clicked node arrives as an index (``f7``), so the panel must be able to
    rebuild the exact same ordering to know which file that was. Sorting by
    count alone would let ties reshuffle between renders and focus the wrong
    file, hence the path tie-break.
    """
    by_file: dict[str, list[dict]] = {}
    for s in parse_symbols(d.get("top_symbols")):
        by_file.setdefault(s["path"], []).append(s)
    return sorted(by_file.items(), key=lambda kv: (-len(kv[1]), kv[0]))


def _dir_of(path: str) -> str:
    parts = [p for p in str(path).split("/") if p]
    return "/".join(parts[:-1]) if len(parts) > 1 else "·"


def _leaf(path: str) -> str:
    parts = [p for p in str(path).split("/") if p]
    return parts[-1] if parts else "?"


def index_graph(d: dict, repo_label: str, focus: str = "") -> ui.UINode | None:
    """The repo's structure as a clickable graph. None when nothing to draw."""
    order = file_order(d)
    if not order:
        return None

    shown = order[:_MAX_FILES]
    total_syms = sum(len(v) for _, v in order)

    # Directory tier: real structure, but only when it says something. One
    # directory for everything would just be a wasted ring.
    dirs: dict[str, int] = {}
    for path, items in shown:
        dirs[_dir_of(path)] = dirs.get(_dir_of(path), 0) + len(items)
    use_dirs = 1 < len(dirs) <= _MAX_DIRS

    nodes: list[dict] = [{"id": "repo", "label": repo_label,
                          "type": "repo", "size": 100}]
    edges: list[dict] = []

    # Language tier: the composition of the WHOLE repo, with real file counts.
    # Without it a 3110-file repo drew nine nodes, because the structural tiers
    # below can only describe the ~20 files named in top_symbols — true, but a
    # misleading sense of scale for the repository as a whole.
    langs: dict[str, int] = {}
    for key, val in (d.get("languages") or {}).items():
        try:
            count = int(val)
        except (TypeError, ValueError):
            continue
        if str(key).strip() and count > 0:
            langs[str(key)] = count
    for n, (name, count) in enumerate(
            sorted(langs.items(), key=lambda kv: -kv[1])[:_MAX_LANGS]):
        lid = f"L{n}"
        nodes.append({"id": lid, "label": f"{name} · {count:,}",
                      "type": "language", "size": 34 + min(count // 40, 46)})
        edges.append({"id": f"e{lid}", "source": "repo", "target": lid,
                      "label": f"{count:,} files"})

    # Symbol-kind tier: the repo's real symbol totals (function 10,081 /
    # class 2,420 for MCP-Configs). top_symbols caps at 20 entries, so the
    # structural tiers below can only ever describe ~20 files — these aggregate
    # counts are what tell the true size of what Webbee has indexed.
    kinds: dict[str, int] = {}
    for key, val in (d.get("symbol_kinds") or {}).items():
        try:
            count = int(val)
        except (TypeError, ValueError):
            continue
        if str(key).strip() and count > 0:
            kinds[str(key)] = count
    for n, (name, count) in enumerate(
            sorted(kinds.items(), key=lambda kv: -kv[1])[:_MAX_KINDS]):
        kid = f"K{n}"
        nodes.append({"id": kid, "label": f"{name} · {count:,}",
                      "type": "kind", "size": 30 + min(count // 300, 46)})
        edges.append({"id": f"e{kid}", "source": "repo", "target": kid,
                      "label": f"{count:,}"})

    dir_id: dict[str, str] = {}
    if use_dirs:
        for n, (name, weight) in enumerate(sorted(dirs.items(),
                                                  key=lambda kv: -kv[1])):
            did = f"d{n}"
            dir_id[name] = did
            nodes.append({"id": did, "label": name, "type": "dir",
                          "size": 40 + min(weight, 40)})
            edges.append({"id": f"e{did}", "source": "repo", "target": did,
                          "label": str(weight)})

    for i, (path, items) in enumerate(shown):
        fid = f"f{i}"
        focused = bool(focus) and path == focus
        nodes.append({
            "id": fid,
            "label": _leaf(path),
            "type": "focus" if focused else "file",
            "size": 22 + min(len(items) * 10, 46),
        })
        parent = dir_id.get(_dir_of(path), "repo") if use_dirs else "repo"
        edges.append({"id": f"e{fid}", "source": parent, "target": fid,
                      "label": str(len(items))})

        if focused:
            for j, s in enumerate(items[:_MAX_FOCUS_SYMS]):
                sid = f"{fid}s{j}"
                nodes.append({"id": sid, "label": s["name"],
                              "type": s["kind"] or "symbol", "size": 16})
                edges.append({"id": f"e{sid}", "source": fid, "target": sid,
                              "label": str(s["line"])})

    head = [ui.Text(
        content=(f"{len(langs)} language(s) across {int(d.get('file_count') or 0):,} "
                 f"file(s); {len(order)} file(s) carry {total_syms} indexed symbol(s)"
                 + (f" — showing the {len(shown)} busiest." if len(shown) < len(order)
                    else ".")
                 + (f" Focused: {focus}" if focus else
                    " Click a file to expand its symbols.")),
        variant="caption")]
    if focus:
        head.append(ui.Button(label="← Back to full graph", variant="ghost",
                              size="sm", on_click=_nav(repo=str(d.get("_repo_key") or ""))))

    # Two non-optional things, both read straight off the renderer's source.
    # 1. `size` rescaled into its hard-coded 0..50 mapData domain (a clamp
    #    would flatten the top tiers into each other).
    # 2. `mention_count` on EVERY node — the invisible-graph bug: the renderer
    #    opens with a minMentions=1 filter and reads a missing field as 0, so
    #    every node went display:none, then every edge with it. Cytoscape
    #    mounted and painted an empty canvas — hence also the empty PNG.
    raws = []
    for n in nodes:
        try:
            raws.append(float(n.get("size") or 0))
        except (TypeError, ValueError):
            raws.append(0.0)
    lo, hi = min(raws), max(raws)
    span = (hi - lo) or 1.0
    for n, raw in zip(nodes, raws):
        scaled = _SIZE_MIN + (raw - lo) / span * (_SIZE_MAX - _SIZE_MIN)
        n["size"] = round(scaled, 2)
        n["mention_count"] = max(1, int(round(scaled)))

    graph = ui.Graph(
        nodes=nodes,
        edges=edges,
        # Deterministic; cose-bilkent drifts out of frame on first paint.
        layout="concentric",
        height=600,
        color_by="type",
        edge_label_visible=True,
        min_node_size=_PX_MIN,
        max_node_size=_PX_MAX,
        # node_id is injected by ui.Graph itself, so it must NOT be blanked by
        # the action — hence _omit.
        on_node_click=_nav(_omit=("node_id",),
                           repo=str(d.get("_repo_key") or "")),
    )
    # Nothing is assigned onto graph.props: only the props above are defined.
    return ui.Section(
        title="Structure graph",
        children=[*head, graph],
    )


def index_charts(d: dict) -> ui.Card | None:
    """Languages and symbol kinds as bar charts — proportions, not raw rows."""
    langs = {k: int(v) for k, v in (d.get("languages") or {}).items()
             if isinstance(v, (int, float))}
    kinds = {k: int(v) for k, v in (d.get("symbol_kinds") or {}).items()
             if isinstance(v, (int, float))}
    if not langs and not kinds:
        return None

    # Titles live on a wrapping ui.Section, NOT on ui.Chart: the deploy
    # validator's component allowlist accepts only data/type/x_key/height/
    # colors/y2_keys, even though the worker's SDK would take title=.
    blocks = []
    if langs:
        rows = [{"name": k, "files": v} for k, v in
                sorted(langs.items(), key=lambda kv: kv[1], reverse=True)[:8]]
        blocks.append(ui.Section(title="Files by language", children=[
            ui.Chart(data=rows, type="bar", x_key="name", height=180),
        ]))
    if kinds:
        rows = [{"name": k, "symbols": v} for k, v in
                sorted(kinds.items(), key=lambda kv: kv[1], reverse=True)[:8]]
        blocks.append(ui.Section(title="Symbols by kind", children=[
            ui.Chart(data=rows, type="bar", x_key="name", height=180),
        ]))

    return ui.Card(title="Index at a glance",
                   content=ui.Stack(direction="v", gap=2, children=blocks))


def memory_bars(index_count: int, note_count: int, orphan_count: int,
                chunk_count: int) -> ui.Card:
    """Inventory-level proportions: how much of the memory is which store."""
    matched = max(index_count - orphan_count, 0)
    pct = int(round(100 * matched / index_count)) if index_count else 0
    return ui.Card(
        title="Memory footprint",
        content=ui.Stack(direction="v", gap=2, children=[
            ui.Stats(children=[
                ui.Stat(label="Indexed repos", value=str(index_count)),
                ui.Stat(label="Repos with notes", value=str(note_count)),
                ui.Stat(label="Semantic chunks", value=f"{chunk_count:,}"),
            ]),
            ui.Progress(value=pct, label=f"{matched}/{index_count} repos have "
                                         "notes filed under the live index"),
        ]),
    )


# graph_focus_path used to live here and resolved ONLY file ids, which is why
# clicking a language/kind/directory/core circle silently redrew the same
# graph. panels_focus.resolve_node replaces it and understands every id this
# module emits, so there is deliberately no second resolver here to drift.
__all__ = ["parse_symbols", "file_order", "index_graph",
           "index_charts", "memory_bars"]
