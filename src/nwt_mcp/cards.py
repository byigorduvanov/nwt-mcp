"""Cards over the NWT symbol graph: map -> type card -> node card, plus search, walk and price series.
Every answer is compact JSON so an agent spends tokens only on what it asked for."""
import difflib
import json
import os
import sqlite3
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from .schema import FIELD_MEANING, RELS, TYPES

DEFAULT_DB = Path.home() / ".nwt" / "symbol-graph" / "graph.db"
DEFAULT_PRICES = Path(__file__).resolve().parents[2] / "build" / "prices.db"
# Fields never shown in a brief card: Russian text and sources are long and rarely needed to find data.
FULL_ONLY = {"name_ru", "description_ru", "sources", "properties"}


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def tokens(obj):
    # shortcut: chars/4 is close for English JSON, not exact; use the model's count_tokens API for billing-grade numbers
    return round(len(obj if isinstance(obj, str) else dumps(obj)) / 4)


def period_date(p):
    """'2026-W37' -> '2026-09-07' (ISO week Monday), '2026-08' -> '2026-08', dates unchanged: comparable as strings."""
    if "-W" in p:
        y, w = p.split("-W")
        return date.fromisocalendar(int(y), int(w), 1).isoformat()
    return p


def group(ids):
    """['sym:A/B/X', 'sym:A/B/Y', 'fld:z'] -> {'sym:A/B/': ['X', 'Y'], 'fld:': ['z']}: a shared prefix is written once."""
    out = defaultdict(list)
    for i in ids:
        cut = i.rfind("/") + 1 or i.find(":") + 1
        out[i[:cut]].append(i[cut:])
    return dict(out)


