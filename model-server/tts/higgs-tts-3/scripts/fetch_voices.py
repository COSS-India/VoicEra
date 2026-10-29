"""Fetch the preset voices' reference clips AND transcripts from ai4bharat/Rasa.

Run ONCE, by someone whose HuggingFace account has accepted Rasa's terms (the
dataset is gated). Audition the result, then commit voices/refs/*.wav and the
updated manifest.json: Rasa is CC-BY-4.0, which allows redistribution with
attribution (voices/NOTICE), so after that no deployment ever needs the token.

Adapted from tts/indic-mio/scripts/fetch_rasa_refs.py, with two differences
that both come from Higgs cloning from a clip PLUS its transcript:

1. **The transcript is saved** into manifest.json `text`. Boson's cookbook says
   it "materially improves cloning quality".
2. **Clips are never trimmed.** indic-mio cut every clip to 10 s, which is fine
   for a speaker embedding and wrong here: a trimmed clip no longer matches its
   transcript. Instead a whole utterance between --min-seconds and
   --max-seconds is chosen.

Usage (from model-server/tts/higgs-tts-3):
    pip install huggingface_hub pyarrow soundfile numpy
    export HF_TOKEN=hf_...          # an account that has accepted Rasa's terms
    python scripts/fetch_voices.py
    python scripts/fetch_voices.py --voice Meera --min-seconds 6 --max-seconds 12

It is a convenience, not a curator: LISTEN to every clip before committing it.
A clip with background noise, a second speaker or an emotional read makes a
worse voice; re-run with --skip N to take a later candidate.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "voices" / "manifest.json"
REFS = ROOT / "voices" / "refs"

RASA_REPO = "ai4bharat/Rasa"
#: Rasa's column names are not documented; these are tried in order, and the
#: script prints the real schema on first use so a miss is easy to fix.
AUDIO_KEYS = ("audio", "wav", "speech")
TEXT_KEYS = ("text", "transcript", "transcription", "sentence", "normalized_text")
GENDER_KEYS = ("gender", "speaker_gender", "sex")
STYLE_KEYS = ("style", "emotion")
#: A calm read makes the most general-purpose voice.
NEUTRAL_STYLES = {"neutral", "conversational", "normal", "default", "narration", "news", ""}

#: manifest `language` code -> Rasa's config name.
RASA_LANGUAGE = {
    "as": "Assamese", "bn": "Bengali", "brx": "Bodo", "doi": "Dogri", "gu": "Gujarati",
    "hi": "Hindi", "kn": "Kannada", "kok": "Konkani", "ks": "Kashmiri", "mai": "Maithili",
    "ml": "Malayalam", "mni": "Manipuri", "mr": "Marathi", "ne": "Nepali", "or": "Odia",
    "pa": "Punjabi", "sa": "Sanskrit", "sat": "Santali", "sd": "Sindhi", "ta": "Tamil",
    "te": "Telugu", "ur": "Urdu",
}


def _first(columns: list[str], keys: tuple[str, ...]) -> str | None:
    return next((k for k in keys if k in columns), None)


def _shard(api, hf_hub_download, language: str, token: str) -> str | None:
    files = api.list_repo_files(RASA_REPO, repo_type="dataset", token=token)
    hits = sorted(f for f in files if f.endswith(".parquet") and language in f.split("/"))
    if not hits:
        print(f"    no parquet shard for {language!r}")
        return None
    print(f"    downloading shard {hits[0]}")
    return hf_hub_download(RASA_REPO, hits[0], repo_type="dataset", token=token)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--voice", help="only this voice (default: all in the manifest)")
    parser.add_argument("--min-seconds", type=float, default=5.0)
    parser.add_argument("--max-seconds", type=float, default=15.0)
    parser.add_argument("--skip", type=int, default=0,
                        help="skip this many matching clips first, to audition another")
    parser.add_argument("--max-scan", type=int, default=3000, help="rows to scan per voice")
    args = parser.parse_args()

    token = os.getenv("HF_TOKEN")
    if not token:
        sys.exit("Set HF_TOKEN to a token whose account has accepted the terms at "
                 "https://huggingface.co/datasets/ai4bharat/Rasa")
    try:
        import pyarrow.parquet as pq
        import soundfile as sf
        from huggingface_hub import HfApi, hf_hub_download
    except ImportError as exc:
        sys.exit(f"missing dependency ({exc}); pip install huggingface_hub pyarrow soundfile numpy")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    voices = manifest["voices"]
    if args.voice:
        voices = [v for v in voices if v["name"].casefold() == args.voice.casefold()]
        if not voices:
            sys.exit(f"voice {args.voice!r} is not in {MANIFEST}")

    REFS.mkdir(parents=True, exist_ok=True)
    api = HfApi()
    schema_shown = False
    for voice in voices:
        name, want_gender = voice["name"], voice.get("gender", "").lower()
        language = RASA_LANGUAGE.get(voice.get("language", ""))
        if not language:
            print(f"[{name}] no Rasa language for {voice.get('language')!r}; skipping")
            continue
        print(f"[{name}] Rasa {language}, {want_gender or 'any gender'}")
        try:
            shard = _shard(api, hf_hub_download, language, token)
        except Exception as exc:  # noqa: BLE001 -- report and carry on with the next voice
            print(f"[{name}] shard download failed: {exc}")
            continue
        if not shard:
            continue

        pf = pq.ParquetFile(shard)
        cols = list(pf.schema_arrow.names)
        if not schema_shown:
            print(f"    columns: {cols}")
            schema_shown = True
        audio_key, text_key = _first(cols, AUDIO_KEYS), _first(cols, TEXT_KEYS)
        gender_key, style_key = _first(cols, GENDER_KEYS), _first(cols, STYLE_KEYS)
        if not audio_key or not text_key:
            print(f"[{name}] need an audio and a text column; adjust AUDIO_KEYS/TEXT_KEYS")
            continue

        wanted = [c for c in (audio_key, text_key, gender_key, style_key) if c]
        skipped = scanned = 0
        saved = False
        for batch in pf.iter_batches(batch_size=64, columns=wanted):
            for row in batch.to_pylist():
                scanned += 1
                if scanned > args.max_scan:
                    break
                gender = str(row.get(gender_key, "")).lower() if gender_key else ""
                # Exact, not a substring test: "male" is a substring of "female".
                if want_gender and gender and gender.strip() not in {want_gender, want_gender[0]}:
                    continue
                if style_key and str(row.get(style_key, "")).strip().lower() not in NEUTRAL_STYLES:
                    continue
                text = str(row.get(text_key) or "").strip()
                audio = row.get(audio_key)
                data = audio.get("bytes") if isinstance(audio, dict) else None
                if not text or not data:
                    continue
                pcm, rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=False)
                if getattr(pcm, "ndim", 1) > 1:
                    pcm = pcm.mean(axis=1)
                seconds = pcm.size / rate
                if not args.min_seconds <= seconds <= args.max_seconds:
                    continue
                if skipped < args.skip:
                    skipped += 1
                    continue
                out = REFS / voice["ref"]
                sf.write(out, pcm, rate)  # whole utterance: it must match `text`
                voice["text"] = text
                print(f"[{name}] wrote {out.name} ({seconds:.1f}s @ {rate} Hz): {text}")
                saved = True
                break
            if saved or scanned > args.max_scan:
                break
        if not saved:
            print(f"[{name}] nothing matched in {scanned} rows; widen --min/--max-seconds")

    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nUpdated {MANIFEST.name}. Listen to voices/refs/*.wav, then commit them with it.")


if __name__ == "__main__":
    main()
