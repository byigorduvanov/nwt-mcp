"""Summarise a run: pass rate by category / model / language, calls, tool errors, tokens, cost, time. Usage: report.py <tag> [<tag2>]"""
import json
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(tag):
    return [json.loads(l) for l in (ROOT / "bench/runs" / tag / "results.jsonl").read_text().splitlines()]


def table(rows, key):
    by = defaultdict(list)
    for r in rows:
        by[key(r)].append(r)
    out = ["| group | n | pass | calls (mean) | tool errors | result tok (mean) | $ total | s (median) |", "|---|---|---|---|---|---|---|---|"]
    for k, rs in sorted(by.items()):
        out.append(f"| {k} | {len(rs)} | {sum(r['ok'] for r in rs)}/{len(rs)} | {st.mean(r['n_calls'] for r in rs):.1f} | "
                   f"{sum(len(r['tool_errors']) for r in rs)} | {st.mean(r['tool_result_tokens'] for r in rs):.0f} | "
                   f"{sum(r['cost'] or 0 for r in rs):.2f} | {st.median(r['ms'] for r in rs) / 1000:.0f} |")
    return "\n".join(out)


def main():
    rows = load(sys.argv[1])
    print(f"# Run {sys.argv[1]}: {sum(r['ok'] for r in rows)}/{len(rows)} passed, ${sum(r['cost'] or 0 for r in rows):.2f}\n")
    for name, key in (("model", lambda r: r["model"]), ("category", lambda r: r["cat"]), ("language", lambda r: r["lang"])):
        print(f"## By {name}\n\n{table(rows, key)}\n")
    tools = Counter(c["name"] for r in rows for c in r["calls"])
    print("## Tool use\n\n" + ", ".join(f"{k}: {v}" for k, v in tools.most_common()) + "\n")
    print("## Failures and tool errors\n")
    for r in rows:
        if not r["ok"] or r["tool_errors"] or r["is_error"]:
            print(f"- **{r['id']}** {r['model']} [{r['cat']}] {r['q']}\n  - why: {'; '.join(r['why'])}; calls: "
                  f"{', '.join(c['name'] + json.dumps(c['input'], ensure_ascii=False) for c in r['calls'])}\n"
                  f"  - tool errors: {r['tool_errors']}\n  - answer: {r['answer'][:500]!r}")


if __name__ == "__main__":
    main()
