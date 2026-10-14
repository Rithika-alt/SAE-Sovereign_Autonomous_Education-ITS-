"""Read-only report over the ``perf_span`` events in data/events.jsonl.

    py -3.11 scripts/perf_report.py                # last hour
    py -3.11 scripts/perf_report.py --last 15m     # or 2h, 1d, ...
    py -3.11 scripts/perf_report.py --all --top 15

Layout (priority order):
  A. Clicks that NEVER reached Ollama (cached views, navigation) — the
     day-to-day latency. Shows where each click's time went and how much is
     UNEXPLAINED by any instrumented stage.
  B. Clicks that did call Ollama (cold generation) — reported separately.
  C. Ollama calls: wall vs compute vs server queue vs client overhead,
     parallelism ratio per batch, cold loads.
  D. Contention: work from earlier clicks still running (superseded) and what
     it made later calls queue behind.
  E. events.jsonl read cost (grows with every event).

A "click" is a chain of Streamlit reruns: a run that ends with st.rerun()
(outcome RerunException / ended_by_next_run) and is followed within
--gap-ms by another run of the same session counts as one click.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

DEFAULT_LOG = Path(__file__).resolve().parent.parent / "data" / "events.jsonl"

# Spans that wrap other spans (or the whole run) — never counted as "leaf" work.
STRUCTURAL = {"rerun_total", "rerun.page", "rerun.sidebar", "rerun.auth_gate", "rerun.import_pages"}
CHAIN_OUTCOMES = {"RerunException", "ended_by_next_run"}
OLLAMA = "ollama.http"


def is_structural(stage: str) -> bool:
    """Wrapper spans and run-timeline segments: never counted as leaf work."""
    return stage in STRUCTURAL or stage.startswith("rerun.segment:")


# --------------------------------------------------------------------------
# Loading / grouping
# --------------------------------------------------------------------------

def parse_window(text: str) -> timedelta:
    m = re.fullmatch(r"\s*(\d+)\s*([smhd])\s*", text)
    if not m:
        raise argparse.ArgumentTypeError("use e.g. 30m, 2h, 1d")
    return timedelta(**{{"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}[m.group(2)]: int(m.group(1))})


def load_spans(path: Path, since: Optional[datetime] = None, student: Optional[str] = None) -> List[Dict]:
    spans: List[Dict] = []
    if not path.exists():
        return spans
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("event_type") != "perf_span":
                continue
            if student and r.get("student_id") != student:
                continue
            if since is not None:
                try:
                    if datetime.fromisoformat(r["timestamp"]) < since:
                        continue
                except (KeyError, ValueError):
                    continue
            spans.append(r)
    return spans


def pct(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, max(0, int(round(p / 100 * (len(s) - 1)))))]


def build_runs(spans: Iterable[Dict]) -> List[Dict]:
    by_run: Dict[str, List[Dict]] = defaultdict(list)
    for s in spans:
        if s.get("run_id"):
            by_run[s["run_id"]].append(s)
    runs = []
    for rid, ss in by_run.items():
        total = next((s for s in ss if s["stage"] == "rerun_total"), None)
        start = total["t_start_ms"] if total else min(s["t_start_ms"] for s in ss)
        end = (total["t_start_ms"] + total["duration_ms"]) if total else max(s["t_start_ms"] + s["duration_ms"] for s in ss)
        runs.append({
            "id": rid, "spans": ss, "total": total,
            "session": next((s.get("session_id") for s in ss if s.get("session_id")), ""),
            "start": start, "end": end,
            "outcome": (total or {}).get("outcome", "(unfinished)"),
            "main_thread": (total or ss[0]).get("thread"),
        })
    return sorted(runs, key=lambda r: r["start"])


def build_clicks(runs: List[Dict], gap_ms: float = 3000) -> List[Dict]:
    clicks: List[Dict] = []
    for r in runs:
        prev = clicks[-1]["runs"][-1] if clicks else None
        if prev and prev["outcome"] in CHAIN_OUTCOMES and prev["session"] == r["session"] and r["start"] - prev["end"] <= gap_ms:
            clicks[-1]["runs"].append(r)
        else:
            clicks.append({"runs": [r]})
    for c in clicks:
        c["start"], c["end"] = c["runs"][0]["start"], c["runs"][-1]["end"]
        c["latency_ms"] = c["end"] - c["start"]
        c["spans"] = [s for r in c["runs"] for s in r["spans"]]
        c["ollama"] = [s for s in c["spans"] if s["stage"] == OLLAMA]
        c["pages"] = [next((s.get("page") for s in r["spans"] if s["stage"] == "rerun.page"), None)
                      or (r["total"] or {}).get("page", "?") for r in c["runs"]]
    return clicks


def union_ms(intervals: List[Tuple[float, float]]) -> float:
    total, cur_s, cur_e = 0.0, None, None
    for s, e in sorted(intervals):
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                total += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    return total + (cur_e - cur_s if cur_e is not None else 0.0)


def breakdown(run: Dict) -> Dict[str, float]:
    """Where one rerun's time went. 'unexplained' = time inside the page that
    no instrumented stage on the main thread accounts for."""
    def dur(stage: str) -> float:
        return sum(s["duration_ms"] for s in run["spans"] if s["stage"] == stage)

    total = run["end"] - run["start"]
    page = next((s for s in run["spans"] if s["stage"] == "rerun.page"), None)
    leaf = [(s["t_start_ms"], s["t_start_ms"] + s["duration_ms"]) for s in run["spans"]
            if not is_structural(s["stage"]) and s.get("thread") == run["main_thread"]
            and (page is None or (s["t_start_ms"] >= page["t_start_ms"] - 1
                                  and s["t_start_ms"] + s["duration_ms"] <= page["t_start_ms"] + page["duration_ms"] + 1))]
    page_ms = page["duration_ms"] if page else 0.0
    instrumented = min(union_ms(leaf), page_ms)
    known = dur("rerun.auth_gate") + dur("rerun.sidebar") + dur("rerun.import_pages") + page_ms
    segments: Dict[str, float] = defaultdict(float)
    for sp in run["spans"]:
        if sp["stage"].startswith("rerun.segment:"):
            segments[sp["stage"].split(":", 1)[1]] += sp["duration_ms"]
    return {
        "segments": dict(segments),
        "total": total, "auth": dur("rerun.auth_gate"), "sidebar": dur("rerun.sidebar"),
        "imports": dur("rerun.import_pages"), "page": page_ms,
        "page_instrumented": instrumented, "page_unexplained": max(0.0, page_ms - instrumented),
        "other": max(0.0, total - known),
    }


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------

def fmt_ms(v: float) -> str:
    return f"{v / 1000:.1f}s" if v >= 10_000 else f"{v:,.0f}ms"


def hhmmss(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%H:%M:%S")


def stage_table(spans: List[Dict], n_clicks: int, top: int, include_structural: bool = False) -> List[str]:
    by_stage: Dict[str, List[float]] = defaultdict(list)
    clicks_with: Dict[str, set] = defaultdict(set)
    for s in spans:
        if not include_structural and is_structural(s["stage"]):
            continue
        by_stage[s["stage"]].append(s["duration_ms"])
        clicks_with[s["stage"]].add(s.get("_click"))
    rows = sorted(by_stage.items(), key=lambda kv: -sum(kv[1]))[:top]
    out = [f"    {'stage':<26}{'in clicks':>10}{'calls/click':>12}{'mean':>10}{'p95':>10}{'total/click':>13}"]
    for stage, v in rows:
        out.append(f"    {stage:<26}{len(clicks_with[stage]):>5}/{n_clicks:<4}{len(v) / n_clicks:>12.1f}"
                   f"{fmt_ms(sum(v) / len(v)):>10}{fmt_ms(pct(v, 95)):>10}{fmt_ms(sum(v) / n_clicks):>13}")
    return out


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------

def section_clicks(title: str, clicks: List[Dict], top: int, per_click: int) -> List[str]:
    out = [title, "=" * len(title)]
    if not clicks:
        return out + ["  (none in this window)", ""]
    lat = [c["latency_ms"] for c in clicks]
    out.append(f"  {len(clicks)} clicks | latency p50 {fmt_ms(pct(lat, 50))}  p95 {fmt_ms(pct(lat, 95))}  max {fmt_ms(max(lat))}")
    out.append("")
    out.append("  Slowest clicks (ms): page chain | [auth sidebar imports page(instrumented + UNEXPLAINED) other]")
    for c in sorted(clicks, key=lambda c: -c["latency_ms"])[:per_click]:
        bs = [breakdown(r) for r in c["runs"]]
        agg = {k: sum(b[k] for b in bs) for k in bs[0] if k != "segments"}
        segs: Dict[str, float] = defaultdict(float)
        for b in bs:
            for name, ms in b["segments"].items():
                segs[name] += ms
        top_segs = ", ".join(f"{n} {ms:.0f}" for n, ms in sorted(segs.items(), key=lambda kv: -kv[1])[:3] if ms >= 100)
        out.append(
            f"   {hhmmss(c['start'])}  {fmt_ms(c['latency_ms']):>8}  {'>'.join(map(str, c['pages'])):<28} "
            f"[auth {agg['auth']:.0f} | sidebar {agg['sidebar']:.0f} | imports {agg['imports']:.0f} | "
            f"page {agg['page']:.0f} ({agg['page_instrumented']:.0f} + UNEXPLAINED {agg['page_unexplained']:.0f}) | other {agg['other']:.0f}]"
            + (f"\n{'':>13}slowest startup segments (ms): {top_segs}" if top_segs else "")
        )
    n = len(clicks)
    tot = {k: sum(breakdown(r)[k] for c in clicks for r in c["runs"]) for k in
           ("auth", "sidebar", "imports", "page", "page_instrumented", "page_unexplained", "other")}
    out += ["", "  Average click, by part (ms): " + ", ".join(f"{k} {v / n:.0f}" for k, v in tot.items()), ""]
    flat = [dict(s, _click=i) for i, c in enumerate(clicks) for s in c["spans"]]
    out.append("  Stages ranked by total time per click (nested stages overlap, so don't add them up):")
    out += stage_table(flat, n, top)
    out.append("")
    return out


def section_ollama(clicks_all: List[Dict]) -> List[str]:
    title = "C. Ollama calls (every HTTP request, retries included)"
    out = [title, "=" * len(title)]
    calls = [s for c in clicks_all for s in c["ollama"]]
    if not calls:
        return out + ["  (no ollama.http spans in this window)", ""]
    by_purpose: Dict[str, List[Dict]] = defaultdict(list)
    for s in calls:
        by_purpose[s.get("purpose", "?")].append(s)
    out.append(f"    {'purpose':<22}{'n':>4}{'wall p50':>10}{'wall p95':>10}{'compute p50':>12}{'queue p50':>10}{'queue p95':>10}{'overhead p50':>13}{'tok/s':>7}")
    for purpose, ss in sorted(by_purpose.items(), key=lambda kv: -sum(s["duration_ms"] for s in kv[1])):
        g = lambda k: [s[k] for s in ss if isinstance(s.get(k), (int, float))]
        out.append(f"    {purpose:<22}{len(ss):>4}{fmt_ms(pct([s['duration_ms'] for s in ss], 50)):>10}"
                   f"{fmt_ms(pct([s['duration_ms'] for s in ss], 95)):>10}{fmt_ms(pct(g('compute_ms'), 50)):>12}"
                   f"{fmt_ms(pct(g('server_queue_ms'), 50)):>10}{fmt_ms(pct(g('server_queue_ms'), 95)):>10}"
                   f"{fmt_ms(pct(g('client_overhead_ms'), 50)):>13}{pct(g('tokens_per_s'), 50):>7.1f}")
    over = [s["client_overhead_ms"] for s in calls if isinstance(s.get("client_overhead_ms"), (int, float))]
    cold = [s for s in calls if (s.get("load_ms") or 0) > 1000]
    out += ["",
            f"  client overhead (wall - server total): p50 {fmt_ms(pct(over, 50))}, max {fmt_ms(max(over) if over else 0)}"
            + ("   <-- >1s: connection problem (e.g. localhost resolving to ::1 first)" if over and pct(over, 50) > 1000 else ""),
            f"  calls that waited on a cold model load (load > 1s): {len(cold)}/{len(calls)}"
            "  (Ollama reports the load wait on every request queued during it, so 'compute' is inflated for these)",
            f"  max concurrent calls from this process: {max(s.get('inflight_at_start', 1) for s in calls)}"]

    # Parallelism per overlapping batch: sum(compute) / wall span. ~1 = serialized.
    calls_sorted = sorted(calls, key=lambda s: s["t_start_ms"])
    batches: List[List[Dict]] = []
    for s in calls_sorted:
        if batches and s["t_start_ms"] <= max(x["t_start_ms"] + x["duration_ms"] for x in batches[-1]):
            batches[-1].append(s)
        else:
            batches.append([s])
    multi = [b for b in batches if len(b) > 1 and all(isinstance(x.get("compute_ms"), (int, float)) for x in b)]
    if multi:
        out += ["", "  Overlapping batches (parallelism ratio = sum(compute) / wall span; ~1.0 = serialized, ~N = parallel):"]
        for b in multi[:8]:
            span_ms = max(x["t_start_ms"] + x["duration_ms"] for x in b) - min(x["t_start_ms"] for x in b)
            ratio = sum(x["compute_ms"] for x in b) / span_ms if span_ms else 0.0
            out.append(f"   {hhmmss(b[0]['t_start_ms'])}  {len(b)} calls  wall {fmt_ms(span_ms):>8}  ratio {ratio:.2f}  "
                       f"({', '.join(sorted({x.get('purpose', '?') for x in b}))})")
    return out + [""]


def section_contention(clicks_all: List[Dict]) -> List[str]:
    title = "D. Contention: work nobody is waiting for any more"
    out = [title, "=" * len(title)]
    spans = [s for c in clicks_all for s in c["spans"]]
    sup = defaultdict(lambda: [0, 0.0])
    for s in spans:
        if s.get("superseded") and not is_structural(s["stage"]):
            sup[s["stage"]][0] += 1
            sup[s["stage"]][1] += s["duration_ms"]
    if sup:
        out.append("  Spans that finished AFTER a newer rerun had started (orphaned work):")
        for stage, (n, ms) in sorted(sup.items(), key=lambda kv: -kv[1][1]):
            out.append(f"    {stage:<26}{n:>4} spans  {fmt_ms(ms):>9} total")
    else:
        out.append("  No superseded spans recorded.")
    calls = sorted((s for s in spans if s["stage"] == OLLAMA), key=lambda s: s["t_start_ms"])
    waits = []
    for x in calls:
        q = x.get("server_queue_ms") or 0
        if q < 500:
            continue
        ahead = [y for y in calls if y is not x and y["t_start_ms"] < x["t_start_ms"] + 50
                 and y["t_start_ms"] + y["duration_ms"] > x["t_start_ms"] and y.get("run_id") != x.get("run_id")]
        if ahead:
            waits.append((q, x, ahead))
    if waits:
        out += ["", "  Calls that queued behind Ollama work started by a DIFFERENT rerun:"]
        for q, x, ahead in sorted(waits, key=lambda w: -w[0])[:8]:
            out.append(f"    {hhmmss(x['t_start_ms'])}  {x.get('purpose', '?'):<20} queued {fmt_ms(q):>8} behind "
                       + ", ".join(sorted({f"{y.get('purpose', '?')}{' (orphaned)' if y.get('superseded') else ''}" for y in ahead})))
    return out + [""]


def section_events(clicks_all: List[Dict]) -> List[str]:
    title = "E. events.jsonl read cost (every read re-parses the whole file)"
    out = [title, "=" * len(title)]
    reads = [s for c in clicks_all for s in c["spans"] if s["stage"] == "events.read_all"]
    if not reads:
        return out + ["  (no events.read_all spans)", ""]
    ms = [s["duration_ms"] for s in reads]
    size = [s.get("file_bytes", 0) for s in reads]
    out.append(f"  {len(reads)} reads | per read: mean {fmt_ms(sum(ms) / len(ms))}, p95 {fmt_ms(pct(ms, 95))}, max {fmt_ms(max(ms))} | "
               f"file {max(size) / 1024:.0f} KiB at last read")
    return out + [""]


def hints(clicks_nollm: List[Dict]) -> List[str]:
    """Plain, factual pointers into the data — not conclusions."""
    out = ["Hints for cached (no-Ollama) clicks"]
    out.append("=" * len(out[0]))
    if not clicks_nollm:
        return out + ["  (no such clicks)", ""]
    n = len(clicks_nollm)
    spans = [s for c in clicks_nollm for s in c["spans"]]

    def per_click(stage_prefix: str) -> Tuple[int, float]:
        sel = [s for s in spans if s["stage"].startswith(stage_prefix)]
        return len(sel), sum(s["duration_ms"] for s in sel) / n

    for label, prefix, why in (
        ("KnowledgeGraph constructions", "kg.init", "H6: reloaded on every construction"),
        ("events.jsonl reads", "events.read_all", "H5: whole file re-parsed per read"),
        ("Redis operations", "redis.", "H7: new client + ping per call"),
        ("progress store", "progress.", ""),
        ("disk caches", "cache.", ""),
    ):
        cnt, ms = per_click(prefix)
        out.append(f"  {label:<30}{cnt / n:>6.1f} per click   {fmt_ms(ms):>9} per click   {why}")
    sup = [s for s in spans if s.get("superseded") and not is_structural(s["stage"])]
    out.append(f"  superseded spans (orphans) seen during cached clicks: {len(sup)}   (H2/H3)")
    anim = [s for s in spans if s["stage"] == "animation.thread"]
    if anim:
        out.append(f"  animation thread still running during cached clicks: {len(anim)} span(s), longest {fmt_ms(max(s['duration_ms'] for s in anim))}   (H3)")
    return out + [""]


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def render(spans: List[Dict], gap_ms: float = 3000, top: int = 12, per_click: int = 8) -> str:
    runs = build_runs(spans)
    clicks = build_clicks(runs, gap_ms)
    nollm = [c for c in clicks if not c["ollama"]]
    llm = [c for c in clicks if c["ollama"]]
    lines = [f"perf report: {len(spans)} spans, {len(runs)} reruns, {len(clicks)} clicks "
             f"({len(nollm)} never reached Ollama, {len(llm)} did)", ""]
    lines += section_clicks("A. PRIORITY — clicks that never reached Ollama (cached views / navigation)", nollm, top, per_click)
    lines += hints(nollm)
    lines += section_clicks("B. Clicks that called Ollama (cold generation)", llm, top, per_click)
    lines += section_ollama(clicks)
    lines += section_contention(clicks)
    lines += section_events(clicks)
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--events", type=Path, default=DEFAULT_LOG, help="path to events.jsonl")
    ap.add_argument("--last", type=parse_window, default=timedelta(hours=1), help="time window (default 1h)")
    ap.add_argument("--all", action="store_true", help="ignore --last and read everything")
    ap.add_argument("--student", help="only this student_id")
    ap.add_argument("--top", type=int, default=12, help="rows in the stage tables")
    ap.add_argument("--per-click", type=int, default=8, help="slowest clicks to list per section")
    ap.add_argument("--gap-ms", type=float, default=3000, help="max gap between chained reruns of one click")
    args = ap.parse_args(argv)

    since = None if args.all else datetime.now(timezone.utc) - args.last
    spans = load_spans(args.events, since, args.student)
    if not spans:
        print("No perf_span events found in that window. Run the app (SAE_PERF_TRACE is on by default), "
              "click around, then re-run; use --all to widen the window.")
        return 1
    print(render(spans, args.gap_ms, args.top, args.per_click))
    return 0


if __name__ == "__main__":
    sys.exit(main())