class Graph:
    def _load_prices(self, path):
        # prices imported beside the graph (build/prices.db, see prices.py); the kit's graph.db stays read-only
        p = Path(path or os.environ.get("NWT_PRICES_DB") or DEFAULT_PRICES)
        if not p.exists():
            return
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        cols = ("series_key", "material", "symbol", "region", "basis", "price_type", "material_state", "currency", "unit", "frequency", "source")
        self.series += [dict(zip(cols, r)) for r in con.execute(f"SELECT {', '.join(cols)} FROM series")]
        for k, per, v in con.execute("SELECT series_key, period, value FROM observations ORDER BY 1, 2"):
            self.points[k].append([per, v])
        con.close()
        self.obs = {k: len(v) for k, v in self.points.items()}

    def __init__(self, db=None, prices=None):
        self.db = Path(db or os.environ.get("NWT_GRAPH_DB") or DEFAULT_DB)
        con = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
        self.nodes = {i: (t, l, layer, json.loads(d)) for i, t, l, layer, d in con.execute("SELECT id, type, label, layer, data FROM nodes")}
        self.out, self.inn = defaultdict(list), defaultdict(list)
        for s, d, r in con.execute("SELECT src, dst, rel FROM edges"):
            self.out[s].append((r, d))
            self.inn[d].append((r, s))
        cols = ("class", "base", "region", "basis", "incoterm", "price_type")
        self.symclass = {r[0]: {k: v for k, v in zip(cols, r[1:]) if v} for r in con.execute(f"SELECT symbol, {', '.join(cols)} FROM symbol_classes")}
        self.regions = dict(con.execute("SELECT code, name_en FROM regions"))
        cols = ("series_key", "material", "symbol", "region", "basis", "incoterm", "price_type", "material_state", "currency", "unit")
        self.series = [dict(zip(cols, r)) for r in con.execute(f"SELECT {', '.join(cols)} FROM price_series")]
        self.obs = dict(con.execute("SELECT series_key, count(*) FROM price_observations GROUP BY 1"))
        self.props = defaultdict(list)
        for r in con.execute("SELECT material, key, grade, min, max, typical, unit, test, condition FROM material_properties"):
            self.props[r[0]].append(r[1:])
        self.points = defaultdict(list)
        for k, p, v in con.execute("SELECT series_key, valid_date, price_mid FROM price_observations WHERE price_mid IS NOT NULL ORDER BY 1, 2"):
            self.points[k].append([p, v])
        con.close()
        self._load_prices(prices)
        ver = self.db.parent / "VERSION"
        self.version = ver.read_text().strip() if ver.exists() else "unknown"
        self.materials_dir = self.db.parent / "materials"
        self._inherit_fields()
        self._index()

    # ---- inheritance of family fields: every family has the base fields, every family of a domain has the domain's
    def _inherit_fields(self):
        fams = {i: {d for r, d in self.out[i] if r == "has_field"} for i, n in self.nodes.items() if n[0] == "family"}
        self.base_fields = set.intersection(*fams.values()) if fams else set()
        by_dom = defaultdict(list)
        for f, fs in fams.items():
            by_dom[self.domain_of(f)].append(fs)
        self.domain_fields = {d: set.intersection(*l) - self.base_fields for d, l in by_dom.items()}

    def domain_of(self, fam):
        return next((d for r, d in self.out[fam] if r == "in_domain"), None)

    def _index(self):
        self.hay = {}
        for i, (t, l, _, d) in self.nodes.items():
            self.hay[i] = " ".join(str(x) for x in (i, l, d.get("name_en"), d.get("abbr"), d.get("code")) if x).lower()
        self.type_counts = Counter(n[0] for n in self.nodes.values())
        # names an agent may pass instead of an id: abbreviation, English or Russian name, last code segment
        self.alias = defaultdict(set)
        for i, (t, l, _, d) in self.nodes.items():
            # also the id without its prefix: nwt-cmd-pet-pla-pe-pricing (fam:), PET-BOTTLE (PLX-VAR-)
            bare = i.split(":", 1)[1] if ":" in i else i.split("-", 2)[-1] if i.startswith("PLX-") else None
            for a in (d.get("abbr"), d.get("name_en"), l, i.rsplit("/", 1)[-1] if "/" in i else None, bare):
                if a:
                    self.alias[a.strip().lower()].add(i)
        self.npts = Counter()
        for s in self.series:
            n = len(self.points.get(s["series_key"], ()))
            self.npts[s["material"]] += n
            self.npts[s["symbol"]] += n

    # ---- helpers
    def name(self, i):
        t, l, _, d = self.nodes[i]
        return d.get("name_en") or l

    def row(self, i):
        # 4th element only when the id has price points, so an agent does not probe symbols without data
        return [i, self.nodes[i][0], self.name(i)] + ([self.npts[i]] if self.npts.get(i) else [])

    def resolve(self, i):
        """The id itself, or the one node an agent meant by a name or code it typed instead (LDPE, HDPE_FILM)."""
        if i in self.nodes:
            return i
        if i.startswith("type:"):
            raise KeyError(f"{i!r} is a type, not a node: read it with nwt_get, list its nodes with nwt_search(q='', type='{i[5:]}')")
        cands = sorted(self.alias.get(i.strip().lower(), ()), key=lambda n: self.nodes[n][2] != "plastics")
        if len(cands) == 1 or cands and self.nodes[cands[0]][2] == "plastics" and (len(cands) < 2 or self.nodes[cands[1]][2] != "plastics"):
            return cands[0]
        near = [h[0] for h in self.search(i, limit=5)["hits"]] if i.strip() else []
        if len(near) < 5 and i.strip():
            # a typo or made-up id (HDPE_FLIM, PLX-VAR-PPHOMO) matches no search word: compare it to every id and name
            if not hasattr(self, "_fuzzy"):
                self._fuzzy = {n.lower(): n for n in self.nodes}
                for n in self.nodes:  # a shared name keeps its first node: plastics (PLX-POL-PE) before the catalogue
                    self._fuzzy.setdefault(self.name(n).lower(), n)
            close = (self._fuzzy[k] for k in difflib.get_close_matches(i.strip().lower(), list(self._fuzzy), n=8, cutoff=0.6))
            near = list(dict.fromkeys([*near, *close]))[:5]
        raise KeyError(f"unknown id {i!r}" + (f"; closest: {', '.join(near)}" if near else "") + ". Find ids with nwt_search")

    def require(self, i):
        self.resolve(i)

    def is_a_parents(self, i):
        ps = [s for r, s in self.inn[i] if r == "has_variety"]
        return ps + [d for r, d in self.out[i] if r == "in_domain"]

    def material(self, i):
        p = self.materials_dir / f"{i}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    # ---- map: the only thing an agent needs first
    def map(self):
        c = self.type_counts
        n = lambda t: f"{t}({c[t]})"
        return {
            "graph": self.version,
            "trees": {
                "plastics (production)": f"{n('feedstock')} > {n('intermediate')} > {n('monomer')} > {n('polymer')} > is_a > {n('variety')}; {n('substance')} outside chain",
                "catalogue (classification)": f"{n('collection')} > {n('category')} > {n('subcategory')} > {n('symbol')} | {n('family')} > {n('field')}",
                "data kinds": f"family is_a {n('data_domain')}; field in {n('field_category')}",
                "links": "material priced_as symbol; material produced_by plant symbol; symbol metric_of material",
            },
            "rel_kinds": {"is_a": "child inherits parent fields", "contains": "tree position only",
                          "made_from": "production step, nothing inherited", "link": "cross-layer reference"},
            "regions": self.regions,
            "price_observations": sum(self.obs.values()),
            "how": "nwt_search(q) -> nwt_get(id) -> nwt_walk(id) / nwt_prices(id); nwt_get('type:<type>') explains a type once",
        }

    # ---- type card: schema of one node type, computed from the graph
    def type_card(self, t):
        if t not in TYPES:
            raise KeyError(f"unknown type {t!r}; types: {', '.join(TYPES)}")
        layer, level, parent, what = TYPES[t]
        ids = [i for i, n in self.nodes.items() if n[0] == t]
        keys = Counter(k for i in ids for k in self.nodes[i][3])
        fields = {k: FIELD_MEANING.get(k, "") + ("" if keys[k] == len(ids) else f" (in {keys[k]} of {len(ids)})") for k in keys}
        if t == "symbol":
            for k in ("class", "base", "region", "basis", "incoterm", "price_type"):
                fields[k] = FIELD_MEANING[k]
        rels = Counter()
        for i in ids:
            for r, d in self.out[i]:
                rels[(RELS[r][1], "out", self.nodes[d][0], RELS[r][0])] += 1
            for r, s in self.inn[i]:
                rels[(RELS[r][2], "in", self.nodes[s][0], RELS[r][0])] += 1
        card = {"type": t, "layer": layer, "level": level, "parent": parent and f"{'is_a' if t == 'variety' else 'in'} {parent}", "what": what, "count": len(ids), "fields": fields,
                "links": {f"{name}": f"{kind} {other} x{cnt}" for (name, _, other, kind), cnt in sorted(rels.items())},
                "examples": ids[:2]}
        if t == "symbol":
            card["classes"] = dict(Counter(c.get("class") for c in self.symclass.values()).most_common())
            card["units"] = dict(Counter(self.nodes[i][3].get("unit") for i in ids).most_common(8))
        if t == "family":
            card["inherited_fields"] = {"all families": group(sorted(self.base_fields)),
                                        "per domain": {d: len(f) for d, f in self.domain_fields.items()}}
        return {k: v for k, v in card.items() if v is not None}

    # ---- node card: own data + links, inherited data only on request
    def node(self, i, inherit=False, detail="brief", limit=20):
        if i.startswith("type:"):
            return self.type_card(i[5:])
        i = self.resolve(i)
        t, label, layer, data = self.nodes[i]
        card = {"id": i, "type": t, "name": self.name(i)}
        own = {k: v for k, v in data.items() if k not in ("name_en", "code") and (detail == "full" or k not in FULL_ONLY) and v not in (None, "", [])}
        if layer == "catalogue" and label != card["name"]:
            own["label"] = label
        for p in self.is_a_parents(i):
            pd = self.nodes[p][3]
            same = {k: v for k, v in own.items() if pd.get(k) == v}
            for k in same:
                own.pop(k)
            card["is_a"] = p
            if inherit:
                card.setdefault("inherited", {}).update({k: v for k, v in pd.items() if k not in own and k not in ("name_en", "name_ru", "abbr", "code", "description_ru", "sources") and v})
            elif same:
                card["inherits"] = sorted(same)
        card.update(own)
        card.update(self.symclass.get(i, {}))
        if layer == "plastics":
            m = self.material(i)
            if m.get("identifiers"):
                card["identifiers"] = {k: v for k, v in m["identifiers"].items() if k != "sources" and not k.endswith("_note")}
            if m.get("ranges"):
                card["ranges"] = {k: [r.get("min"), r.get("max"), r.get("unit")] for k, r in m["ranges"].items()}
            if detail == "full":
                card["properties"] = [list(p) for p in self.props.get(i, [])]
                card["gaps"] = m.get("gaps") or []
        if t == "family":
            own_f = {d for r, d in self.out[i] if r == "has_field"} - self.base_fields - self.domain_fields.get(self.domain_of(i), set())
            card["fields"] = group(sorted(own_f))
            card["inherits_fields"] = {"type:family": len(self.base_fields), self.domain_of(i): len(self.domain_fields.get(self.domain_of(i), ()))}
            if inherit:
                card["inherited_fields"] = group(sorted(self.base_fields | self.domain_fields.get(self.domain_of(i), set())))
        if t == "data_domain":
            card["fields_for_families"] = group(sorted(self.domain_fields.get(i, ())))
        links = defaultdict(list)
        for r, d in self.out[i]:
            if r not in ("in_domain", "has_field") or t != "family":
                links[RELS[r][1]].append(d)
        for r, s in self.inn[i]:
            if r != "has_variety" or t != "variety":
                links[RELS[r][2]].append(s)
        for name, ids in sorted(links.items()):
            # ids with prices first, so a cut list keeps what has data (rPET, rHDPE were cut alphabetically)
            # then tradable products before metrics, fees and policies
            rank = {"series": 0, "grade": 0, "substance": 1, "futures": 2, "asset": 2, "trade": 3, "metric": 4, "policy": 5}
            ids.sort(key=lambda x: (-self.npts.get(x, 0), rank.get(self.symclass.get(x, {}).get("class"), 3), x))
            # a subcategory's symbols share one prefix, so all of them (max 146) cost ~450 tokens: never cut them
            cap = max(limit, 150) if name == "symbols" else limit
            card[name] = group(ids[:cap]) if len(ids) > 1 else ids[0]
            if len(ids) > cap:
                card[name + "_total"] = len(ids)
        n = sum(1 for s in self.series if s["material"] == i or s["symbol"] == i)
        if n:
            card["price_series"] = n
        return card

    # ---- search: ranked rows [id, type, name]
    def search(self, q, type=None, under=None, limit=10):
        words = q.lower().split()
        if not words and not type:
            raise ValueError("empty query: give words, or type= to list every node of a type")
        if type and type not in TYPES:
            # a made-up type (material, product) must not cost a failed call: search all types and say so
            out = self.search(q, None, under, limit)
            return {**out, "note": f"unknown type {type!r}, searched all types; types: {', '.join(TYPES)}"}
        path = under.split(":", 1)[-1] if under else None
        hits = []
        for i, h in self.hay.items():
            t = self.nodes[i][0]
            if type and t != type or not all(w in h for w in words):
                continue
            if path and not self._under(i, path):
                continue
            d = self.nodes[i][3]
            ql = q.lower()
            score = (100 if ql in ((d.get("abbr") or "").lower(), (d.get("code") or "").lower(), i.lower().rsplit("/", 1)[-1]) else
                     60 if self.name(i).lower().startswith(ql) else 20)
            score += {"variety": 9, "polymer": 8, "monomer": 7, "subcategory": 6, "symbol": 5}.get(t, 0)
            hits.append((-score, len(self.name(i)), i))
        hits.sort()
        if not hits and type and words:
            # a wrong type guess (HDPE as polymer) must not cost the agent a second call
            out = self.search(q, None, under, limit)
            return {**out, "note": f"no {type} matches; showing all types"} if out["total"] else out
        rows = [self.row(i) for *_, i in hits[:limit]]
        out = {"total": len(hits), "hits": rows}
        if rows and not any(len(r) == 4 for r in rows):
            out["note"] = "none of these hits has price data"
        return out

    def _under(self, i, path):
        # segment boundary: PLA-PE must not match PLA-PET
        inside = lambda node: (p := node.split(":", 1)[-1]) == path or p.startswith(path + "/")
        return inside(i) or any(inside(s) for r, s in self.inn[i] if r in ("has_family", "has_symbol"))

    # ---- walk: tree/chain around a node as rows [depth, id, type, name, via]
    def walk(self, i, direction="up", kind=None, depth=3, limit=50):
        i = self.resolve(i)
        if direction not in ("up", "down"):
            raise ValueError("direction is 'up' or 'down'")
        kinds = {kind} if kind else {"is_a", "contains", "made_from"}
        seen, rows, frontier = {i}, [], [i]
        for lvl in range(1, depth + 1):
            nxt = []
            for cur in frontier:
                for nb, rel in self._steps(cur, direction, kinds):
                    if nb in seen:
                        continue
                    seen.add(nb)
                    nxt.append(nb)
                    rows.append([lvl, *self.row(nb), rel])
            frontier = nxt
        out = {"from": i, "direction": direction, "rows": rows[:limit]}
        if len(rows) > limit:
            out["total"] = len(rows)
        return out

    def _steps(self, i, direction, kinds):
        # in_domain / in_field_category point child -> parent; every other rel points parent/source -> child/product
        up_is_dst = {"in_domain", "in_field_category"}
        for r, d in self.out[i]:
            if RELS[r][0] in kinds and (direction == "up") == (r in up_is_dst):
                yield d, r
        for r, s in self.inn[i]:
            if RELS[r][0] in kinds and (direction == "up") != (r in up_is_dst):
                yield s, r

    # ---- price series of a material or symbol, series with data first; history = last N points per series
    def prices(self, i, limit=30, history=0, since=None, until=None):
        # a series key from an earlier answer (plasticportal:weekly:ABS) selects that one series
        one = [s for s in self.series if s["series_key"] == i]
        i = one[0]["symbol"] if one else self.resolve(i)
        rows = one or [s for s in self.series if i in (s["material"], s["symbol"])]
        rows.sort(key=lambda s: (-len(self.points.get(s["series_key"], ())), s["series_key"]))
        out = {"id": i, "series_total": len(rows), "with_data": sum(1 for s in rows if self.points.get(s["series_key"]))}
        if rows:
            out["cols"] = ["series", "symbol", "region", "terms", "price_type", "state", "unit", "freq", "n", "first", "last", "last_value", "age_d"]
            out["series"] = []
            for s in rows[:limit]:
                pts = self.points.get(s["series_key"], [])
                unit = f"{s.get('currency')}/{s.get('unit')}" if s.get("currency") else s.get("unit")
                age = (date.today() - date.fromisoformat(period_date(pts[-1][0])[:10])).days if pts else None
                out["series"].append([s["series_key"], s["symbol"], s["region"], s.get("incoterm") or s.get("basis"), s["price_type"],
                                      s["material_state"], unit, s.get("frequency"), len(pts),
                                      pts[0][0] if pts else None, pts[-1][0] if pts else None, pts[-1][1] if pts else None, age])
            if history:
                n, lo, hi = max(1, min(int(history), 120)), since and period_date(since), until and period_date(until)
                keep = lambda p: (not lo or period_date(p) >= lo) and (not hi or period_date(p) <= hi)
                hist = {s["series_key"]: [p for p in self.points[s["series_key"]] if keep(p[0])][-n:] for s in rows[:limit]}
                out["history"] = {k: v for k, v in hist.items() if v}
            sources = sorted({s["source"] for s in rows if s.get("source")})
            if sources:
                out["sources"] = sources
        # a polymer's own series may be empty while its varieties have prices: say so instead of "no data"
        kids = {k: self.npts.get(k, 0) for r, k in self.out[i] if r == "has_variety"}
        if kids:
            out["varieties_price_points"] = kids
        if not out["with_data"]:
            out["note"] = ("no own price observations; varieties have prices: call nwt_prices on them" if any(kids.values())
                           else "no price observations for this id: series definitions only")
        return out
