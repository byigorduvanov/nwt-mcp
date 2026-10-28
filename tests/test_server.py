import json

import pytest
from mcp.client import Client

from nwt_mcp.server import MAX_SEARCH, MAX_WALK, mcp


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def call(name, args):
    async with Client(mcp) as c:
        res = await c.call_tool(name, args)
    return res.is_error, "".join(p.text for p in res.content)


@pytest.mark.anyio
async def test_model_limit_is_capped():
    err, txt = await call("nwt_search", {"q": "", "type": "symbol", "limit": 100000})
    out = json.loads(txt)
    assert not err and len(out["hits"]) == MAX_SEARCH and out["total"] > MAX_SEARCH
    err, txt = await call("nwt_walk", {"id": "cat:CMD/PET", "direction": "down", "depth": 10, "limit": 100000})
    assert not err and len(json.loads(txt)["rows"]) == MAX_WALK


@pytest.mark.anyio
async def test_error_hint_reaches_model():
    err, txt = await call("nwt_get", {"id": "HDPE-X"})
    assert err and "unknown id 'HDPE-X'" in txt and "Find ids with nwt_search" in txt
    err, txt = await call("nwt_search", {"q": ""})
    assert err and "empty query" in txt


@pytest.mark.anyio
async def test_close_ids_reach_model():
    err, txt = await call("nwt_get", {"id": "PLX-VAR-PPHOMO"})
    assert err and "closest: PLX-VAR-PP-HOMO" in txt
