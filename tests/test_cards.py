import json

import pytest

from nwt_mcp.cards import Graph, dumps, group, tokens
from nwt_mcp.schema import RELS, TYPES

g = Graph()


def test_group_writes_prefix_once():
    assert group(["sym:A/B/X", "sym:A/B/Y", "fld:z", "PLX-VAR-HDPE"]) == {"sym:A/B/": ["X", "Y"], "fld:": ["z"], "": ["PLX-VAR-HDPE"]}


def test_schema_covers_graph():
    assert {n[0] for n in g.nodes.values()} == set(TYPES)
    assert {r for es in g.out.values() for r, _ in es} == set(RELS)


def test_every_card_builds_within_budget():
    for t in TYPES:
        assert tokens(g.type_card(t)) < 400, t
    worst = max(g.nodes, key=lambda i: tokens(g.node(i)))
    assert tokens(g.node(worst)) < 1200, worst


def test_variety_inherits_from_polymer_only_via_is_a():
    hdpe = g.node("PLX-VAR-HDPE")
    assert hdpe["is_a"] == "PLX-POL-PE" and hdpe["inherits"] == ["formula", "repeat_unit"]
    assert "formula" not in hdpe
    full = g.node("PLX-VAR-HDPE", inherit=True)
    assert full["inherited"]["formula"] == "(C2H4)n"
    # made_from passes nothing: ethylene's data must not show up in a polymer card
    assert "inherited" not in g.node("PLX-POL-PE", inherit=True)


def test_family_fields_inherit_without_loss():
    for f in [i for i, n in g.nodes.items() if n[0] == "family"][::50]:
        card = g.node(f, inherit=True, limit=10**6)
        got = {p + s for part in (card["fields"], card["inherited_fields"]) for p, v in part.items() for s in v}
        assert got == {d for r, d in g.out[f] if r == "has_field"}, f


def test_walk_up_reaches_feedstock_and_down_reaches_variety():
    up = {r[1] for r in g.walk("PLX-VAR-HDPE", "up", depth=6)["rows"]}
    assert {"PLX-POL-PE", "PLX-MON-ETHYLENE", "PLX-FEED-CRUDE", "PLX-FEED-NATGAS"} <= up
    down = {r[1] for r in g.walk("PLX-MON-ETHYLENE", "down", depth=2)["rows"]}
    assert "PLX-VAR-HDPE" in down
    assert g.walk("fam:nwt-cmd-pet-pla-pe-pricing", "up", depth=1)["rows"][0][1] in ("dom:pricing", "sub:CMD/PET/PLA-PE")


def test_search_ranks_exact_names_first():
    assert g.search("HDPE")["hits"][0][0] == "PLX-VAR-HDPE"
    assert g.search("polyethylene")["hits"][0][0] == "PLX-POL-PE"
    assert all(h[0].startswith("sym:CMD/PET/PLA-PE/") for h in g.search("film", under="sub:CMD/PET/PLA-PE")["hits"])


def test_unknown_id_says_how_to_find_one():
    with pytest.raises(KeyError, match="nwt_search"):
        g.node("PLX-VAR-NOPE")


def test_typical_question_stays_cheap():
    # "HDPE film price in Europe and what drives it": map, search, type card, node card, prices, chain
    steps = [g.map(), g.search("hdpe film"), g.type_card("variety"), g.node("PLX-VAR-HDPE"), g.prices("PLX-VAR-HDPE"),
             g.walk("PLX-VAR-HDPE", "up", depth=6)]
    assert sum(map(tokens, steps)) < 2500


@pytest.mark.anyio
async def test_mcp_tools_return_compact_text_only():
    from mcp.client import Client
    from nwt_mcp.server import mcp
    async with Client(mcp) as c:
        tools = (await c.list_tools()).tools
        assert sorted(t.name for t in tools) == ["nwt_get", "nwt_map", "nwt_prices", "nwt_search", "nwt_walk"]
        assert tokens(json.dumps([t.model_dump(exclude_none=True) for t in tools])) < 1500
        res = await c.call_tool("nwt_get", {"id": "PLX-VAR-HDPE"})
        assert res.structured_content is None and json.loads(res.content[0].text)["abbr"] == "HDPE"
        bad = await c.call_tool("nwt_get", {"id": "nope"})
        assert bad.is_error
        r = await c.read_resource("nwt://node/sym:CMD/PET/PLA-PE/HDPE_FILM")
        assert json.loads(r.contents[0].text)["prices"] == "PLX-VAR-HDPE"
