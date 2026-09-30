"""Turn the sweep JSONs into the markdown tables of the load-test report.

Tables are generated, never transcribed, so a number in the report can always be
traced back to a run. A metric that was not collected prints as `--`, never as a
plausible-looking guess.

    python report.py --arm before [--arm after] --out results/orpheus_tts_loadtest.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

NM = "--"


def load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except Exception:                                            # noqa: BLE001
        return None


def g(cell: dict, block: str, key: str, scale: float = 1.0, nd: int = 0) -> str:
    v = (cell.get(block) or {}).get(key)
    if v is None:
        return NM
    v = v * scale
    return f"{v:.{nd}f}" if nd else f"{v:.0f}"


def gpu(cell: dict, field: str, key: str) -> str:
    blk = cell.get("gpu")
    if not isinstance(blk, dict):
        return NM
    v = (blk.get(field) or {})
    if not isinstance(v, dict):
        return NM
    return NM if v.get(key) is None else f"{v[key]:.0f}"


def table(rows: list[list[str]], head: list[str]) -> str:
    out = ["| " + " | ".join(head) + " |",
           "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def core(cell: dict) -> list[str]:
    """The block every table shares: TTFA, RTF, audio, throughput."""
    return [
        f"{cell['ok']}/{cell['requests']}",
        str(cell["muted"]),
        g(cell, "ttfa_ms", "p50"), g(cell, "ttfa_ms", "p95"), g(cell, "ttfa_ms", "p99"),
        g(cell, "rtf", "p50", nd=3), g(cell, "rtf", "p95", nd=3),
        g(cell, "audio_s", "p50", nd=2),
        g(cell, "chunk_gap_ms", "p95", nd=1),
    ]


CORE_HEAD = ["ok", "muted", "TTFA p50", "p95", "p99", "RTF p50", "RTF p95",
             "audio s", "gap p95"]


def sec_concurrency(d: dict) -> str:
    rows = []
    for c in d["cells"]:
        rows.append([str(c["concurrency"])] + core(c) + [
            f"{c['requests_per_s']:.2f}" if c.get("requests_per_s") else NM,
            f"{c['audio_seconds_per_s']:.1f}" if c.get("audio_seconds_per_s") else NM,
            gpu(c, "utilization.gpu", "p50"),
            gpu(c, "memory.used", "max"),
        ])
    return table(rows, ["conc"] + CORE_HEAD + ["req/s", "audio-s/s", "GPU%", "VRAM MiB"])


def sec_arrivals(d: dict, rate_col: str = "rate/s") -> str:
    rows = []
    for c in d["cells"]:
        key = (c.get("arrival_rate_per_s") or c.get("requests"))
        rows.append([str(key)] + core(c) + [
            g(c, "queue_delay_ms", "p50"), g(c, "queue_delay_ms", "p95"),
            str(c["queue_depth"].get("max") or NM),
            f"{c['audio_seconds_per_s']:.1f}" if c.get("audio_seconds_per_s") else NM,
            "yes" if c.get("client_bound_suspected") else "no",
        ])
    return table(rows, [rate_col] + CORE_HEAD +
                 ["queue p50", "queue p95", "depth max", "audio-s/s", "client-bound"])


def sec_labelled(d: dict, first: str, extra_char_col: bool = True) -> str:
    rows = []
    for c in d["cells"]:
        row = [str(c.get("label"))]
        if extra_char_col:
            row.append(str(c.get("chars", NM)))
        if c.get("voice"):
            row.append(c["voice"])
        rows.append(row + core(c))
    head = [first] + (["chars"] if extra_char_col else [])
    if any(c.get("voice") for c in d["cells"]):
        head.append("voice")
    return table(rows, head + CORE_HEAD)


def sec_single(d: dict) -> str:
    c = d["cells"][0]
    rows = [[m, v] for m, v in [
        ("requests ok", f"{c['ok']}/{c['requests']}"),
        ("muted (runaway)", str(c["muted"])),
        ("TTFA p50 / p95 / p99 (ms)",
         f"{g(c,'ttfa_ms','p50')} / {g(c,'ttfa_ms','p95')} / {g(c,'ttfa_ms','p99')}"),
        ("TTFA min / max (ms)", f"{g(c,'ttfa_ms','min')} / {g(c,'ttfa_ms','max')}"),
        ("RTF p50 / p95", f"{g(c,'rtf','p50',nd=3)} / {g(c,'rtf','p95',nd=3)}"),
        ("audio duration p50 (s)", g(c, "audio_s", "p50", nd=2)),
        ("total per request p50 (s)", g(c, "total_s", "p50", nd=2)),
        ("chunks per request p50", g(c, "chunks", "p50")),
        ("inter-chunk gap p50 / p95 / max (ms)",
         f"{g(c,'chunk_gap_ms','p50',nd=1)} / {g(c,'chunk_gap_ms','p95',nd=1)} / "
         f"{g(c,'chunk_gap_ms','max',nd=1)}"),
        ("GPU util p50 / max (%)",
         f"{gpu(c,'utilization.gpu','p50')} / {gpu(c,'utilization.gpu','max')}"),
        ("VRAM max (MiB)", gpu(c, "memory.used", "max")),
        ("power p50 / max (W)", f"{gpu(c,'power.draw','p50')} / {gpu(c,'power.draw','max')}"),
    ]]
    return table(rows, ["metric", "value"])


def header(d: dict) -> str:
    env = d.get("environment", {})
    h = env.get("health") if isinstance(env.get("health"), dict) else {}
    e = env.get("engine_env", {})
    rows = [
        ["host", env.get("host", NM)],
        ["GPU", env.get("gpu", NM)],
        ["model", f"{h.get('model', NM)} ({h.get('model_path', NM)})"],
        ["quantization", h.get("quantization", NM)],
        ["endpoint under test", env.get("endpoint", NM)],
        ["gateway", env.get("gateway", NM)],
        ["gpu_memory_utilization", e.get("ORPHEUS_GPU_MEMORY_UTILIZATION", NM)],
        ["max_num_seqs", e.get("ORPHEUS_MAX_NUM_SEQS", NM)],
        ["decoder.max_batch", e.get("ORPHEUS_DECODER_MAX_BATCH", NM)],
        ["max_model_len", e.get("ORPHEUS_MAX_MODEL_LEN", NM)],
        ["temperature / repetition_penalty",
         f"{e.get('ORPHEUS_TEMPERATURE', NM)} / {e.get('ORPHEUS_REPETITION_PENALTY', NM)}"],
        ["voice / style / language",
         f"{d.get('voice', NM)} / {d.get('style', NM)} / {d.get('language', NM)}"],
        ["run (UTC)", env.get("when_utc", NM)],
    ]
    kv = env.get("kv_cache_lines")
    if kv:
        rows.append(["KV cache (engine boot)", " · ".join(dict.fromkeys(kv))])
    return table(rows, ["field", "value"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", action="append", default=[], help="results/<arm>_*.json")
    ap.add_argument("--dir", default="results")
    ap.add_argument("--out", default="results/orpheus_tts_loadtest.md")
    a = ap.parse_args()
    d = Path(a.dir)

    parts: list[str] = []
    for arm in a.arm:
        files = {k: load(d / f"{arm}_{k}.json") for k in
                 ("single", "concurrency", "poisson", "stagger", "sync", "length", "language")}
        base = next((v for v in files.values() if v), None)
        if not base:
            parts.append(f"## {arm}\n\nNo results found.\n")
            continue
        parts.append(f"## Configuration — `{arm}`\n\n{header(base)}\n")
        if files["single"]:
            parts.append(f"### Single request (concurrency 1, n={files['single']['cells'][0]['requests']})"
                         f"\n\n{sec_single(files['single'])}\n")
        if files["concurrency"]:
            parts.append("### Concurrency — closed loop\n\n"
                         "A fixed pool of callers; a new request starts only when one finishes. "
                         "No queue by construction, so TTFA here is service time.\n\n"
                         + sec_concurrency(files["concurrency"]) + "\n")
        for key, title, note in (
            ("poisson", "Arrival rate — open loop, Poisson",
             "Arrival times fixed before the run and launched on schedule regardless of "
             "whether the server keeps up. TTFA is measured from the **scheduled** arrival, "
             "so queueing is counted rather than hidden."),
            ("stagger", "Arrival rate — open loop, evenly paced", "Same, with deterministic spacing."),
        ):
            if files[key]:
                parts.append(f"### {title}\n\n{note}\n\n{sec_arrivals(files[key])}\n")
        if files["sync"]:
            parts.append("### Burst — all requests at once\n\n"
                         "The artificial thundering herd: every request arrives simultaneously. "
                         "A real worst case, not a typical one.\n\n"
                         + sec_arrivals(files["sync"], rate_col="burst") + "\n")
        if files["length"]:
            parts.append("### Text length\n\n"
                         "TTFA should stay flat as text grows; if it climbs, something is "
                         "buffering the whole utterance before sending.\n\n"
                         + sec_labelled(files["length"], "prompt") + "\n")
        if files["language"]:
            parts.append("### Language and voice\n\n"
                         + sec_labelled(files["language"], "lang") + "\n")

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("\n".join(parts))
    print(f"wrote {a.out}  ({len(parts)} sections)")


if __name__ == "__main__":
    main()
