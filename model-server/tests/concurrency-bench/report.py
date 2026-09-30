#!/usr/bin/env python3
"""Turn one run's results into a markdown report with a verdict per N.

    python report.py --results results/my-run            # writes results/my-run/report.md

Reads whatever exists of stt/batch_{sync,random}.json, tts/batch_{sync,random}.json
and runaway/summary.json. A value that was not measured prints as `--`.

Pass rule (default): a level PASSES when no request failed and p95 RTF < 1.0
across the pooled rounds. --percentile and --rtf-threshold change it;
--runaways-fail also fails any TTS level with a runaway generation.
Latencies, accuracy and GPU numbers are reported, not judged.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

NM = "--"
TESTS = (("sync", "Test A - single batch: all N requests at the same instant"),
         ("random", "Test B - N requests at random times within the arrival window"))


def load(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text())
    except Exception:                                            # noqa: BLE001
        return None


def g(d: object, *keys: str, nd: int | None = None) -> object:
    for k in keys:
        if not isinstance(d, dict):
            return NM
        d = d.get(k)
    if d is None:
        return NM
    if nd is not None and isinstance(d, int | float):
        return round(d, nd) if nd else int(round(d))
    return d


def table(rows: list[list], head: list[str]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
    return "\n".join(out)


class Rule:
    def __init__(self, a: argparse.Namespace):
        self.q, self.thr, self.runaways_fail = a.percentile, a.rtf_threshold, a.runaways_fail

    def text(self) -> str:
        s = f"zero failed requests and {self.q} RTF < {self.thr:g}"
        return s + (" and zero runaway generations" if self.runaways_fail else "")

    def passes(self, c: dict) -> bool:
        v = (c.get("rtf") or {}).get(self.q)
        if c.get("requests", 0) == 0 or c.get("failed", 1) != 0 or v is None:
            return False
        if self.runaways_fail and c.get("runaways"):
            return False
        return v < self.thr

    def verdict(self, cells: list[dict]) -> str:
        clean = None
        for c in sorted(cells, key=lambda c: c["n"]):
            if not self.passes(c):
                break
            clean = c["n"]
        passing = [str(c["n"]) for c in cells if self.passes(c)]
        return (f"**Passes at every N up to: {clean if clean is not None else 'none'}**  \n"
                f"Levels passing: {', '.join(passing) or 'none'}")


def rtf_cols(c: dict, rule: Rule) -> list:
    return [g(c, "rtf", "p50", nd=3), g(c, "rtf", "p95", nd=3), g(c, "rtf", "p99", nd=3),
            g(c, "rtf", "max", nd=3), "PASS" if rule.passes(c) else "FAIL"]


RTF_HEAD = ["RTF p50", "RTF p95", "RTF p99", "RTF max", "result"]
STT_HEAD = ["N", "ok", *RTF_HEAD, "final p50 ms", "final p95 ms", "final p99 ms",
            "1st partial p50 ms", "CER %", "GPU mem max MiB", "note"]
TTS_HEAD = ["N", "ok", "runaways", *RTF_HEAD, "TTFA p50 ms", "TTFA p95 ms", "TTFA p99 ms",
            "chunk gap p95 ms", "audio s/s", "GPU mem max MiB", "note"]


def note(c: dict) -> str:
    return "client-bound" if c.get("client_bound_suspected") else ""


def stt_rows(cells: list[dict], rule: Rule) -> list[list]:
    return [[c["n"], f"{c['ok']}/{c['requests']}", *rtf_cols(c, rule),
             g(c, "final_ms", "p50", nd=0), g(c, "final_ms", "p95", nd=0),
             g(c, "final_ms", "p99", nd=0), g(c, "first_partial_ms", "p50", nd=0),
             g(c, "cer_pct", "mean", nd=1), g(c, "gpu", "memory.used", "max", nd=0), note(c)]
            for c in cells]


def tts_rows(cells: list[dict], rule: Rule) -> list[list]:
    return [[c["n"], f"{c['ok']}/{c['requests']}", c.get("runaways", NM), *rtf_cols(c, rule),
             g(c, "ttfa_ms", "p50", nd=0), g(c, "ttfa_ms", "p95", nd=0),
             g(c, "ttfa_ms", "p99", nd=0),
             g(c, "chunk_gap_ms", "p95", nd=0), c.get("audio_seconds_per_s", NM),
             g(c, "gpu", "memory.used", "max", nd=0), note(c)] for c in cells]


def errors(cells: list[dict]) -> str:
    errs = sorted({e for c in cells for e in c.get("errors", [])})
    return ("Errors seen: " + "; ".join(f"`{e}`" for e in errs[:8]) + "\n") if errs else ""


def meta_table(meta: dict | None, endpoint: str) -> str:
    meta = meta or {}
    s = meta.get("settings") or {}
    rows = [["endpoint", endpoint], ["when (UTC)", meta.get("when_utc", NM)],
            ["client host", meta.get("client_host", NM)],
            ["git commit", meta.get("git_commit") or NM],
            ["GPU", meta.get("gpu", NM)],
            ["levels / rounds / window", f"{s.get('levels', NM)} / {s.get('rounds', NM)} / "
                                         f"{s.get('arrival_window', NM)} s"],
            ["server notes", "; ".join(meta.get("server_notes") or []) or NM]]
    return table(rows, ["field", "value"])


def section(results: Path, kind: str, rule: Rule) -> list[str]:
    data = {m: load(results / kind / f"batch_{m}.json") for m, _ in TESTS}
    if not any(data.values()):
        return []
    base = next(v for v in data.values() if v)
    meta = load(results / kind / "run_meta.json")
    parts = []
    if kind == "stt":
        parts += [f"## Streaming STT - language `{base.get('language')}`\n",
                  meta_table(meta, base.get("endpoint", NM)) + "\n",
                  "Request = open the socket, stream one clip "
                  f"(bucket `{base.get('bucket')}`) at real time in 160 ms frames, `flush_eos`, "
                  "read the final. **RTF** = server time on the utterance (its reported "
                  "per-message processing times plus the flush) / audio duration; below 1 it "
                  "keeps up with live speech. **final** = scheduled end of speech to final "
                  "transcript.\n"]
        rows = stt_rows
    else:
        parts += [f"## Streaming TTS - language `{base.get('language')}`, "
                  f"voice `{base.get('voice')}`\n",
                  meta_table(meta, base.get("endpoint", NM)) + "\n",
                  f"Request = one streaming synthesis of: \"{base.get('text')}\" "
                  f"({len(base.get('text') or '')} characters). **RTF** = generation time / audio "
                  "duration; below 1 audio arrives faster than it plays. **TTFA** = scheduled "
                  "start to first audio byte. **runaways** = responses cut off by the "
                  f"server's duration guard (audio >= {base.get('runaway_threshold_s')} s); "
                  "they are successful requests and included in RTF.\n"]
        rows = tts_rows
    head = STT_HEAD if kind == "stt" else TTS_HEAD
    for m, title in TESTS:
        f = data[m]
        if f:
            parts.append(f"### {title}\n\n{rule.verdict(f['cells'])}\n\n"
                         + table(rows(f["cells"], rule), head) + "\n\n" + errors(f["cells"]))
    return parts


def runaway_section(results: Path) -> list[str]:
    s = load(results / "runaway" / "summary.json")
    if not s:
        return []
    lo, hi = s.get("runaway_rate_95ci_wilson") or [None, None]
    rate = s.get("runaway_rate")
    return ["## TTS runaway rate at N=1 (no load)\n",
            table([["requests (ok)", f"{s['requests']} ({s['ok']})"],
                   ["guard cap / threshold",
                    f"{s['guard_cap_s']} s / {s['runaway_threshold_s']} s"],
                   ["runaways", f"{s['runaways']} = {NM if rate is None else f'{100 * rate:.1f}%'} "
                                f"(95% CI {100 * (lo or 0):.1f}-{100 * (hi or 0):.1f}%)"],
                   ["RTF p95 all / excluding runaways",
                    f"{g(s, 'rtf_all', 'p95')} / {g(s, 'rtf_excluding_runaways', 'p95')}"]],
                  ["field", "value"]) + "\n"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", required=True, help="the --out-dir used for the tests")
    ap.add_argument("--out", default="", help="default: <results>/report.md")
    ap.add_argument("--percentile", default="p95", choices=["p50", "p95", "p99", "max"])
    ap.add_argument("--rtf-threshold", type=float, default=1.0)
    ap.add_argument("--runaways-fail", action="store_true")
    ap.add_argument("--title", default="Concurrency test report")
    a = ap.parse_args()
    r = Path(a.results)
    rule = Rule(a)
    body = section(r, "stt", rule) + section(r, "tts", rule) + runaway_section(r)
    if not body:
        raise SystemExit(f"no results found under {r}")
    rounds = next((c.get("rounds") for k in ("stt", "tts") for m, _ in TESTS
                   for c in ((load(r / k / f"batch_{m}.json") or {}).get("cells") or [])), NM)
    head = [f"# {a.title}\n",
            f"N = requests started per round; each N ran {rounds} rounds, pooled. "
            "**Test A** starts all N at once. **Test B** starts them at random times "
            "within the arrival window, a fresh draw each round. "
            f"A level **passes** with {rule.text()}. Percentiles are nearest-rank. "
            "*client-bound* marks a level where the load generator itself fell "
            "behind (event-loop lag p95 > 50 ms); treat those numbers with care.\n"]
    out = Path(a.out or r / "report.md")
    out.write_text("\n".join(head + body))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
