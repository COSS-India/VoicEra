# indic-speak-preview-v2 — two generation-stability issues

**Reported by:** Tarento / VoicEra · **Checkpoint:** `bodhan-ai/indic-speak-preview-v2`
**Date:** 2 September 2026

---

## Summary

Two issues, both reproduced using **your own `inference.py`** — our serving stack is not in
the path for any result below.

1. **Runaway generation.** A ~4-second sentence intermittently generates to the
   `max_new_tokens` cap (2520 tokens ≈ 30 s) without ever emitting `<|end_of_speech|>`.
   Same prompt, same speaker, same style.
2. **Audible tremolo.** Generated speech intermittently carries a periodic amplitude
   modulation — listeners describe the voice as "shivering", or as a slight echo. It is
   present in the generated SNAC codes, not in the vocoder.

Both are stochastic: identical prompt, voice, style and text give audibly different results
run to run. We understand this is an early checkpoint shared for integration testing, so
these may already be known — we are reporting them in case the detail is useful.

---

## 1. Runaway generation

Two calls with the same prompt and `--seed 42`, one process:

| | tokens | duration |
|---|---:|---:|
| first | — | 4.27 s |
| second | ≥ 2520 (capped) | **30.72 s** |

Cross-correlating the first second of the two gives **+0.597** — they are different
utterances, not one utterance decoded twice. Your own warning fired on the second:

> generation hit max_new_tokens (2520) without emitting `<|end_of_speech|>` — audio is
> likely truncated or runaway babble

We consider this the more serious of the two: an unbounded output on ordinary input, and one
a caller cannot easily defend against beyond capping tokens and discarding the result.

**Related:** `--seed` does not appear to make generation reproducible. The two runs above were
both invoked with `--seed 42`. Either the seed is not reaching the second generation or
generation is nondeterministic; either way, anyone trying to reproduce a report can't.

---

## 2. Tremolo, and why the vocoder is not the cause

### The measurement

Tremolo is periodic amplitude modulation, so we made it a number rather than an opinion:
amplitude envelope → spectrum → fraction of envelope energy in **8–20 Hz** (above the
syllable rate) relative to 1–60 Hz. Script at the bottom.

### A/B of the two decoders, on one generation

**Note on `--stock`:** it does not decode one generation twice — it generates again. That
made our first A/B invalid (the two files above differ 7× in length). We got a valid one by
using your `TTS` class as a library: generate once, decode that single `z_q` with both
`self.vocos` and `self.snac.decoder`.

| | duration | tremolo (8–20 Hz) |
|---|---:|---:|
| Vocos | 4.01 s | 0.238 |
| stock SNAC | 4.01 s | 0.255 |

Identical length (same `z_q`), waveform correlation +0.695 — consistent with two vocoders
reconstructing phase differently. Spectral energy shares agree within ±0.011 across
0–1 k, 1–2 k, 2–4 k, 4–8 k and 8–12 kHz.

**Both decodes of the same codes carry the tremolo, at the same level.** The 7% difference is
well inside the run-to-run noise floor measured below. So it originates in the generated
codes.

### It is not style-specific

Five runs per style, identical text and voice:

| style | scores | spread |
|---|---|---:|
| `surprise` | 0.280 0.209 0.245 0.228 0.211 | **0.070** |
| `educational lecture` | 0.236 0.216 0.215 0.207 0.204 | **0.031** |

The **within-style** spread exceeds the difference between the two styles' means (~0.019).
A sweep of all 14 styles at one voice separated none of them. Listeners had reported it on
particular styles; the measurements say that was sampling luck.

### It is not the repetition penalty

Tested at 1.3, 1.2 (your production value) and 1.0 (disabled). No audible or measured
difference. We had expected penalty to be implicated, since sustained phonation legitimately
repeats codes.

### One unverified observation

