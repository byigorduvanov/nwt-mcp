"""MCP server: five read-only tools over the NWT graph. Answers are compact JSON text, never structured duplicates."""
from typing import Literal

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from .cards import Graph, dumps

INSTRUCTIONS = (
    "NWT data graph: plastics production chain + market data catalogue. Start with nwt_map once, find ids with "
    "nwt_search, read one card with nwt_get, follow chains with nwt_walk. Ids are permanent codes; never guess one. "
    "Lists of ids are grouped by shared prefix: {\"sym:CMD/PET/PLA-PE/\":[\"HDPE_FILM\"]} = sym:CMD/PET/PLA-PE/HDPE_FILM."
)

mcp = MCPServer("nwt-data", instructions=INSTRUCTIONS)
RO = ToolAnnotations(read_only_hint=True, open_world_hint=False)
_graph = None


def graph():
    global _graph
    if _graph is None:
        _graph = Graph()
    return _graph


def tool(fn):
    return mcp.tool(annotations=RO, structured_output=False)(fn)


@tool
def nwt_map() -> str:
    """Overview: node types with counts, how they nest, relation kinds, region codes. Call once at the start."""
    return dumps(graph().map())


@tool
def nwt_search(q: str, type: str | None = None, under: str | None = None, limit: int = 10) -> str:
    """Find ids by name, abbreviation or code (all words must match). Returns [id, type, name] rows, best first.
    type: only this node type; if nothing matches, all types are searched. polymer = PE, PP, PVC, PS, PET, ABS;
    variety = HDPE, LDPE, LLDPE, PP-HOMO/RCP/ICP, PVC-U/P, GPPS, HIPS, PET-BOTTLE, RPET. Usually omit it.
    under: only inside this catalogue node, e.g. 'sub:CMD/PET/PLA-PE' or 'cat:CMD/PET'."""
    return dumps(graph().search(q, type, under, limit))


@tool
def nwt_get(id: str, inherit: bool = False, detail: Literal["brief", "full"] = "brief", limit: int = 20) -> str:
    """One card. 'type:<type>' (e.g. type:variety) explains a node type: fields, links, counts.
    Any other id gives the node card: own fields, links (first `limit` per kind, *_total = full count).
    Fields equal to the is_a parent are listed in 'inherits'; inherit=true includes their values.
    detail=full adds Russian text, sources, per-grade properties and data gaps."""
    return dumps(graph().node(id, inherit, detail, limit))


@tool
def nwt_walk(id: str, direction: Literal["up", "down"] = "up",
             kind: Literal["is_a", "contains", "made_from", "link"] | None = None, depth: int = 3, limit: int = 50) -> str:
    """Rows [depth, id, type, name, rel] around a node. up = parents and raw materials, down = children and products.
    kind limits the relation kind (default: is_a + contains + made_from). Example: walk HDPE up, depth 6 = full production chain."""
    return dumps(graph().walk(id, direction, kind, depth, limit))


@tool
def nwt_prices(id: str, limit: int = 30) -> str:
    """Price series of a material or market symbol: symbol, region, incoterm, price type, number of observations."""
    return dumps(graph().prices(id, limit))


@mcp.resource("nwt://map", mime_type="application/json")
def map_resource() -> str:
    """Graph overview (same as nwt_map)."""
    return dumps(graph().map())


@mcp.resource("nwt://type/{type}", mime_type="application/json")
def type_resource(type: str) -> str:
    """Type card: what a node type is, its fields and links."""
    return dumps(graph().type_card(type))


@mcp.resource("nwt://node/{+id}", mime_type="application/json")
def node_resource(id: str) -> str:
    """Node card (brief)."""
    return dumps(graph().node(id))
