"""Run each question as an isolated headless Claude Code session that sees only the nwt-data MCP (no files, no shell,
no user settings, plugins or hooks), then grade it. Usage: uv run python bench/run.py <tag> [--workers 6] [--only q001 q002]"""
import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD = ("You are the market-data assistant of a plastics company. Answer using the nwt-data tools only, never from memory. "
         "Be concise. Reply in the language of the question.")
MCP = {"mcpServers": {"nwt-data": {"command": str(Path.home() / ".local/bin/uv"), "args": ["run", "--directory", str(ROOT), "nwt-mcp"]}}}
ENV = {k: os.environ[k] for k in ("HOME", "USER", "LOGNAME", "SHELL", "TMPDIR") if k in os.environ}
CLAUDE = shutil.which("claude")  # resolved before env -i style isolation drops nvm from PATH
ENV |= {"PATH": f"{Path(CLAUDE).parent}:{Path.home()}/.local/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin", "LANG": "en_US.UTF-8"}


def numbers(text):
    """Every number in the text, read both ways where a comma is ambiguous (1,261 = 1261; 1,48 = 1.48)."""
    out = []
    for m in re.findall(r"-?\d[\d\s  ,.]*\d|-?\d", text):
        s = re.sub(r"[\s  ]", "", m).rstrip(".,")
        for cand in {s.replace(",", ""), s.replace(".", "").replace(",", "."), s.replace(",", ".")}:
            try:
                out.append(float(cand))
            except ValueError:
                pass
    return out


def grade(answer, check):
    # subscript digits (C₂H₄) count as digits
    a = (answer or "").translate(str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789"))
    a = re.sub(r"(?<=\d) (?=\d)", "", a)  # HS code "3901 20" = 390120
    low, why = a.lower(), []
    if check.get("nodata"):
        ok = any(w.lower() in low for w in ["no data", "no price", "not available", "no observ", "нет данн", "нет цен", "немає", "нема ",
                                            "отсутств", "відсутн", "keine", "brak", "без значен", "no values", "не содерж", "не має",
                                            "doesn't have", "does not have", "don't have", "no recorded", "not have", "unavailable", "no actual",
                                            "не нашёл", "не нашел", "в базе нет", "нет ни одного", "0 точек", "не знайш", "isn't in", "not in the",
                                            "can't give", "cannot give", "couldn't find", "could not find", "0 data points", "zero observations", "нуль спостережень", "0 наблюдений", "не могу указать", "не можу назвати", "liegen", "keine preise"])
        why.append("says no data" if ok else "did not say there is no data")
        return ok, why
    ok = True
    if check.get("any"):
        hit = any(w.lower() in low for w in check["any"])
        ok &= hit
        why.append("any ok" if hit else f"missing any of {check['any'][:4]}")
    for w in check.get("all", []):
        if w.lower() not in low:
            ok = False
            why.append(f"missing {w}")
    if check.get("num"):
        found = numbers(a)
        hit = any(abs(f - e) <= max(abs(e) * 0.006, 0.006) for e in check["num"] if e is not None for f in found)
        ok &= hit
        why.append("number ok" if hit else f"expected one of {[round(e, 3) for e in check['num'] if e is not None][:4]}")
    return ok, why


def reply_lang(text):
    """latin / uk / ru by letters; inline code and bold markers are ignored."""
    t = re.sub(r"`[^`]*`|\*\*", "", text or "")
    cyr, lat = len(re.findall(r"[а-яА-ЯёЁіїєґІЇЄҐ]", t)), len(re.findall(r"[a-zA-Z]", t))
    if cyr < lat * 0.5:
        return "latin"
    uk, ru = len(re.findall(r"[іїєґІЇЄҐ]", t)), len(re.findall(r"[ыэъёЫЭЪЁ]", t))
    return "uk" if uk > ru else "ru" if ru > uk else "cyr?"


def run_one(item, model, outdir):
    cwd = tempfile.mkdtemp(prefix="nwtq-")
    cmd = [CLAUDE, "-p", item["text"], "--model", model, "--output-format", "stream-json", "--verbose", "--no-session-persistence",
           "--permission-mode", "bypassPermissions", "--strict-mcp-config", "--mcp-config", json.dumps(MCP), "--tools", "",
           "--setting-sources", "project,local", "--max-budget-usd", "0.6", "--append-system-prompt", GUARD]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd, env=ENV, capture_output=True, text=True, timeout=300)
        lines, err = p.stdout.splitlines(), p.stderr[-500:]
    except subprocess.TimeoutExpired as e:
        lines, err = (e.stdout or b"").decode(errors="replace").splitlines() if isinstance(e.stdout, bytes) else (e.stdout or "").splitlines(), "timeout"
    (outdir / f"{item['id']}.jsonl").write_text("\n".join(lines))
    calls, tool_errors, result_chars, final = [], [], 0, {}
    for ln in lines:
        try:
            ev = json.loads(ln)
        except json.JSONDecodeError:
            continue
        msg = ev.get("message") or {}
        for b in msg.get("content") or [] if isinstance(msg.get("content"), list) else []:
            if b.get("type") == "tool_use":
                calls.append({"name": b["name"].replace("mcp__nwt-data__", ""), "input": b.get("input")})
            elif b.get("type") == "tool_result":
                c = b.get("content")
                text = "".join(x.get("text", "") for x in c) if isinstance(c, list) else str(c or "")
                result_chars += len(text)
                if b.get("is_error"):
                    tool_errors.append(text[:300])
        if ev.get("type") == "result":
            final = ev
    answer = final.get("result", "")
    ok, why = grade(answer, item["check"])
    row = {"id": item["id"], "cat": item["cat"], "lang": item["lang"], "persona": item["persona"], "model": model, "q": item["text"],
           "ok": ok, "lang_ok": reply_lang(answer) == {"en": "latin", "de": "latin", "pl": "latin"}.get(item["lang"], item["lang"]),
           "soft": bool(item["check"].get("soft")), "why": why, "answer": answer, "calls": calls, "n_calls": len(calls),
           "tool_errors": tool_errors, "tool_result_tokens": round(result_chars / 4), "turns": final.get("num_turns"),
           "cost": final.get("total_cost_usd"), "ms": final.get("duration_ms") or round((time.time() - t0) * 1000),
           "is_error": final.get("is_error", True), "subtype": final.get("subtype"), "stderr": err if not final else ""}
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    qs = json.load(open(ROOT / "bench/questions.json"))
    if a.only:
        qs = [x for x in qs if x["id"] in a.only]
    outdir = ROOT / "bench/runs" / a.tag
    outdir.mkdir(parents=True, exist_ok=True)
    res = outdir / "results.jsonl"
    done = {json.loads(l)["id"] for l in res.read_text().splitlines()} if res.exists() else set()
    todo = [(x, "sonnet" if int(x["id"][1:]) % 2 == 0 else "haiku") for x in qs if x["id"] not in done]
    with ThreadPoolExecutor(a.workers) as ex, res.open("a") as f:
        for row in ex.map(lambda t: run_one(t[0], t[1], outdir), todo):
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(f"{row['id']} {row['model']:6} {'OK ' if row['ok'] else 'BAD'} calls={row['n_calls']} err={len(row['tool_errors'])} "
                  f"${row['cost'] or 0:.3f} {row['ms'] / 1000:.0f}s {'; '.join(row['why'])}", flush=True)


if __name__ == "__main__":
    main()