The modulation shows a modest local elevation around **11–13 Hz** — 1.57× its neighbours for
the Vocos decode, 1.28× for stock. The SNAC frame rate is **11.72 Hz** (24000 / 2048, and
your contract's "82 tokens ≈ 1 second" ÷ 7 gives 11.71), which would suggest frame-to-frame
discontinuity in the generated codes.

**We are not claiming this.** On a single 4-second clip the modulation spectrum is too noisy
to distinguish a real peak from chance, and there is a comparable bump at 17 Hz that
certainly means nothing. Averaging the modulation spectrum over many generations would settle
it — a real frame-rate artefact survives averaging, syllable-rate energy and noise smear out.
We have the harness if it would be useful, but you are better placed to test it against your
training data.

---

## Our configuration

We verified our own integration before reporting, since a mis-integration produces exactly
these symptoms:

| | |
|---|---|
| Prompt | `token_contract.md` §5 TTS-with-conditioning, built as token ids — matches token for token |
| Audio band | base 128266, 7 codebooks × 4096, offset by frame position — matches §3 |
| Sampling | temperature 0.6, top_p 0.9, repetition_penalty 1.2 — your published production config |
| Serving | vLLM 0.25.1, `LlamaForCausalLM`, fp8, `max_model_len` 8192 |
| GPU | NVIDIA H200 NVL, compute capability 9.0 |
| Vocoder | stock SNAC decoder (see question 3) |

Our server's outputs score **0.204–0.280** on the metric above; your reference implementation
scores **0.238** on the same voice and text. Same range, so our decode path is not adding
anything measurable.

---

## Questions

1. **Are these known for this checkpoint?** Your model card notes it is "a very early
   checkpoint, shared only for integration and load testing".

2. **`top_k`** — your code example passes `top_k=50`, but the benchmark configuration line
   ("ckpt-8944, t 0.6 · top_p 0.9 · rp 1.2") does not mention it. Which is the reference
   configuration? Our server currently cannot set `top_k`; we will add it if it is part of
   the intended config.

3. **Streaming with Vocos.** We serve live audio, decoding a 4-frame window and emitting the
   middle frame. Vocos's receptive field looks far wider — 3 pre-blocks and 11 post-blocks of
   `Conv1d(kernel_size=7)` plus the iSTFT head, order ±18 latent frames — so a windowed
   decode would truncate its context. Is there a recommended streaming configuration, or is
   whole-utterance decode the intended use?

4. **Emotion style casing.** `voices.md` prints emotions lowercase (`happy`, `sad`, `anger`,
   `fear`, `surprise`, `disgust`) while the README examples pass them uppercase
   (`style="ANGER"`). Which did training use? An untrained conditioning string degrades
   delivery silently rather than erroring.

5. **`min_tokens`.** We floor generation at 28 tokens (one 4-frame decode window) to stop
   temperature sampling emitting an immediate end-of-speech. Is there a value you recommend?

6. **Bhili.** `README.md`'s voice table lists Bhili (`bhb`) with 7 speakers, but `bhb` is
   absent from the frontmatter `language:` list and from both the Production and Preview tier
   tables. Is it supported, and at which tier?

---

## Reproduction

### Runaway generation

```bash
python inference.py --model <local dir> \
  --text "మీరు ఎలా ఉన్నారు? ఈరోజు వాతావరణం చాలా బాగుంది." \
  --speaker Sravani --style "educational lecture" \
  --seed 42 --stock --out-dir ./ab
```

Compare the durations of the two output files. We saw 4.27 s and 30.72 s.

### The decoder A/B — one generation, two decoders

```python
import sys, torch, soundfile as sf
sys.path.insert(0, "<local dir>")
from inference import TTS, build_prompt, ids_to_codes

tts = TTS("<local dir>")
prompt = build_prompt(tts.tok, TEXT, "Sravani", "educational lecture")
ids = torch.tensor([prompt], device=tts.device)
torch.manual_seed(42)
with torch.no_grad():
    gen = tts.lm.generate(
        input_ids=ids, attention_mask=torch.ones_like(ids), max_new_tokens=2520,
        eos_token_id=[tts._eos, tts.tok.eos_token_id], pad_token_id=tts.tok.eos_token_id,
        do_sample=True, temperature=0.6, top_p=0.9, top_k=50)
    new = gen[0].tolist()[len(prompt):]
    z_q = tts.snac.quantizer.from_codes(ids_to_codes(new, tts._base, tts.device))
    sf.write("vocos.wav", tts.vocos(z_q.float())[0, 0].clamp(-1, 1).float().cpu().numpy(), 24000)
    sf.write("stock.wav", tts.snac.decoder(z_q)[0, 0].clamp(-1, 1).float().cpu().numpy(), 24000)
```

### The metric

```python
import numpy as np, soundfile as sf

def tremolo(path, lo=8.0, hi=20.0):
    """Fraction of amplitude-envelope energy in the tremolo band, relative to
    1-60 Hz, plus the peak modulation frequency in that band."""
    x, sr = sf.read(path, dtype="float32")
    if x.ndim > 1:
        x = x.mean(1)
    hop = max(1, sr // 200)                      # envelope at ~200 Hz
    n = len(x) // hop * hop
    env = np.abs(x[:n]).reshape(-1, hop).mean(1)
    env = env[env.size // 10:]                   # drop the attack transient
    env = env - env.mean()
    spec = np.abs(np.fft.rfft(env * np.hanning(env.size)))
    f = np.fft.rfftfreq(env.size, d=hop / sr)
    band, ref = (f >= lo) & (f <= hi), (f >= 1) & (f <= 60)
    return (float(spec[band].sum() / (spec[ref].sum() + 1e-12)),
            float(f[band][np.argmax(spec[band])]))
```

Run the same generation five or more times without a fixed seed to see the run-to-run spread.

---

## What we are not claiming

The metric is a proxy for what a listener hears. It cannot resolve your Vocos decode from
stock SNAC at this scale (0.017 apart, against a run-to-run noise floor of 0.031–0.070), so
read finding 2 as "both carry it equally" rather than "the two decoders are identical". The
judgement that started this investigation was a listener's, not the script's.
