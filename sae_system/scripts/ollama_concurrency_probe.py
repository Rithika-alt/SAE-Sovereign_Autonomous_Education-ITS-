"""Does the local Ollama server actually run requests concurrently?

Standalone diagnostic — not imported by the app and changes no configuration.
Fires N identical short prompts at once (N = 1, 3, 6 by default, matching the
app's own fan-out: 3 workers, 6 lesson sections) and compares the wall-clock
time of the batch with the sum of Ollama's *own* per-request timings.

    serialization ratio = sum(server total_duration) / batch wall time

    ~1.0  -> the server worked on one request at a time (requests queued)
    ~N    -> the server really ran them in parallel

Per request, queue_wait ~= client wall - server total_duration (time spent
waiting for the server's slot, plus HTTP overhead).

Usage (from sae_system/):
    py -3.11 scripts/ollama_concurrency_probe.py
    py -3.11 scripts/ollama_concurrency_probe.py --sizes 1,3 --tokens 32
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import OLLAMA_BASE_URL, OLLAMA_MODEL  # noqa: E402

PROMPT = "In exactly three short sentences, explain what clustering is in machine learning."
NS = 1e9


def _guard_local(base_url: str) -> None:
    # Same sovereignty rule the agents enforce: never talk to a non-local LLM.
    if not (base_url.startswith("http://localhost") or base_url.startswith("http://127.0.0.1")):
        sys.exit(f"Refusing non-local OLLAMA_BASE_URL: {base_url}")


def _one_request(base_url: str, model: str, tokens: int, timeout: float) -> Dict:
    t0 = time.perf_counter()
    start_epoch = time.time()
    try:
        r = requests.post(
            f"{base_url}/api/chat",
            json={
                "model": model,
                "stream": False,
                "messages": [{"role": "user", "content": PROMPT}],
                "options": {"num_predict": tokens, "temperature": 0},
            },
            timeout=timeout,
        )
        r.raise_for_status()
        d = r.json()
    except Exception as exc:  # report, don't crash the whole probe
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                "wall_s": time.perf_counter() - t0, "start_epoch": start_epoch}
    wall = time.perf_counter() - t0
    total = d.get("total_duration", 0) / NS
    load = d.get("load_duration", 0) / NS
    prompt_eval = d.get("prompt_eval_duration", 0) / NS
    gen = d.get("eval_duration", 0) / NS
    # NOTE: Ollama's total_duration is measured from when the request was
    # received, so it INCLUDES time spent queued behind other requests. Summing
    # it across a batch double-counts the queue. "busy" is the compute actually
    # done for this request and is what must be summed to detect parallelism.
    busy = load + prompt_eval + gen
    return {
        "ok": True,
        "wall_s": wall,
        "server_total_s": total,
        "busy_s": busy,
        "load_s": load,
        "prompt_eval_s": prompt_eval,
        "eval_s": gen,
        "eval_count": d.get("eval_count", 0),
        # time inside the server before compute started (queued behind others)
        "server_queue_s": max(0.0, total - busy),
        # time outside the server: connect + HTTP + JSON, on the client side
        "client_overhead_s": max(0.0, wall - total),
        "start_epoch": start_epoch,
    }


def _connect_overhead(base_url: str, repeats: int = 3) -> None:
    """Time a trivial GET on a fresh connection via 'localhost' vs '127.0.0.1'.

    On Windows, 'localhost' can resolve to ::1 first; if Ollama only listens on
    127.0.0.1 each new connection pays a fallback delay before succeeding.
    """
    import socket
    from urllib.parse import urlparse

    u = urlparse(base_url)
    port = u.port or 11434
    try:
        order = [ai[4][0] for ai in socket.getaddrinfo(u.hostname, port, type=socket.SOCK_STREAM)]
        print(f"  '{u.hostname}' resolves (in order) to: {', '.join(order)}")
    except Exception as exc:
        print(f"  could not resolve {u.hostname}: {exc}")
    for host in dict.fromkeys([u.hostname, "127.0.0.1"]):
        times = []
        for _ in range(repeats):
            t0 = time.perf_counter()
            try:
                requests.get(f"http://{host}:{port}/api/version", timeout=10)
                times.append((time.perf_counter() - t0) * 1000)
            except Exception:
                times.append(float("nan"))
        print(f"  GET /api/version via {host:<10}: " + ", ".join(f"{t:.0f} ms" for t in times))


def _processor_info(base_url: str) -> str:
    try:
        models = requests.get(f"{base_url}/api/ps", timeout=5).json().get("models", [])
    except Exception as exc:
        return f"(could not read /api/ps: {exc})"
    if not models:
        return "(no model reported loaded)"
    parts = []
    for m in models:
        size, vram = m.get("size", 0), m.get("size_vram", 0)
        where = "100% GPU" if size and vram >= size else ("CPU only" if not vram else f"{vram / size:.0%} GPU / rest CPU")
        parts.append(f"{m.get('name')}: {size / 1e9:.1f} GB loaded, {where}")
    return "; ".join(parts)


def run_batch(base_url: str, model: str, n: int, tokens: int, timeout: float) -> List[Dict]:
    with ThreadPoolExecutor(max_workers=n) as pool:
        futures = [pool.submit(_one_request, base_url, model, tokens, timeout) for _ in range(n)]
        return [f.result() for f in futures]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sizes", default="1,3,6", help="comma-separated concurrency levels (default 1,3,6)")
    ap.add_argument("--tokens", type=int, default=48, help="max tokens to generate per request (default 48)")
    ap.add_argument("--timeout", type=float, default=600, help="per-request timeout in seconds")
    args = ap.parse_args()

    base_url, model = OLLAMA_BASE_URL.rstrip("/"), OLLAMA_MODEL
    _guard_local(base_url)
    sizes = [int(s) for s in args.sizes.split(",") if s.strip()]

    print(f"Ollama: {base_url}   model: {model}   max tokens/request: {args.tokens}")

    print("\n[warm-up] loading the model so cold-load time doesn't contaminate the batches…")
    w = _one_request(base_url, model, args.tokens, args.timeout)
    if not w["ok"]:
        print(f"  warm-up failed: {w['error']}")
        return 1
    print(f"  warm-up wall {w['wall_s']:.1f}s (model load {w['load_s']:.1f}s, "
          f"{w['eval_count']} tokens in {w['eval_s']:.1f}s = {w['eval_count'] / max(w['eval_s'], 1e-9):.1f} tok/s)")
    print(f"  processor: {_processor_info(base_url)}")

    print("\n[connection overhead] fresh-connection latency of a trivial request")
    _connect_overhead(base_url)

    rows = []
    for n in sizes:
        print(f"\n[batch of {n}] firing {n} request(s) simultaneously…")
        t0 = time.perf_counter()
        results = run_batch(base_url, model, n, args.tokens, args.timeout)
        batch_wall = time.perf_counter() - t0
        ok = [r for r in results if r["ok"]]
        ordered = sorted(results, key=lambda x: x["wall_s"])
        prev = 0.0
        for i, r in enumerate(ordered, 1):
            if r["ok"]:
                print(f"  #{i}: done at {r['wall_s']:6.1f}s (+{r['wall_s'] - prev:4.1f}s after previous) | "
                      f"compute {r['busy_s']:4.1f}s | queued in server {r['server_queue_s']:5.1f}s | "
                      f"client overhead {r['client_overhead_s']:3.1f}s")
                prev = r["wall_s"]
            else:
                print(f"  #{i}: FAILED after {r['wall_s']:.1f}s — {r['error']}")
        if not ok:
            continue
        busy_sum = sum(r["busy_s"] for r in ok)
        ratio = busy_sum / batch_wall if batch_wall else 0.0
        rows.append((n, len(ok), batch_wall, busy_sum, ratio, max(r["server_queue_s"] for r in ok)))
        print(f"  -> batch wall {batch_wall:.1f}s, sum of compute {busy_sum:.1f}s, "
              f"parallelism ratio {ratio:.2f} (~1.0 = serialized, ~{n}.0 = fully parallel)")

    print("\nSummary")
    print(f"{'N':>3} {'ok':>3} {'batch wall':>11} {'sum compute':>12} {'ratio':>6} {'max server queue':>17}")
    for n, okc, bw, bs, ratio, mq in rows:
        print(f"{n:>3} {okc:>3} {bw:>10.1f}s {bs:>11.1f}s {ratio:>6.2f} {mq:>16.1f}s")

    multi = [r for r in rows if r[0] > 1]
    if multi:
        avg = sum(r[4] for r in multi) / len(multi)
        # Serialized => ratio stays near 1 (a bit under, from client overhead)
        # no matter how many requests are in flight; parallel => it grows with N.
        verdict = ("SERIALIZED — the server processes one request at a time; extra client threads only add queue wait."
                   if avg < 1.3 else
                   "PARALLEL — the server is overlapping requests.")
        print(f"\nVerdict (mean parallelism ratio over N>1 = {avg:.2f}): {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
