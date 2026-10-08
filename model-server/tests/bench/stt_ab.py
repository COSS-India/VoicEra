"""Compare STT servers on the same audio: transcripts side by side, WER/CER when
there is a reference.

Written for swapping a checkpoint behind indic-nemotron (the Bhili retrain of
2026-10-05), but nothing in it is Nemotron-specific: it speaks the OpenAI
`POST /v1/audio/transcriptions` contract, so it works against a model container
directly or through the gateway.

That endpoint runs the same streaming session (ASRSession, fixed 320 ms chunks)
as a live call, not a separate offline path -- so what this measures is what a
caller would get. AI4Bharat's own numbers come from NeMo's offline `transcribe`,
so expect the absolute WER to differ from theirs; the comparison between two
servers is the part that means something.

Standard library only, so it runs on the GPU box without installing anything.

Usage:
    # old = the live slot through the gateway, new = a standalone container
    python stt_ab.py --server old=http://127.0.0.1:8100 \\
                     --server new=http://127.0.0.1:8200 \\
                     --language bhb --manifest bhili_test.jsonl --out ab.jsonl

    # or just files, no references
    python stt_ab.py --server new=http://127.0.0.1:8200 --language bhb a.wav b.wav

Manifest: one JSON object per line with "audio_filepath" and, optionally, "text"
(the reference) -- the same shape AI4Bharat's infer_nemotron_bhb.py reads.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import mimetypes
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import uuid
from pathlib import Path

MODEL = "indic-nemotron-600m"


# --------------------------------------------------------------------- scoring

def normalise(text: str) -> str:
    """Lowercase, drop punctuation (any Unicode P* category, so the danda goes
    too), collapse whitespace. Deliberately light: the point is that both
    servers are scored the same way, not that the number matches anyone else's."""
    text = unicodedata.normalize("NFC", text).lower()
    text = "".join(" " if unicodedata.category(c).startswith("P") else c for c in text)
    return re.sub(r"\s+", " ", text).strip()


def edits(ref: list, hyp: list) -> int:
    """Levenshtein distance over tokens."""
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1]


# --------------------------------------------------------------------- transport

def multipart(fields: dict[str, str], file_field: str, path: Path) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    out = bytearray()
    for k, v in fields.items():
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n"
                f"{v}\r\n").encode()
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; "
            f"filename=\"{path.name}\"\r\nContent-Type: {ctype}\r\n\r\n").encode()
    out += path.read_bytes() + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def transcribe(base: str, path: Path, language: str, timeout: float) -> tuple[str, float]:
    body, ctype = multipart({"model": MODEL, "language": language,
                             "response_format": "json"}, "file", path)
    req = urllib.request.Request(base.rstrip("/") + "/v1/audio/transcriptions",
                                 data=body, headers={"Content-Type": ctype}, method="POST")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read()[:300]!r}") from None
    return payload.get("text", ""), (time.perf_counter() - t0) * 1000.0


def health(base: str) -> dict | None:
    """Best effort. The gateway has no /health of its own model; a container does."""
    try:
        with urllib.request.urlopen(base.rstrip("/") + "/health", timeout=5) as r:
            return json.loads(r.read())
    except Exception:
        return None


# --------------------------------------------------------------------- main

def score_one(item: dict, servers: dict[str, str], a, totals: dict) -> dict:
    """Send one utterance to every server; add its errors to the running totals."""
    path = Path(item["audio_filepath"])
    ref = item.get("text")
    row = {"audio_filepath": str(path), "ref": ref, "hyp": {}, "ms": {}}
    for name, url in servers.items():
        try:
            text, ms = transcribe(url, path, a.language, a.timeout)
        except Exception as e:                       # keep going; count it
            totals[name]["fail"] += 1
            row["hyp"][name] = None
            row.setdefault("error", {})[name] = str(e)
            continue
        row["hyp"][name], row["ms"][name] = text, round(ms, 1)
        totals[name]["ms"] += ms
        if ref:
            r, h = normalise(ref), normalise(text)
            totals[name]["words"] += len(r.split())
            totals[name]["w_err"] += edits(r.split(), h.split())
            totals[name]["chars"] += len(r.replace(" ", ""))
            totals[name]["c_err"] += edits(list(r.replace(" ", "")), list(h.replace(" ", "")))
    return row


