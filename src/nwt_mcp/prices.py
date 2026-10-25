"""Import PlasticPortal prices (our crawler on the VPS, /opt/plastic-index) into build/prices.db for nwt_prices.
Dump on the VPS:  sqlite3 -json -readonly plastic.db "<SERIES_SQL>" / "<OBS_SQL>"  (see `nwt-mcp prices-import`)."""
import json
import sqlite3
from pathlib import Path

SERIES_SQL = "SELECT id, dataset, ext_id, name, unit, currency, market, price_basis, origin, canonical_url FROM series"
OBS_SQL = "SELECT series_id, period_key, value FROM observation WHERE recorded_to IS NULL"

S = "sym:CMD/PET/"
# crawler series (dataset, ext_id) -> (material, market symbol); checked against the graph on import
MAP = {
    ("monthly", "1"): ("PLX-VAR-HDPE", S + "PLA-PE/HDPE_IM"),
    ("monthly", "2"): ("PLX-VAR-HDPE", S + "PLA-PE/HDPE_BM"),
    ("monthly", "3"): ("PLX-VAR-HDPE", S + "PLA-PE/HDPE_FILM"),
    ("monthly", "4"): ("PLX-VAR-LDPE", S + "PLA-PE/LDPE_IM"),
    ("monthly", "5"): ("PLX-VAR-LDPE", S + "PLA-PE/LDPE_FILM"),
    ("monthly", "6"): ("PLX-VAR-LLDPE", S + "PLA-PE/LLDPE_BUTENE"),
    ("monthly", "7"): ("PLX-VAR-PP-HOMO", S + "PLA-PP/PP_HOMO_IM_GP"),
    ("monthly", "8"): ("PLX-VAR-PP-ICP", S + "PLA-PP/PP_BLOCK_COPO"),
    ("monthly", "9"): ("PLX-VAR-PP-RCP", S + "PLA-PP/PP_RANDOM_COPO"),
    ("monthly", "10"): ("PLX-VAR-PET-BOTTLE", S + "PLA-PET/PET_BOTTLE"),
    ("monthly", "11"): ("PLX-VAR-HIPS", S + "PLA-PS/HIPS"),
    ("monthly", "12"): ("PLX-VAR-GPPS", S + "PLA-PS/GPPS"),
    ("monthly", "13"): ("PLX-SUB-PA6", S + "PLA-ENG/PA6"),
    ("monthly", "14"): ("PLX-SUB-PA66", S + "PLA-ENG/PA66"),
    ("monthly", "15"): ("PLX-POL-ABS", S + "PLA-PS/ABS"),
    ("monthly", "16"): ("PLX-SUB-SAN", S + "PLA-PS/SAN"),
    ("monthly", "17"): ("PLX-SUB-PMMA", S + "PLA-ENG/PMMA"),
    ("monthly", "18"): ("PLX-SUB-POM", S + "PLA-ENG/POM"),
    ("monthly", "19"): ("PLX-SUB-PBT", S + "PLA-PET/PBT"),
    ("monthly", "20"): ("PLX-SUB-PC", S + "PLA-ENG/PC"),
    ("weekly", "HDPE_blow_molding"): ("PLX-VAR-HDPE", S + "PLA-PE/HDPE_BM"),
    ("weekly", "HDPE_film"): ("PLX-VAR-HDPE", S + "PLA-PE/HDPE_FILM"),
    ("weekly", "HDPE_injection_molding"): ("PLX-VAR-HDPE", S + "PLA-PE/HDPE_IM"),
    ("weekly", "HDPE_pipe"): ("PLX-VAR-HDPE", S + "PLA-PE/HDPE_PIPE"),
    ("weekly", "LDPE_film"): ("PLX-VAR-LDPE", S + "PLA-PE/LDPE_FILM"),
    ("weekly", "RLDPE_film"): ("PLX-SUB-RLDPE", S + "PLA-RCY/RLDPE_FILM"),
    ("weekly", "LLDPE_c4"): ("PLX-VAR-LLDPE", S + "PLA-PE/LLDPE_BUTENE"),
    ("weekly", "LLDPE_c6"): ("PLX-VAR-LLDPE", S + "PLA-PE/LLDPE_HEXENE"),
    ("weekly", "LDPE_general_purpose"): ("PLX-VAR-LDPE", S + "PLA-PE/LDPE_FILM_GP"),
    ("weekly", "PP_co_polymer_injection_molding"): ("PLX-VAR-PP-ICP", S + "PLA-PP/PP_BLOCK_COPO"),
    ("weekly", "PP_homo_polymer_fiber"): ("PLX-VAR-PP-HOMO", S + "PLA-PP/PP_HOMO_FIBRE"),
    ("weekly", "PP_homo_polymer_injection_molding"): ("PLX-VAR-PP-HOMO", S + "PLA-PP/PP_HOMO_IM"),
    ("weekly", "RPP_im"): ("PLX-SUB-RPP", S + "PLA-RCY/RPP"),
    ("weekly", "PPR"): ("PLX-VAR-PP-RCP", S + "PLA-PP/PP_RANDOM_PIPE_PPR"),
    ("weekly", "GPPS"): ("PLX-VAR-GPPS", S + "PLA-PS/GPPS"),
    ("weekly", "HIPS"): ("PLX-VAR-HIPS", S + "PLA-PS/HIPS"),
    ("weekly", "EPS"): ("PLX-SUB-EPS", S + "PLA-PS/EPS"),
    ("weekly", "ABS"): ("PLX-POL-ABS", S + "PLA-PS/ABS"),
    ("weekly", "S_PVC"): ("PLX-POL-PVC", S + "PLA-PVC/PVC_SUSPENSION"),
}
UNIT = {"kg": "KGM", "t": "TNE"}
SCHEMA = """
CREATE TABLE series (series_key TEXT PRIMARY KEY, material TEXT NOT NULL, symbol TEXT NOT NULL, region TEXT, basis TEXT,
  price_type TEXT, material_state TEXT, currency TEXT, unit TEXT, frequency TEXT, source TEXT, url TEXT, name TEXT);
CREATE TABLE observations (series_key TEXT NOT NULL, period TEXT NOT NULL, value REAL NOT NULL, PRIMARY KEY (series_key, period));
"""


def import_dump(series_json, obs_json, out, known_ids):
    series, obs = json.loads(Path(series_json).read_text()), json.loads(Path(obs_json).read_text())
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)
    keys = {}
    for s in series:
        mat, sym = MAP[(s["dataset"], s["ext_id"])]
        missing = [x for x in (mat, sym) if x not in known_ids]
        if missing:
            raise SystemExit(f"price map points at ids not in the graph: {missing}")
        key = f"plasticportal:{s['dataset']}:{s['ext_id']}"
        keys[s["id"]] = key
        # short terms and price type: the source's long wording would repeat in every row an agent reads
        weekly = s["dataset"] == "weekly"
        con.execute("INSERT INTO series VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            key, mat, sym, "EU-CEE", "CEE delivered" if weekly else "Central Europe",
            "avg market price" if weekly else "avg buy price", "recycled" if mat in ("PLX-SUB-RLDPE", "PLX-SUB-RPP") else "virgin",
            s["currency"], UNIT.get(s["unit"], s["unit"]), s["dataset"], s["origin"], s["canonical_url"], s["name"]))
    con.executemany("INSERT INTO observations VALUES (?,?,?)", [(keys[o["series_id"]], o["period_key"], round(o["value"], 4)) for o in obs])
    con.commit()
    n = con.execute("SELECT count(*) FROM observations").fetchone()[0]
    con.close()
    tmp.replace(out)
    return len(keys), n
