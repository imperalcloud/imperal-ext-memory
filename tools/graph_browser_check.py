"""Render the REAL panel payload through REAL cytoscape in a REAL browser.

Why this exists: three rounds of fixing the payload "against the contract"
changed nothing, because the payload was never wrong — the renderer was
hiding every node. Reading DGraph found it; this proves it, by running the
same code path Chromium runs and counting what is actually visible.

The harness mirrors @imperal/ui-kit's DGraph exactly (elements, stylesheet
with the hard-coded mapData(size, 0, 50, ...) domain, and applyFilters with
its opening minMentions=1), then reports visible nodes/edges and PNG size.

It runs BOTH the live payload and a control with mention_count stripped. The
control is the point: it must come back with zero visible nodes and a blank
PNG, or the diagnosis is wrong and nothing here should be trusted.

    python3 tools/graph_browser_check.py payload.json
"""
from __future__ import annotations

import base64
import json
import os
import sys

CHROME = ("/Users/val-mac/Library/Caches/ms-playwright/chromium-1228/"
          "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/"
          "Google Chrome for Testing")

# Lifted verbatim from the renderer, so a difference here is a real difference.
# The library is loaded from a local copy, never a CDN: a network wait made
# the page hang on load and the check never ran. Same version the panel ships.
PAGE = """
<!doctype html><html><body style="margin:0;background:#0f172a">
<div id="cy" style="width:1200px;height:600px"></div>
</body></html>
"""

CYTOSCAPE_JS = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), ".cytoscape.min.js")

HARNESS = r"""
(payload) => {
  const { nodes = [], edges = [], layout = 'concentric',
          min_node_size = 10, max_node_size = 50,
          edge_label_visible = false, color_by = 'type' } = payload;

  const TYPE_COLORS = { person:'#60a5fa', file:'#9ca3af', default:'#64748b' };
  const resolveColor = (n, by) => n.color
    || TYPE_COLORS[String(n[by] ?? '').toLowerCase()] || TYPE_COLORS.default;

  // elements — exactly as DGraph builds them
  const elements = [
    ...nodes.map(n => ({ data: { ...n, id: n.id, label: n.label ?? n.id,
        type: n.type, size: typeof n.size === 'number' ? n.size : 20,
        color: resolveColor(n, color_by),
        mention_count: typeof n.mention_count === 'number' ? n.mention_count : 0 } })),
    ...edges.map(e => ({ data: { id: e.id, source: e.source, target: e.target,
        label: e.label ?? '', weight: typeof e.weight === 'number' ? e.weight : 0.5 } })),
  ];

  const cy = cytoscape({
    container: document.getElementById('cy'),
    elements,
    layout: { name: layout === 'cose-bilkent' ? 'cose' : layout },
    style: [
      { selector: 'node', style: {
          'background-color': 'data(color)', label: 'data(label)',
          width:  `mapData(size, 0, 50, ${min_node_size}, ${max_node_size})`,
          height: `mapData(size, 0, 50, ${min_node_size}, ${max_node_size})`,
          'font-size': '.625rem', color: '#e5e7eb',
          'text-valign': 'bottom', 'text-halign': 'center',
          'text-outline-color': '#0f172a', 'text-outline-width': 2 } },
      { selector: 'edge', style: {
          width: 'mapData(weight, 0, 1, 1, 4)', 'line-color': '#475569',
          'target-arrow-color': '#475569', 'target-arrow-shape': 'triangle',
          'curve-style': 'bezier',
          label: edge_label_visible ? 'data(label)' : '',
          'font-size': '.5rem', color: '#94a3b8', opacity: 0.55 } },
    ],
  });

  // applyFilters — verbatim, including the opening minMentions = 1
  const minMentions = 1, minStrength = 0, hiddenTypes = new Set();
  cy.batch(() => {
    cy.nodes().forEach(n => {
      const type = String(n.data('type') ?? 'unknown');
      const mc = Number(n.data('mention_count') ?? 0);
      n.style('display', (hiddenTypes.has(type) || mc < minMentions) ? 'none' : 'element');
    });
    cy.edges().forEach(e => {
      const src = e.source ? e.source() : null;
      const tgt = e.target ? e.target() : null;
      const w = Number(e.data('weight') ?? 0);
      const hid = (src && src.style('display') === 'none')
               || (tgt && tgt.style('display') === 'none') || w < minStrength;
      e.style('display', hid ? 'none' : 'element');
    });
  });

  let nVis = 0, eVis = 0;
  cy.nodes().forEach(n => { if (n.style('display') !== 'none') nVis++; });
  cy.edges().forEach(e => { if (e.style('display') !== 'none') eVis++; });

  const widths = cy.nodes().map(n => Math.round(n.renderedWidth()));
  const bb = cy.elements(':visible').renderedBoundingBox();
  const png = cy.png({ bg: '#0f172a', full: true, scale: 1, output: 'base64uri' });

  return {
    total_nodes: cy.nodes().length, visible_nodes: nVis,
    total_edges: cy.edges().length, visible_edges: eVis,
    rendered_widths: [Math.min(...widths), Math.max(...widths)],
    bbox: { w: Math.round(bb.w), h: Math.round(bb.h) },
    png_b64: png.split(',')[1] || '',
  };
}
"""


