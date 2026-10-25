"""nwt-mcp: run the MCP server (stdio); `nwt-mcp export <dir>` writes the cards as files; `nwt-mcp view` builds the graph viewer with an agent tab."""
import json
import sys
from pathlib import Path


def export(out):
    from .cards import Graph, tokens
    from .schema import TYPES
    g, out = Graph(), Path(out)
    (out / "types").mkdir(parents=True, exist_ok=True)
    (out / "examples").mkdir(exist_ok=True)
    rows = []

    def write(path, obj, label):
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        rows.append((label, tokens(obj)))

    write(out / "map.json", g.map(), "map")
    for t in TYPES:
        write(out / "types" / f"{t}.json", g.type_card(t), f"type:{t}")
    for i in ("PLX-VAR-HDPE", "PLX-POL-PE", "PLX-MON-ETHYLENE", "PLX-FEED-CRUDE", "sub:CMD/PET/PLA-PE",
              "sym:CMD/PET/PLA-PE/HDPE_FILM", "fam:nwt-cmd-pet-pla-pe-pricing", "dom:pricing", "fld:price_mid"):
        write(out / "examples" / (i.replace(":", "_").replace("/", "_") + ".json"), g.node(i), i)
    # baseline: what "give the agent everything" would cost, even in our compact form
    for layer in ("plastics", "catalogue"):
        rows.append((f"ALL {layer} node cards at once", sum(tokens(g.node(i)) for i, n in g.nodes.items() if n[2] == layer)))
    lines = ["# Card sizes", "", f"Graph: `{g.version}`. Tokens = compact JSON chars / 4 (estimate).", "",
             "| card | tokens |", "|---|---|"] + [f"| `{l}` | {n} |" for l, n in rows]
    (out / "TOKENS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} cards to {out}")


AGENT_JS = """
const AG = __AGENT__;
function drawAgent() {
  const t = N[idx.get(sel)][1], tok = o => Math.round(JSON.stringify(o).length / 4);
  // full ids inside the JSON become links to the same tab
  const json = o => esc(JSON.stringify(o, null, 1)).replace(/&quot;([^&\\n]+)&quot;/g, (m, s) => idx.has(s) && s !== sel ? `&quot;<a href="#agent/${encodeURIComponent(s)}">${s}</a>&quot;` : m);
  const block = (title, call, o, open) => `<details class="agent"${open ? ' open' : ''}><summary><b>${title}</b> <code>${esc(call)}</code> <span class="tiny">≈${tok(o)} ток.</span></summary><pre>${json(o)}</pre></details>`;
  view.innerHTML = `<h2>Что получает AI-агент</h2><p class="small">Ответы MCP-сервера nwt-data для выбранного узла: карточка узла, карточка его типа и карта графа. Ссылки внутри открывают карточку другого узла.</p>`
    + block('Карточка узла', `nwt_get("${sel}")`, AG.nodes[sel], true)
    + block('Карточка типа', `nwt_get("type:${t}")`, AG.types[t], true)
    + block('Карта графа', 'nwt_map()', AG.map, false);
}
"""
AGENT_CSS = ".agent{margin:12px 0}.agent summary{cursor:pointer}.agent pre{white-space:pre-wrap;word-break:break-word;max-height:65vh;overflow:auto}"


def view(out):
    """Kit's graph viewer (view.html) plus an 'Агент' tab with the cards an agent gets. The kit folder is not touched."""
    from .cards import Graph
    from .schema import TYPES
    g, out = Graph(), Path(out)
    src = g.db.parent / "view.html"
    if not src.exists():
        raise SystemExit(f"{src} not found: run `python3 graph.py view` in {g.db.parent}")
    html = src.read_text(encoding="utf-8")
    data = {"map": g.map(), "types": {t: g.type_card(t) for t in TYPES}, "nodes": {i: g.node(i) for i in g.nodes}}
    js = AGENT_JS.replace("__AGENT__", json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
    tabs = "(chain|catalogue|price|plastic|file)"
    edits = [
        ('<button role="tab" data-tab="file" aria-selected="false">Файл</button>',
         '<button role="tab" data-tab="file" aria-selected="false">Файл</button>\n    <button role="tab" data-tab="agent" aria-selected="false">Агент</button>', 1),
        ("file: drawFile };", "file: drawFile, agent: drawAgent };", 1),
        ("const DRAW = {", js + "const DRAW = {", 1),
        (tabs, "(chain|catalogue|price|plastic|file|agent)", 2),
        ("</style>", AGENT_CSS + "</style>", 1),
    ]
    for old, new, n in edits:
        if html.count(old) != n:
            raise SystemExit(f"kit viewer changed, anchor not found {n}x: {old[:60]!r}")
        html = html.replace(old, new)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size // 1048576} MB): open {out.resolve().as_uri()}#agent/PLX-VAR-HDPE")


def main():
    if sys.argv[1:2] == ["export"]:
        export(sys.argv[2] if len(sys.argv) > 2 else "cards")
    elif sys.argv[1:2] == ["prices-import"]:
        # nwt-mcp prices-import series.json observations.json [build/prices.db]
        from .cards import DEFAULT_PRICES, Graph
        from .prices import import_dump
        n_series, n_obs = import_dump(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else DEFAULT_PRICES, set(Graph(prices="/nonexistent").nodes))
        print(f"imported {n_series} series, {n_obs} observations")
    elif sys.argv[1:2] == ["view"]:
        view(sys.argv[2] if len(sys.argv) > 2 else "build/view.html")
    else:
        from .server import mcp
        mcp.run()