def load_items(args) -> list[dict]:
    items = [{"audio_filepath": a} for a in args.audio]
    if args.manifest:
        base = Path(args.manifest).resolve().parent
        for line in Path(args.manifest).read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                p = Path(row["audio_filepath"])
                row["audio_filepath"] = str(p if p.is_absolute() else base / p)
                items.append(row)
    if args.limit:
        items = items[: args.limit]
    return items


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("audio", nargs="*")
    ap.add_argument("--manifest")
    ap.add_argument("--server", action="append", required=True, metavar="NAME=URL",
                    help="repeatable; the first one named is the baseline")
    ap.add_argument("--language", default="bhb",
                    help="sent on every request; this model has no auto (default: bhb)")
    ap.add_argument("--out", help="per-utterance results as JSONL")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--show", type=int, default=10,
                    help="how many disagreeing utterances to print (default 10)")
    a = ap.parse_args()

    servers: dict[str, str] = {}
    for s in a.server:
        name, _, url = s.partition("=")
        if not url:
            ap.error(f"--server wants NAME=URL, got {s!r}")
        servers[name] = url
    items = load_items(a)
    if not items:
        ap.error("give audio files or --manifest")

    for name, url in servers.items():
        h = health(url)
        loaded = (h or {}).get("models_loaded")
        print(f"[{name}] {url}  models_loaded={loaded}" if h else f"[{name}] {url}")
        if loaded is not None and a.language in ("bhb", "bhili") and not loaded.get("bhili"):
            print(f"  WARNING: {name} has no Bhili model loaded -- bhb will be served by "
                  f"the multilingual checkpoint, and this comparison measures that instead.")

    totals = {n: {"words": 0, "w_err": 0, "chars": 0, "c_err": 0, "ms": 0.0, "fail": 0}
              for n in servers}
    rows = []
    with contextlib.ExitStack() as stack:
        # Written row by row, so a long run that dies halfway still leaves its data.
        out = stack.enter_context(open(a.out, "w", encoding="utf-8")) if a.out else None
        for k, item in enumerate(items, 1):
            row = score_one(item, servers, a, totals)
            rows.append(row)
            if out:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
            print(f"\r{k}/{len(items)}", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)
    scored = sum(bool(r["ref"]) for r in rows)

    names = list(servers)
    print(f"\n{len(items)} utterances, {scored} with a reference, language={a.language}\n")
    print(f"{'server':<12}{'WER %':>8}{'CER %':>8}{'mean ms':>10}{'failed':>8}")
    for n in names:
        t = totals[n]
        done = len(items) - t["fail"]
        wer = f"{100 * t['w_err'] / t['words']:.1f}" if t["words"] else "-"
        cer = f"{100 * t['c_err'] / t['chars']:.1f}" if t["chars"] else "-"
        ms = f"{t['ms'] / done:.0f}" if done else "-"
        print(f"{n:<12}{wer:>8}{cer:>8}{ms:>10}{t['fail']:>8}")

    if len(names) > 1:
        base = names[0]
        for other in names[1:]:
            differ = [r for r in rows
                      if r["hyp"].get(base) is not None and r["hyp"].get(other) is not None
                      and normalise(r["hyp"][base]) != normalise(r["hyp"][other])]
            print(f"\n{other} vs {base}: {len(differ)}/{len(rows)} transcripts differ")
            for r in differ[: a.show]:
                print(f"\n  {Path(r['audio_filepath']).name}")
                if r["ref"]:
                    print(f"    {'ref':<8}{r['ref']}")
                print(f"    {base:<8}{r['hyp'][base]}")
                print(f"    {other:<8}{r['hyp'][other]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