def strip_mention_count(props: dict) -> dict:
    """The control: the payload exactly as it was BEFORE the fix."""
    clone = json.loads(json.dumps(props))
    for n in clone["nodes"]:
        n.pop("mention_count", None)
    return clone


def main() -> int:
    from playwright.sync_api import sync_playwright

    payload_path = sys.argv[1] if len(sys.argv) > 1 else "payload.json"
    dumps = json.load(open(payload_path))
    out_dir = os.path.join(os.path.dirname(payload_path) or ".", "shots")
    os.makedirs(out_dir, exist_ok=True)

    if not os.path.exists(CYTOSCAPE_JS):
        print(f"missing local cytoscape at {CYTOSCAPE_JS}", file=sys.stderr)
        return 2
    cyto_src = open(CYTOSCAPE_JS, encoding="utf-8").read()

    failures: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=CHROME)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}")
                if m.type == "error" else None)

        for entry in dumps:
            repo, props = entry["repo"], entry["props"]
            for tag, data in (("FIXED", props),
                              ("CONTROL (no mention_count)", strip_mention_count(props))):
                page.set_content(PAGE, wait_until="domcontentloaded")
                page.add_script_tag(content=cyto_src)
                page.wait_for_function("() => !!window.cytoscape", timeout=30_000)
                r = page.evaluate(HARNESS, data)

                png = base64.b64decode(r.pop("png_b64") or "")
                name = f"{repo}-{'fixed' if tag == 'FIXED' else 'control'}.png"
                with open(os.path.join(out_dir, name), "wb") as fh:
                    fh.write(png)

                print(f"\n=== {repo} · {tag} ===")
                print(f"  nodes visible : {r['visible_nodes']}/{r['total_nodes']}")
                print(f"  edges visible : {r['visible_edges']}/{r['total_edges']}")
                print(f"  node px range : {r['rendered_widths']}")
                print(f"  drawn area    : {r['bbox']['w']}x{r['bbox']['h']} px")
                print(f"  png bytes     : {len(png):,}  -> shots/{name}")

                if tag == "FIXED":
                    if r["visible_nodes"] != r["total_nodes"]:
                        failures.append(f"{repo}: renderer hides "
                                        f"{r['total_nodes'] - r['visible_nodes']} node(s)")
                    if r["bbox"]["w"] < 50 or r["bbox"]["h"] < 50:
                        failures.append(f"{repo}: nothing drawn (empty bbox)")
                elif r["visible_nodes"] != 0:
                    failures.append(f"{repo}: CONTROL should render nothing, "
                                    f"got {r['visible_nodes']} visible")

        browser.close()

    if errors:
        print("\n=== browser errors ===")
        for e in errors[:10]:
            print("  ", e)

    print("\n" + ("FAILURES:\n  " + "\n  ".join(failures) if failures
                  else "OK — fixed payload renders, control renders nothing."))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
