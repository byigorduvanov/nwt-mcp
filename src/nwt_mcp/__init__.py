"""nwt-mcp: run the MCP server (stdio), or `nwt-mcp export <dir>` to write the cards as files for review."""
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


def main():
    if sys.argv[1:2] == ["export"]:
        export(sys.argv[2] if len(sys.argv) > 2 else "cards")
    else:
        from .server import mcp
        mcp.run()
