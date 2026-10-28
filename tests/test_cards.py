import json
import re

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
    wrong_type = g.search("HDPE", type="polymer")
    assert wrong_type["hits"][0][0] == "PLX-VAR-HDPE" and "no polymer" in wrong_type["note"]
    assert "note" not in g.search("HDPE", type="variety")


@pytest.mark.skipif(not g.points, reason="no build/prices.db: run nwt-mcp prices-import")
def test_prices_have_data_and_history_filters_mixed_periods():
    p = g.prices("PLX-VAR-HDPE")
    assert p["with_data"] >= 1 and p["series"][0][8] > 0 and "note" not in p
    h = g.prices("sym:CMD/PET/PLA-PE/HDPE_FILM", history=4, since="2026-W30")["history"]
    assert all(len(v) <= 4 for v in h.values()) and len(h) == 2  # weekly and monthly both survive the filter
    assert "note" in g.prices("PLX-FEED-CRUDE")
    assert g.prices("plasticportal:weekly:ABS")["series_total"] == 1


def test_names_resolve_to_ids_and_types_list_their_nodes():
    # found by the 100-session bench: agents pass names instead of ids and want "all collections"
    assert g.prices("LDPE")["id"] == "PLX-VAR-LDPE" and g.node("HDPE_FILM")["id"] == "sym:CMD/PET/PLA-PE/HDPE_FILM"
    assert g.search("", type="collection")["total"] == g.type_counts["collection"]
    with pytest.raises(KeyError, match="is a type"):
        g.walk("type:collection")


@pytest.mark.skipif(not g.points, reason="no build/prices.db")
def test_polymer_prices_point_to_varieties_and_search_marks_price_data():
    pp = g.prices("PLX-POL-PP")
    assert pp["varieties_price_points"]["PLX-VAR-PP-HOMO"] > 0 and "varieties have prices" in pp["note"]
    assert len(next(h for h in g.search("polypropylene")["hits"] if h[0] == "PLX-VAR-PP-HOMO")) == 4
    jan = g.prices("sym:CMD/PET/PLA-PE/HDPE_FILM", history=50, since="2024-01-01", until="2024-01-31")["history"]
    assert all(p[0].startswith("2024-01") or p[0] in ("2024-W01", "2024-W02", "2024-W03", "2024-W04", "2024-W05") for v in jan.values() for p in v)


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


def test_unknown_id_suggests_close_ids():
    for typo, meant in [("PLX-VAR-HDPE-FILM", "PLX-VAR-HDPE"), ("sym:CMD/PET/PLA-PE/HDPE_FLIM", "sym:CMD/PET/PLA-PE/HDPE_FILM"),
                        ("PLX-POL-POLYETHYLENE", "PLX-POL-PE"), ("PLX-VAR-PPHOMO", "PLX-VAR-PP-HOMO")]:
        with pytest.raises(KeyError, match=rf"closest: .*\b{re.escape(meant)}[,.]"):
            g.node(typo)
