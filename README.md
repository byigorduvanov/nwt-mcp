# nwt-mcp

MCP server over the NWT symbol graph (`~/.nwt/symbol-graph/graph.db`, read-only). The client's agent gets data in
layers and only pays tokens for what it asks for:

| Layer | Tool | Size |
|---|---|---|
| tool list + instructions | always loaded | ~880 tokens |
| map: types, counts, trees, regions | `nwt_map` | ~290 |
| type card: what a type is, its fields and links | `nwt_get("type:variety")` | 60–300 |
| node card: own fields + grouped links | `nwt_get(id)` | ~30 (symbol) to ~600 (largest family) |
| chain / tree around a node | `nwt_walk(id, up\|down)` | ~100 |
| price series | `nwt_prices(id)` | ~220 |

A typical question ("HDPE film price in Europe, what drives it") costs ~2,000 tokens in total. All node cards at once
would be ~1.37 million. Numbers per card: [cards/TOKENS.md](cards/TOKENS.md).

## Rules the cards follow

- **is_a inherits, made_from does not.** HDPE `is_a` PE: fields equal to the parent's go to `inherits` and are not
  repeated (`inherit=true` shows the values). Ethylene → PE is production: nothing passes.
- **Family fields inherit in two levels**: 9 fields every family has (`type:family`), then the fields every family of
  a data domain has (`dom:pricing`, ...). A family card lists only its own: 95,258 field links become 29,477.
- **Grouped ids**: `{"sym:CMD/PET/PLA-PE/": ["HDPE_FILM", "HDPE_BM"]}`. Long lists stop at `limit` with `<name>_total`.
- **Brief by default**: Russian text, sources and per-grade properties only with `detail="full"`.

The meaning of types and relations is the only hand-written part: [src/nwt_mcp/schema.py](src/nwt_mcp/schema.py).
Counts, links and inherited fields are computed from the graph, so a new `nwt update` of the graph needs no edits.

## Run

```bash
uv run nwt-mcp                       # stdio MCP server
uv run nwt-mcp export cards          # write map, type cards, example node cards and TOKENS.md
uv run nwt-mcp view                  # build/view.html: the kit's graph viewer + an "Агент" tab with every node's cards
uv run pytest -q
claude mcp add nwt-data -- uv run --directory /Users/atom/work/nwt/nwt-mcp nwt-mcp
```

`NWT_GRAPH_DB` overrides the graph path.

## Prices

`nwt_prices` reads the graph's own observations (none yet: the NWT Kit publishes no price pack) plus
`build/prices.db`: PlasticPortal series from our crawler on the VPS (`/opt/plastic-index`), mapped to graph materials
and symbols in [src/nwt_mcp/prices.py](src/nwt_mcp/prices.py). Refresh:

```bash
ssh spaceship-us 'sqlite3 -json -readonly /opt/plastic-index/data/plastic.db "<SERIES_SQL>"' > build/dump/series.json   # SQL in prices.py
ssh spaceship-us 'sqlite3 -json -readonly /opt/plastic-index/data/plastic.db "<OBS_SQL>"' > build/dump/observations.json
uv run nwt-mcp prices-import build/dump/series.json build/dump/observations.json
```

## Bench

100 questions from different kinds of clients, each run as an isolated headless Claude Code session that sees only
this MCP server ([bench/run.py](bench/run.py)); expectations are computed from the data ([bench/questions.py](bench/questions.py)).

```bash
uv run python bench/questions.py bench/questions.json
uv run python bench/run.py <tag> --workers 6      # ~6 min, ~$1.3 (half Haiku, half Sonnet)
uv run python bench/report.py <tag>
```

Results of the three runs of 2026-10-25: [bench/results/](bench/results/), report: [docs/test-report.html](docs/test-report.html).
