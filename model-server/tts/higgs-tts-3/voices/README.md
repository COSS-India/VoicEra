# Voices

Each Higgs voice is a **reference clip plus its transcript**, cloned zero-shot
on every request. `manifest.json` lists them, and `refs/` holds the clips.
The sidecar reads the clips (mounted read-only at `/voices`). The adapter only
checks that they exist.

| voice | clip | from |
|---|---|---|
| Aditi (default) | `aditi.wav` | Rasa Hindi, female |
| Meera | `meera.wav` | Rasa Tamil, female |
| Ananya | `ananya.wav` | Rasa Bengali, female |
| Rahul | `rahul.wav` | Rasa Hindi, male |
| Arjun | `arjun.wav` | Rasa Telugu, male |

These are the same five speakers as `tts/indic-mio`. Every voice speaks every
supported language, but **with the accent of the language its clip was
recorded in**.

## Getting the clips: once, then commit

The clips are not in the repo yet. [`ai4bharat/Rasa`](https://huggingface.co/datasets/ai4bharat/Rasa)
is **gated**: someone has to accept its terms on HuggingFace. It is usually a
one-click "share your contact information" form. Its licence (CC-BY-4.0)
allows redistribution with attribution, so the clips only need fetching
**once**. After they are committed, no deployment needs a token.

```bash
cd model-server/tts/higgs-tts-3
pip install huggingface_hub pyarrow soundfile numpy
export HF_TOKEN=hf_...            # read token from an account that accepted Rasa's terms
python scripts/fetch_voices.py    # writes refs/*.wav AND each clip's transcript into manifest.json
```

**Listen to every clip** before committing. Each one should be:

- one speaker, clean, with no music or room echo;
- a calm, neutral read: the clip's mood carries into every sentence spoken in that voice;
- 5–15 s long. The script picks whole utterances and **never trims**, so the
  transcript still matches the audio.

To try a different candidate for one voice:
`python scripts/fetch_voices.py --voice Meera --skip 1`.

Then commit `refs/*.wav` together with `manifest.json`, and restart the `tts`
service. No rebuild is needed because the folder is bind-mounted.

## Using your own clips instead

Put a clean mono WAV in `refs/`, add an entry to `manifest.json` (`name`,
`gender`, `language`, `ref`, and the **exact transcript** in `text`), and
restart `tts`. Clone only people who have agreed to it. The model's licence
forbids non-consensual cloning.

Keep a voice's `name` stable once agents use it. It is stored in agent configs,
and the voice list in `apps/providers/local/higgs_tts/catalog.py` has to match
this manifest.

## Attribution

Clips from **ai4bharat/Rasa**, CC-BY-4.0. See `NOTICE`.
