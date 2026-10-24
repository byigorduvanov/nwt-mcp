"""Cards over the NWT symbol graph: map -> type card -> node card, plus search, walk and price series.
Every answer is compact JSON so an agent spends tokens only on what it asked for."""
import json
import os
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from .schema import FIELD_MEANING, RELS, TYPES

DEFAULT_DB = Path.home() / ".nwt" / "symbol-graph" / "graph.db"
# Fields never shown in a brief card: Russian text and sources are long and rarely needed to find data.
FULL_ONLY = {"name_ru", "description_ru", "sources", "properties"}


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def tokens(obj):
    # shortcut: chars/4 is close for English JSON, not exact; use the model's count_tokens API for billing-grade numbers
    return round(len(obj if isinstance(obj, str) else dumps(obj)) / 4)


def group(ids):
    """['sym:A/B/X', 'sym:A/B/Y', 'fld:z'] -> {'sym:A/B/': ['X', 'Y'], 'fld:': ['z']}: a shared prefix is written once."""
    out = defaultdict(list)
    for i in ids:
        cut = i.rfind("/") + 1 or i.find(":") + 1
        out[i[:cut]].append(i[cut:])
    return dict(out)


class Graph:
    def __init__(self, db=None):
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
        con.close()
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

    # ---- helpers
    def name(self, i):
        t, l, _, d = self.nodes[i]
        return d.get("name_en") or l

    def row(self, i):
        return [i, self.nodes[i][0], self.name(i)]

    def require(self, i):
        if i not in self.nodes:
            raise KeyError(f"unknown id {i!r}: find ids with nwt_search")

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
        self.require(i)
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
            ids.sort()
            card[name] = group(ids[:limit]) if len(ids) > 1 else ids[0]
            if len(ids) > limit:
                card[name + "_total"] = len(ids)
        n = sum(1 for s in self.series if s["material"] == i or s["symbol"] == i)
        if n:
            card["price_series"] = n
        return card

    # ---- search: ranked rows [id, type, name]
    def search(self, q, type=None, under=None, limit=10):
        words = q.lower().split()
        if not words:
            raise ValueError("empty query")
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
        return {"total": len(hits), "hits": [self.row(i) for *_, i in hits[:limit]]}

    def _under(self, i, path):
        # segment boundary: PLA-PE must not match PLA-PET
        inside = lambda node: (p := node.split(":", 1)[-1]) == path or p.startswith(path + "/")
        return inside(i) or any(inside(s) for r, s in self.inn[i] if r in ("has_family", "has_symbol"))

    # ---- walk: tree/chain around a node as rows [depth, id, type, name, via]
    def walk(self, i, direction="up", kind=None, depth=3, limit=50):
        self.require(i)
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

    # ---- price series of a material or symbol; observations only if the graph has them
    def prices(self, i, limit=30):
        self.require(i)
        rows = [s for s in self.series if i in (s["material"], s["symbol"])]
        out = {"id": i, "series_total": len(rows)}
        if rows:
            cols = ["symbol", "region", "incoterm", "price_type", "material_state"]
            out["cols"] = cols + ["observations"]
            out["series"] = [[s[c] for c in cols] + [self.obs.get(s["series_key"], 0)] for s in rows[:limit]]
        else:
            kids = [s for r, s in self.out[i] if r == "has_variety"]
            if kids:
                out["see_varieties"] = {k: sum(1 for s in self.series if s["material"] == k) for k in kids}
        if not sum(self.obs.values()):
            out["note"] = "this graph build has no price observations yet: series definitions only"
        return out
