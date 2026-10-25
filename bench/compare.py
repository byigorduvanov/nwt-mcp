"""Compare two runs question by question and write one JSON for the report page. Usage: compare.py <before> <after> <out.json>"""
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(tag):
    return {r["id"]: r for r in map(json.loads, (ROOT / "bench/runs" / tag / "results.jsonl").read_text().splitlines())}


def summary(rows):
    rs = list(rows.values())
    return {"n": len(rs), "ok": sum(r["ok"] for r in rs), "lang_ok": sum(r.get("lang_ok", True) for r in rs),
            "tool_errors": sum(len(r["tool_errors"]) for r in rs), "calls": round(st.mean(r["n_calls"] for r in rs), 2),
            "calls_ge6": sum(r["n_calls"] >= 6 for r in rs), "result_tok": round(st.mean(r["tool_result_tokens"] for r in rs)),
            "cost": round(sum(r["cost"] or 0 for r in rs), 2), "sec_median": round(st.median(r["ms"] for r in rs) / 1000, 1),
            "by_model": {m: {"n": sum(1 for r in rs if r["model"] == m), "ok": sum(r["ok"] for r in rs if r["model"] == m),
                             "cost": round(sum(r["cost"] or 0 for r in rs if r["model"] == m), 2),
                             "calls": round(st.mean(r["n_calls"] for r in rs if r["model"] == m), 2)} for m in ("haiku", "sonnet")},
            "by_cat": {c: {"n": sum(1 for r in rs if r["cat"] == c), "ok": sum(r["ok"] for r in rs if r["cat"] == c)}
                       for c in sorted({r["cat"] for r in rs})}}


def main():
    a, b = load(sys.argv[1]), load(sys.argv[2])
    rows = []
    for qid in sorted(a):
        x, y = a[qid], b.get(qid)
        rows.append({"id": qid, "cat": x["cat"], "lang": x["lang"], "persona": x["persona"], "model": x["model"], "q": x["q"],
                     "before": {k: x[k] for k in ("ok", "n_calls", "tool_result_tokens", "cost", "ms")} | {"errors": len(x["tool_errors"]), "lang_ok": x.get("lang_ok", True), "answer": x["answer"], "calls": x["calls"]},
                     "after": y and {k: y[k] for k in ("ok", "n_calls", "tool_result_tokens", "cost", "ms")} | {"errors": len(y["tool_errors"]), "lang_ok": y.get("lang_ok", True), "answer": y["answer"], "calls": y["calls"]}})
    out = {"before": summary(a), "after": summary(b), "rows": rows}
    Path(sys.argv[3]).write_text(json.dumps(out, ensure_ascii=False))
    for k in ("before", "after"):
        s = out[k]
        print(k, {x: s[x] for x in ("n", "ok", "lang_ok", "tool_errors", "calls", "calls_ge6", "result_tok", "cost", "sec_median")}, s["by_model"])
    print("changed:", [(r["id"], r["before"]["ok"], r["after"] and r["after"]["ok"]) for r in rows if r["after"] and r["before"]["ok"] != r["after"]["ok"]])


if __name__ == "__main__":
    main()
