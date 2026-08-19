"""Memory & Index · Visual layer — the index as a graph and charts.

Why a graph rather than more key/value rows: the index IS a graph — a repo
holds files, files hold symbols — and that shape is impossible to read as a
flat list of "top_symbols" strings. ``ui.Graph`` is Cytoscape-backed, so
clustering, sizing and colour carry real meaning here:

  * node size  = how many symbols hang off that file (mapData over `size`)
  * node type  = repo | file | symbol, which drives colour via `color_by`
  * clicking a file node re-renders the panel focused on that file

Everything drawn here comes from fields the kernel actually persists in
``imperal:repo_index_map`` — ``languages``, ``symbol_kinds``, ``top_symbols``
(each "name (kind) @ path:line"), ``file_count``, ``embedded_chunks``. Nothing
is synthesised: if a field is absent the visual degrades instead of inventing
structure that does not exist in the index.
"""
from __future__ import annotations

import logging
import re

from imperal_sdk import ui

from panels_common import _nav

log = logging.getLogger("memory-index")

# "name (kind) @ path/to/file.py:123" — the exact shape core/repo_index_map.py
# writes into top_symbols. Parsed defensively: an unparsable entry is skipped
# rather than guessed at, so a format change degrades the visual instead of
# producing a wrong graph.
_SYM_RE = re.compile(r"^(?P<name>.+?)\s*\((?P<kind>[^)]+)\)\s*@\s*(?P<path>[^:]+):(?P<line>\d+)\s*$")

_MAX_FILE_NODES = 28      # cytoscape stays readable; beyond this it is hairball
_MAX_SYMS_PER_FILE = 6


def parse_symbols(top_symbols: list) -> list[dict]:
    """Turn raw ``top_symbols`` strings into {name, kind, path, line} dicts."""
    out: list[dict] = []
    for raw in (top_symbols or []):
        m = _SYM_RE.match(str(raw).strip())
        if not m:
            continue
        out.append({
            "name": m.group("name").strip(),
            "kind": m.group("kind").strip(),
            "path": m.group("path").strip(),
            "line": int(m.group("line")),
        })
    return out


def _short(path: str) -> str:
    """Last two path segments — enough to identify a file without the noise."""
    parts = [p for p in str(path).split("/") if p]
    return "/".join(parts[-2:]) if len(parts) > 1 else (parts[-1] if parts else "?")


def index_graph(d: dict, repo_label: str, focus: str = "") -> ui.Card | None:
    """The repo's structure as a clickable graph. None when there is nothing to draw."""
    syms = parse_symbols(d.get("top_symbols"))
    if not syms:
        return None

    by_file: dict[str, list[dict]] = {}
    for s in syms:
        by_file.setdefault(s["path"], []).append(s)

    # Busiest files first: with a capped node budget, the ones carrying the most
    # symbols are the ones worth showing.
    files = sorted(by_file.items(), key=lambda kv: len(kv[1]), reverse=True)
    files = files[:_MAX_FILE_NODES]

    repo_id = "repo::root"
    nodes: list[dict] = [{
        "id": repo_id,
        "label": repo_label,
        "type": "repo",
        "size": 100,
    }]
    edges: list[dict] = []

    for path, items in files:
        fid = f"file::{path}"
        is_focus = bool(focus) and path == focus
        nodes.append({
            "id": fid,
            "label": _short(path),
            "type": "focus" if is_focus else "file",
            "size": 20 + len(items) * 12,
        })
        edges.append({"id": f"e::{fid}", "source": repo_id, "target": fid,
                      "label": f"{len(items)}"})

        # Symbol nodes only for the focused file (or when few files exist):
        # drawing every symbol at once is what turns a graph into a hairball.
        show_syms = is_focus or (not focus and len(files) <= 6)
        if not show_syms:
            continue
        for s in items[:_MAX_SYMS_PER_FILE]:
            sid = f"sym::{path}::{s['name']}::{s['line']}"
            nodes.append({
                "id": sid,
                "label": s["name"],
                "type": s["kind"] or "symbol",
                "size": 14,
            })
            edges.append({"id": f"e::{sid}", "source": fid, "target": sid,
                          "label": f":{s['line']}"})

    hint = ("Click a file to expand its symbols."
            if not focus else
            f"Showing symbols in {_short(focus)} — click another file to switch.")

    return ui.Card(
        title="Structure graph",
        content=ui.Stack(direction="v", gap=1, children=[
            ui.Text(content=hint, variant="caption"),
            ui.Graph(
                nodes=nodes,
                edges=edges,
                layout="cose-bilkent",
                height=460,
                color_by="type",
                min_node_size=14,
                max_node_size=64,
                # The clicked node's id arrives as node_id; the panel turns a
                # "file::<path>" id back into a focus path. node_id is OMITTED
                # from the action rather than blanked: ui.Graph injects it, so
                # pinning it to "" here would erase the click's own payload.
                on_node_click=_nav(_omit=("node_id",),
                                   repo=str(d.get("_repo_key") or "")),
            ),
        ]),
    )


def index_charts(d: dict) -> ui.Card | None:
    """Languages and symbol kinds as bar charts — proportions, not raw rows."""
    langs = {k: int(v) for k, v in (d.get("languages") or {}).items()
             if isinstance(v, (int, float))}
    kinds = {k: int(v) for k, v in (d.get("symbol_kinds") or {}).items()
             if isinstance(v, (int, float))}
    if not langs and not kinds:
        return None

    # Titles live on a wrapping ui.Section, NOT on ui.Chart: the SDK deployed on
    # the platform accepts only data/type/x_key/height/colors/y2_keys, and a
    # newer local SDK that also takes title=/show_legend= will happily validate
    # code the worker then rejects. Section is the portable way to label a chart.
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
    total_repos = max(index_count, 1)
    return ui.Card(
        title="Memory footprint",
        content=ui.Stack(direction="v", gap=2, children=[
            ui.Stats(children=[
                ui.Stat(label="Indexed repos", value=str(index_count), icon="FolderGit2"),
                ui.Stat(label="Durable notes", value=str(note_count), icon="Brain"),
                ui.Stat(label="Semantic chunks", value=f"{chunk_count:,}", icon="Layers"),
                ui.Stat(label="Orphaned note sets", value=str(orphan_count),
                        icon="Unlink",
                        color="orange" if orphan_count else "green"),
            ]),
            ui.Progress(value=min(100, int(100 * (index_count - orphan_count) / total_repos)),
                        label="Repos whose notes match a live index",
                        show_value=True),
        ]),
    )


__all__ = ["parse_symbols", "index_graph", "index_charts", "memory_bars"]
