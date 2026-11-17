"""Emit before/after tables side by side.

Two separate per-arm sections make a reader do the subtraction themselves, and
the subtraction is the finding. Every table here is generated from the JSON; a
metric that was not collected prints as `--`.

    python compare.py --before before --after after --out results/_compare.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

NM = "--"
FRAME_MS = 85.333          # one 2048-sample frame at 24 kHz


def load(d: Path, arm: str, suite: str) -> dict | None:
    try:
        return json.loads((d / f"{arm}_{suite}.json").read_text())
    except Exception:                                            # noqa: BLE001
        return None


def v(cell: dict, block: str, key: str, nd: int = 0) -> str:
    x = (cell.get(block) or {}).get(key)
    return NM if x is None else f"{x:.{nd}f}"


def tbl(head: list[str], rows: list[list[str]]) -> str:
    return "\n".join(["| " + " | ".join(head) + " |",
                      "|" + "|".join("---" for _ in head) + "|"]
                     + ["| " + " | ".join(r) + " |" for r in rows])


def pair(b: dict | None, a: dict | None, keyfn, label: str) -> str:
    """One row per condition present in both arms."""
    if not (b and a):
        return "_Not measured in both arms._"
    bi = {keyfn(c): c for c in b["cells"]}
    ai = {keyfn(c): c for c in a["cells"]}
    rows = []
    for k in bi:
        if k not in ai:
            continue
        cb, ca = bi[k], ai[k]
        gb = (cb["chunk_gap_ms"] or {}).get("p95")
        ga = (ca["chunk_gap_ms"] or {}).get("p95")
        rows.append([
            str(k),
            v(cb, "ttfa_ms", "p50"), v(ca, "ttfa_ms", "p50"),
            v(cb, "ttfa_ms", "p95"), v(ca, "ttfa_ms", "p95"),
            v(cb, "rtf", "p50", 3), v(ca, "rtf", "p50", 3),
            v(cb, "rtf", "p95", 3), v(ca, "rtf", "p95", 3),
            f"{cb['audio_seconds_per_s']:.1f}" if cb.get("audio_seconds_per_s") else NM,
            f"{ca['audio_seconds_per_s']:.1f}" if ca.get("audio_seconds_per_s") else NM,
            NM if gb is None else f"{gb:.0f}", NM if ga is None else f"{ga:.0f}",
        ])
    head = [label,
            "TTFA p50 ⟨B⟩", "⟨A⟩", "TTFA p95 ⟨B⟩", "⟨A⟩",
            "RTF p50 ⟨B⟩", "⟨A⟩", "RTF p95 ⟨B⟩", "⟨A⟩",
            "audio-s/s ⟨B⟩", "⟨A⟩", "gap p95 ⟨B⟩", "⟨A⟩"]
    return tbl(head, rows)


def envelope(a: dict | None) -> str:
    """Where clean streaming ends, judged against the frame period."""
    if not a:
        return "_Not measured._"
    rows = []
    for c in a["cells"]:
        g = c["chunk_gap_ms"]
        p50, p95 = g.get("p50"), g.get("p95")
        if p50 is None:
            continue
        verdict = ("clean" if p95 is not None and p95 <= FRAME_MS
                   else "tail late" if p50 <= FRAME_MS else "**starving**")
        rows.append([str(c.get("concurrency") or c.get("arrival_rate_per_s") or c["requests"]),
                     f"{c['audio_seconds_per_s']:.1f}" if c.get("audio_seconds_per_s") else NM,
                     f"{p50:.0f}", NM if p95 is None else f"{p95:.0f}",
                     str(c["queue_depth"].get("max") or NM), verdict])
    return tbl(["level", "audio-s/s", "gap p50", "gap p95", "depth max",
                f"vs {FRAME_MS:.0f} ms frame"], rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", default="before")
    ap.add_argument("--after", default="after")
    ap.add_argument("--dir", default="results")
    ap.add_argument("--out", default="results/_compare.md")
    o = ap.parse_args()
    d = Path(o.dir)
    B, A = o.before, o.after

    out = []
    for suite, keyfn, label, title in (
        ("concurrency", lambda c: c["concurrency"], "conc", "Concurrency — closed loop"),
        ("poisson", lambda c: c["arrival_rate_per_s"], "req/s", "Arrival rate — open loop, Poisson"),
        ("stagger", lambda c: c["arrival_rate_per_s"], "req/s", "Arrival rate — open loop, evenly paced"),
        ("sync", lambda c: c["requests"], "burst", "Simultaneous burst"),
        ("length", lambda c: c["label"], "prompt", "Text length"),
        ("language", lambda c: c["label"], "lang", "Language"),
    ):
        out.append(f"#### {title}\n\n"
                   + pair(load(d, B, suite), load(d, A, suite), keyfn, label) + "\n")

    out.append("#### Streaming quality envelope (after config)\n\n"
               + envelope(load(d, A, "concurrency")) + "\n")
    out.append("#### Streaming quality under unbounded arrivals (after config)\n\n"
               + envelope(load(d, A, "poisson")) + "\n")

    Path(o.out).write_text("\n".join(out))
    print(f"wrote {o.out}")


if __name__ == "__main__":
    main()
