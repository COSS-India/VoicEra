# Orpheus TTS — Streaming Load Test

**Date** 2026-09-18 · **Host** ip-172-31-23-34 · **GPU** NVIDIA RTX PRO 6000 Blackwell Server Edition (97,887 MiB, driver 595.91.07, CC 12.0)
**Endpoint under test** `POST /v1/audio/speech`, `response_format: pcm` — the OpenAI-spec streaming route, through the gateway at `http://127.0.0.1:8100`
**Result** 2,879 of 2,880 requests succeeded across 14 runs. 1 failure. 0 malformed or silent responses.

---

## 1. Verdict

The deployment is **healthy and fast at low load, and was mis-sized for this GPU**. Raising two engine
settings removed a hard ceiling and cost nothing:

| | before | after |
|---|---|---|
| `gpu_memory_utilization` | 0.12 | **0.90** |
| `max_num_seqs` | 32 | **64** |
| KV cache | 6.69 GiB (62,576 tokens) | **80.76 GiB (756,128 tokens)** |
| VRAM in use | 12,720 MiB of 97,887 | **88,856 MiB of 97,887** |
| TTFA p95 @ 64 concurrent | 3,655 ms | **601 ms** |
| TTFA p95 @ 16 req/s arrivals | 5,905 ms | **566 ms** |
| Peak throughput | 47.8 audio-s/s | **72.5 audio-s/s** |
| RTF p95 @ 64 concurrent | 1.390 | **0.895** |

**But the change does not raise how many live calls this box can serve with clean audio.** That number is
set by GPU throughput, not configuration, and is unchanged at roughly **4 requests/second** of sustained
arrivals. What improved is behaviour *past* that point: the service now degrades gracefully instead of
stalling. Both facts are load-bearing and neither should be quoted without the other.

---

## 2. Method

Single endpoint, single style (`none`), single voice per language, fixed seed. Every prompt is a **single
clause** — a second clause triggers an unrelated open bug (§7) that would have contaminated every cell.

Per cell: one warm-up request discarded; the server drained to `streams_active == 0` before the next cell;
GPU sampled at 10 Hz across the measurement window; percentiles are **nearest-rank, no interpolation**,
matching `stt/indic-transcribe/bench/metrics_lib.py` so the two reports' p95 mean the same thing.

Two load models, because they answer different questions:

- **Closed loop** — a fixed pool of N callers; a new request starts only when one finishes. Finds the
  capacity ceiling. No queue by construction, so TTFA is service time.
- **Open loop** — arrival times fixed *before* the run and launched on schedule whether or not the server
  keeps up, with latency measured from the **scheduled** arrival. This is what real traffic does, and it is
  the only model that exposes queue growth. Timing from the actual start instead would hide queue delay and
  make p99 look healthy exactly when the server is drowning.

**Key threshold used throughout:** one audio frame is 2,048 samples at 24 kHz = **85.33 ms**. If the gap
between streamed chunks exceeds that, the client's playback drains faster than frames arrive and the caller
hears a gap. `gap p50 > 85.33 ms` means the typical stream stutters continuously; `gap p95 > 85.33 ms` means
roughly 5% of frames are late, which a jitter buffer may absorb.

---

## 3. Results

⟨B⟩ = before (0.12 / 32) · ⟨A⟩ = after (0.90 / 64). TTFA and gap in ms, RTF dimensionless.

#### Concurrency — closed loop

| conc | TTFA p50 ⟨B⟩ | ⟨A⟩ | TTFA p95 ⟨B⟩ | ⟨A⟩ | RTF p50 ⟨B⟩ | ⟨A⟩ | RTF p95 ⟨B⟩ | ⟨A⟩ | audio-s/s ⟨B⟩ | ⟨A⟩ | gap p95 ⟨B⟩ | ⟨A⟩ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 152 | 152 | 156 | 160 | 0.351 | 0.351 | 0.356 | 0.353 | 2.8 | 2.9 | 32 | 30 |
| 2 | 179 | 167 | 187 | 180 | 0.411 | 0.404 | 0.416 | 0.409 | 4.9 | 5.0 | 34 | 34 |
| 4 | 196 | 202 | 236 | 223 | 0.458 | 0.443 | 0.466 | 0.463 | 8.8 | 8.8 | 43 | 42 |
| 8 | 241 | 242 | 262 | 269 | 0.485 | 0.483 | 0.559 | 0.523 | 14.1 | 14.4 | 64 | 60 |
| 12 | 200 | 202 | 290 | 282 | 0.544 | 0.541 | 0.583 | 0.605 | 10.8 | 16.9 | 76 | 83 |
| 16 | 216 | 200 | 280 | 311 | 0.574 | 0.589 | 0.598 | 0.611 | 20.6 | 20.7 | 74 | 93 |
| 24 | 231 | 215 | 271 | 251 | 0.663 | 0.629 | 0.682 | 0.648 | 34.0 | 16.3 | 108 | 92 |
| 32 | 253 | 273 | 293 | 275 | 0.676 | 0.682 | 0.702 | 0.697 | 45.9 | 45.5 | 94 | 96 |
| 48 | 365 | 309 | 3566 | 365 | 0.787 | 0.768 | 1.296 | 0.793 | 39.2 | 60.9 | 127 | 108 |
| 64 | 369 | 455 | 3655 | 601 | 0.822 | 0.859 | 1.390 | 0.895 | 47.8 | 72.5 | 153 | 125 |

#### Arrival rate — open loop, Poisson

| req/s | TTFA p50 ⟨B⟩ | ⟨A⟩ | TTFA p95 ⟨B⟩ | ⟨A⟩ | RTF p50 ⟨B⟩ | ⟨A⟩ | RTF p95 ⟨B⟩ | ⟨A⟩ | audio-s/s ⟨B⟩ | ⟨A⟩ | gap p95 ⟨B⟩ | ⟨A⟩ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1.0 | 221 | 209 | 261 | 252 | 0.472 | 0.450 | 0.504 | 0.496 | 5.2 | 5.2 | 52 | 51 |
| 2.0 | 242 | 234 | 272 | 268 | 0.505 | 0.514 | 0.554 | 0.559 | 9.2 | 7.4 | 68 | 67 |
| 4.0 | 279 | 262 | 312 | 296 | 0.711 | 0.724 | 0.771 | 0.773 | 18.8 | 18.8 | 86 | 85 |
| 8.0 | 331 | 312 | 637 | 362 | 1.195 | 1.090 | 1.300 | 1.231 | 32.1 | 35.2 | 132 | 130 |
| 12.0 | 1528 | 355 | 2929 | 431 | 1.448 | 1.402 | 1.799 | 1.604 | 42.5 | 48.0 | 181 | 170 |
| 16.0 | 3058 | 395 | 5905 | 566 | 1.955 | 1.623 | 2.337 | 1.908 | 46.0 | 59.7 | 206 | 234 |

#### Arrival rate — open loop, evenly paced

| req/s | TTFA p50 ⟨B⟩ | ⟨A⟩ | TTFA p95 ⟨B⟩ | ⟨A⟩ | RTF p50 ⟨B⟩ | ⟨A⟩ | RTF p95 ⟨B⟩ | ⟨A⟩ | audio-s/s ⟨B⟩ | ⟨A⟩ | gap p95 ⟨B⟩ | ⟨A⟩ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1.0 | 200 | 197 | 225 | 215 | 0.421 | 0.416 | 0.429 | 0.429 | 5.0 | 5.0 | 38 | 38 |
| 2.0 | 235 | 231 | 249 | 243 | 0.475 | 0.471 | 0.486 | 0.482 | 9.0 | 8.9 | 52 | 52 |
| 4.0 | 254 | 249 | 269 | 269 | 0.629 | 0.629 | 0.662 | 0.655 | 17.4 | 17.4 | 61 | 62 |
| 8.0 | 308 | 300 | 355 | 342 | 1.105 | 1.065 | 1.211 | 1.232 | 23.4 | 32.6 | 125 | 124 |
| 12.0 | 717 | 347 | 1573 | 434 | 1.571 | 1.677 | 1.687 | 1.790 | 32.4 | 34.4 | 190 | 183 |
| 16.0 | 2653 | 396 | 5273 | 577 | 1.873 | 2.097 | 2.241 | 2.187 | 45.1 | 43.4 | 196 | 251 |

#### Simultaneous burst

| burst | TTFA p50 ⟨B⟩ | ⟨A⟩ | TTFA p95 ⟨B⟩ | ⟨A⟩ | RTF p50 ⟨B⟩ | ⟨A⟩ | RTF p95 ⟨B⟩ | ⟨A⟩ | audio-s/s ⟨B⟩ | ⟨A⟩ | gap p95 ⟨B⟩ | ⟨A⟩ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 8 | 192 | 193 | 217 | 194 | 0.485 | 0.477 | 0.503 | 0.485 | 16.4 | 16.4 | 55 | 47 |
| 16 | 218 | 206 | 219 | 206 | 0.549 | 0.545 | 0.564 | 0.552 | 28.9 | 29.2 | 63 | 66 |
| 32 | 272 | 274 | 305 | 321 | 0.692 | 0.646 | 0.712 | 0.674 | 45.0 | 48.0 | 107 | 94 |
| 64 | 3302 | 432 | 3610 | 508 | 1.187 | 0.873 | 1.392 | 0.898 | 47.8 | 71.8 | 149 | 125 |

#### Text length

| prompt | TTFA p50 ⟨B⟩ | ⟨A⟩ | TTFA p95 ⟨B⟩ | ⟨A⟩ | RTF p50 ⟨B⟩ | ⟨A⟩ | RTF p95 ⟨B⟩ | ⟨A⟩ | audio-s/s ⟨B⟩ | ⟨A⟩ | gap p95 ⟨B⟩ | ⟨A⟩ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| short | 151 | 151 | 153 | 152 | 0.353 | 0.350 | 0.355 | 0.352 | 2.8 | 2.9 | 30 | 30 |
| medium | 152 | 152 | 161 | 152 | 0.351 | 0.348 | 0.351 | 0.348 | 2.9 | 2.9 | 32 | 30 |
| long | 152 | 152 | 155 | 152 | 0.351 | 0.348 | 0.351 | 0.351 | 2.9 | 2.9 | 32 | 30 |

#### Language

| lang | TTFA p50 ⟨B⟩ | ⟨A⟩ | TTFA p95 ⟨B⟩ | ⟨A⟩ | RTF p50 ⟨B⟩ | ⟨A⟩ | RTF p95 ⟨B⟩ | ⟨A⟩ | audio-s/s ⟨B⟩ | ⟨A⟩ | gap p95 ⟨B⟩ | ⟨A⟩ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hi | 152 | 152 | 154 | 152 | 0.351 | 0.349 | 0.352 | 0.349 | 2.9 | 2.9 | 32 | 30 |
| bn | 152 | 151 | 155 | 152 | 0.352 | 0.350 | 0.353 | 0.350 | 2.8 | 2.9 | 32 | 30 |
| ta | 152 | 151 | 154 | 154 | 0.351 | 0.348 | 0.352 | 0.349 | 2.9 | 2.9 | 32 | 30 |
| te | 152 | 152 | 153 | 153 | 0.352 | 0.349 | 0.352 | 0.350 | 2.8 | 2.9 | 32 | 30 |
| mr | 151 | 151 | 153 | 152 | 0.352 | 0.349 | 0.353 | 0.350 | 2.8 | 2.9 | 32 | 30 |
| gu | 152 | 152 | 154 | 154 | 0.352 | 0.350 | 0.353 | 0.350 | 2.8 | 2.9 | 32 | 30 |

#### Streaming quality envelope (after config)

| level | audio-s/s | gap p50 | gap p95 | depth max | vs 85 ms frame |
|---|---|---|---|---|---|
| 1 | 2.9 | 30 | 30 | 1 | clean |
| 2 | 5.0 | 34 | 34 | 2 | clean |
| 4 | 8.8 | 35 | 42 | 4 | clean |
| 8 | 14.4 | 36 | 60 | 8 | clean |
| 12 | 16.9 | 34 | 83 | 12 | clean |
| 16 | 20.7 | 35 | 93 | 16 | tail late |
| 24 | 16.3 | 42 | 92 | 24 | tail late |
| 32 | 45.5 | 46 | 96 | 32 | tail late |
| 48 | 60.9 | 55 | 108 | 48 | tail late |
| 64 | 72.5 | 62 | 125 | 64 | tail late |

#### Streaming quality under unbounded arrivals (after config)

| level | audio-s/s | gap p50 | gap p95 | depth max | vs 85 ms frame |
|---|---|---|---|---|---|
| 1.0 | 5.2 | 35 | 51 | 7 | clean |
| 2.0 | 7.4 | 33 | 67 | 11 | clean |
| 4.0 | 18.8 | 55 | 85 | 22 | tail late |
| 8.0 | 35.2 | 92 | 130 | 60 | **starving** |
| 12.0 | 48.0 | 124 | 170 | 105 | **starving** |
| 16.0 | 59.7 | 149 | 234 | 151 | **starving** |

---

## 4. Capacity and operating envelope

Throughput alone is misleading: the service can produce 72 audio-seconds per second, but not all of it is
usable for live playback. Judged against the 85.33 ms frame period, on the **after** config:

| in-flight streams | throughput | streaming quality | use |
|---|---|---|---|
| ≤ 12 | to 17 audio-s/s | gap p95 ≤ 85 ms — **clean** | safe for live calls |
| 16 – 64 | to 72 audio-s/s | median comfortable, ~5% of frames late | usable with a client jitter buffer |
| unbounded arrivals > ~4–6/s | 60 audio-s/s | **gap p50 above the frame period** — continuous stutter | not usable for live audio |

The distinction is **bounded vs unbounded work in flight**, not raw load. At 64 concurrent the queue is
capped and gap p50 is 62 ms; at 16 req/s open-loop the queue grows to 151 and gap p50 is 149 ms. Same
machine, same throughput band, completely different caller experience.

**Sustainable arrival rate for clean audio: ~4 requests/second** — where RTF crosses 1.0 and gap p95 reaches
85.4 ms against an 85.33 ms budget. Identical in both configs.

---

## 5. Findings

1. **The engine was sized for a different GPU.** `compose.extra.yml` set `gpu_memory_utilization=0.12`,
   documented in its own comment as sized for a shared H200 ("Raise it on a card you actually own"). On this
   dedicated 96 GB card that left 87 GB idle and capped the KV cache at 6.69 GiB.

2. **The binding limit was admission, not memory.** The engine's boot line "Maximum concurrency 7.64x" is
   computed for 8,192-token requests; real utterances here use ~430 tokens, so cache was never the
   constraint. The ceiling was `max_num_seqs=32`, which is why throughput sat flat at ~46 audio-s/s under
   three different load models and rose 52% the moment the cap was raised.

3. **More concurrency does not buy more *clean* concurrency.** Inter-chunk gaps at 8 req/s are unchanged
   (91.2 → 91.8 ms) and at 16 req/s are worse (107.5 → 149.0 ms). Extra slots divide the same compute among
   more streams, converting "some callers wait" into "more callers stutter."

4. **TTFA is flat in text length** — 151.3 ms at 23 chars, 152.0 ms at 157 chars (0.5% across a 6.8× range).
   Confirms the path is genuinely incremental and nothing buffers the utterance before sending.

5. **No language or voice penalty.** Six scripts span 151.3–151.7 ms TTFA and 0.351–0.352 RTF.

6. **The gateway has no admission control.** At 16 req/s it accepted all 160 requests and queued them to a
   depth of 151 rather than shedding or signalling backpressure. Nothing fails; everything degrades.

7. **Bursty arrivals behave differently after the change.** Before, evenly-paced arrivals beat Poisson at the
   knee (355 vs 637 ms p95 at 8/s). After, Poisson delivers ~35% *more* throughput than a metronome at 12–16
   req/s. A plausible cause is fuller vLLM batches under bursty arrival, but batch sizes were not measured,
   so this is an observation, not a conclusion.

8. **GPU utilisation is useless here.** `nvidia-smi` reports 100% at every level including a single request,
   because it measures kernel residency, not work. The counters that would settle it (SM_ACTIVE,
   PIPE_TENSOR_ACTIVE) need DCGM, which is not installed. Power draw is the better proxy: 282 W of 600 W at
   idle-ish load.

---

## 6. Recommendations

| # | Action | Basis | Effort |
|---|---|---|---|
| 1 | Commit `gpu_memory_utilization=0.90`, `max_num_seqs=64`, `decoder.max_batch=64`, warmup widths to 64 in `compose.extra.yml`, replacing the shared-H200 defaults and correcting the comment at `:12-18` | §3, §5.1–5.2. Currently applied only via gitignored `model-server/.env`, so it is lost on a fresh checkout | low |
| 2 | Add admission control at the gateway — cap in-flight TTS requests and return a retryable error beyond it | §5.6. Unbounded queueing is the difference between "clean" and "stutters throughout" | medium |
| 3 | Treat **4 req/s** as the per-GPU planning figure for live calls, not the 72 audio-s/s peak | §4 | none |
| 4 | Re-run this suite on any checkpoint or vLLM change; it is now one command per arm | §8 | none |
| 5 | Do not raise `max_num_seqs` further without re-measuring gaps — beyond 64 it trades smoothness for throughput | §5.3 | none |

---

## 7. Known issue affecting test design (not a load-test finding)

A separate open bug makes the model speak the first clause of a multi-clause input, then emit **silent
frames** until the token cap — 18.69 s of audio containing ~2.2 s of speech. Measured at 33–42% of runs on
multi-clause input, in **every style including no-style**, triggered by any mid-sentence break including a
comma; single-clause input is unaffected (0/24). All prompts here are therefore single-clause, and the
harness counts muted runs separately and excludes them from aggregates. **0 muted runs occurred in this
report's 2,880 requests**, confirming the corpus choice worked.

---

## 8. Verification

| check | result |
|---|---|
| All configured languages produce audio at 24 kHz | PASS — 6/6 languages, 12 runs each |
| Streaming emits multiple chunks with clean end-of-stream | PASS — 61 chunks per request at medium length |
| Audio is non-empty and non-silent | PASS — sanity guard on every request; 0 silent |
| Zero failures under load | **1 failure in 2,880** — `RemoteProtocolError: Server disconnected` at 64 concurrent, before config. Server-side `errors_total` stayed 0, so the gateway dropped it without counting it |
| No per-request VRAM growth | PASS — flat at 12,720 MiB (before) / 88,856 MiB (after) across every level |
| `streams_active` returns to 0 after every cell | PASS — enforced as a gate between cells |
| Server request counter matches requests issued | PASS |
| TTFA does not grow with text length | PASS — §5.4 |
| Clean restart at the new config | PASS — ready in 116 s, no OOM at 0.90 |

---

## 9. Not measured

- **Audio quality / WER** — out of scope by decision. Latency without quality cannot distinguish fast
  correct audio from fast garbled audio; the sanity guard only catches silence and truncation.
- **Buffered synthesis** (`response_format: wav`) — out of scope; this deployment is for live streaming.
- **WebSocket and SSE transports** — the harness supports both, but this report covers the OpenAI-spec
  HTTP endpoint only, as scoped.
- **SM occupancy / tensor-pipe activity** — needs DCGM, not installed. Reported as `NOT MEASURED` rather
  than inferred from `utilization.gpu`.
- **Sustained soak** — the suite exists (`sweep.py sustained`) but was not run; drift over hours is unknown.
- **Multi-GPU / tensor parallel** — single GPU, `tp=1` throughout.

---

## 10. Provenance

| | |
|---|---|
| Harness | `model-server/tests/bench/` — `tts_client.py`, `sweep.py`, `compare.py`, `report.py`, `gpu_sampler.py` |
| Raw data | `model-server/tests/bench/results/{before,after}_*.json` (14 files) |
| Run logs | `results/{before,after}_run.log` — **not committed** (`*.log` is gitignored repo-wide); the JSON files carry every number the report uses |
| Reproduce | `./run_matrix.sh before` · apply config · `./run_matrix.sh after` · `python compare.py` |
| Requests | 2,880 total, 2,879 succeeded, 1 failed, 0 muted |
| Seed | 1234 (arrival schedules reproducible; model sampling is unseeded at `temperature 0.6`) |
| GPU sampler | 10 Hz `nvidia-smi`; DCGM counters unavailable |

**Caveat on two cells:** at c=12 and c=24 the request count is close to the concurrency level, so only one
or two waves complete and `audio-s/s` there is noisy (e.g. 16.3 at c=24 vs 45.5 at c=32). Latency
percentiles at those points are sound; the throughput figures are not. Cells at c≥32 use n≥32.

---

## Appendix — full per-arm detail

## Configuration — `before`

| field | value |
|---|---|
| host | ip-172-31-23-34 |
| GPU | NVIDIA RTX PRO 6000 Blackwell Server Edition, 97887 MiB, 595.91.07, 12.0 |
| model | orpheus-indic (/models/indic-speak) |
| quantization | fp8 |
| endpoint under test | POST /v1/audio/speech (response_format=pcm) |
| gateway | http://127.0.0.1:8100 |
| gpu_memory_utilization | 0.12 |
| max_num_seqs | 32 |
| decoder.max_batch | 32 |
| max_model_len | 8192 |
| temperature / repetition_penalty | 0.6 / 1.0 |
| voice / style / language | Kavya / none / hi |
| run (UTC) | 2026-09-18T10:23:37Z |
| KV cache (engine boot) | Available KV cache memory: 6.69 GiB · GPU KV cache size: 62,576 tokens · Maximum concurrency for 8,192 tokens per request: 7.64x |

### Single request (concurrency 1, n=20)

| metric | value |
|---|---|
| requests ok | 20/20 |
| muted (runaway) | 0 |
| TTFA p50 / p95 / p99 (ms) | 156 / 158 / 158 |
| TTFA min / max (ms) | 152 / 158 |
| RTF p50 / p95 | 0.361 / 0.361 |
| audio duration p50 (s) | 5.21 |
| total per request p50 (s) | 1.88 |
| chunks per request p50 | 61 |
| inter-chunk gap p50 / p95 / max (ms) | 29.8 / 31.9 / 32.0 |
| GPU util p50 / max (%) | 100 / 100 |
| VRAM max (MiB) | 12720 |
| power p50 / max (W) | 282 / 288 |

### Concurrency — closed loop

A fixed pool of callers; a new request starts only when one finishes. No queue by construction, so TTFA here is service time.

| conc | ok | muted | TTFA p50 | p95 | p99 | RTF p50 | RTF p95 | audio s | gap p95 | req/s | audio-s/s | GPU% | VRAM MiB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 20/20 | 0 | 152 | 156 | 156 | 0.351 | 0.356 | 5.29 | 31.7 | 0.53 | 2.8 | 100 | 12720 |
| 2 | 20/20 | 0 | 179 | 187 | 187 | 0.411 | 0.416 | 5.38 | 34.2 | 0.91 | 4.9 | 100 | 12720 |
| 4 | 20/20 | 0 | 196 | 236 | 236 | 0.458 | 0.466 | 5.38 | 43.3 | 1.62 | 8.8 | 100 | 12720 |
| 8 | 20/20 | 0 | 241 | 262 | 262 | 0.485 | 0.559 | 5.21 | 64.3 | 2.70 | 14.1 | 100 | 12720 |
| 12 | 20/20 | 0 | 200 | 290 | 290 | 0.544 | 0.583 | 5.29 | 76.2 | 1.77 | 10.8 | 100 | 12720 |
| 16 | 20/20 | 0 | 216 | 280 | 280 | 0.574 | 0.598 | 5.29 | 74.2 | 3.88 | 20.6 | 100 | 12720 |
| 24 | 24/24 | 0 | 231 | 271 | 271 | 0.663 | 0.682 | 5.29 | 107.5 | 6.35 | 34.0 | 100 | 12720 |
| 32 | 32/32 | 0 | 253 | 293 | 293 | 0.676 | 0.702 | 5.38 | 94.0 | 8.62 | 45.9 | 100 | 12720 |
| 48 | 48/48 | 0 | 365 | 3566 | 3569 | 0.787 | 1.296 | 5.21 | 127.0 | 7.44 | 39.2 | 100 | 12742 |
| 64 | 63/64 | 0 | 369 | 3655 | 3882 | 0.822 | 1.390 | 5.29 | 153.2 | 9.07 | 47.8 | 100 | 12742 |

### Arrival rate — open loop, Poisson

Arrival times fixed before the run and launched on schedule regardless of whether the server keeps up. TTFA is measured from the **scheduled** arrival, so queueing is counted rather than hidden.

| rate/s | ok | muted | TTFA p50 | p95 | p99 | RTF p50 | RTF p95 | audio s | gap p95 | queue p50 | queue p95 | depth max | audio-s/s | client-bound |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1.0 | 20/20 | 0 | 221 | 261 | 261 | 0.472 | 0.504 | 5.29 | 51.9 | 1 | 2 | 7 | 5.2 | no |
| 2.0 | 20/20 | 0 | 242 | 272 | 272 | 0.505 | 0.554 | 5.29 | 68.0 | 1 | 1 | 12 | 9.2 | no |
| 4.0 | 40/40 | 0 | 279 | 312 | 314 | 0.711 | 0.771 | 5.21 | 85.6 | 1 | 2 | 22 | 18.8 | no |
| 8.0 | 80/80 | 0 | 331 | 637 | 704 | 1.195 | 1.300 | 5.21 | 131.9 | 1 | 1 | 61 | 32.1 | no |
| 12.0 | 120/120 | 0 | 1528 | 2929 | 3029 | 1.448 | 1.799 | 5.29 | 181.0 | 1 | 2 | 92 | 42.5 | no |
| 16.0 | 160/160 | 0 | 3058 | 5905 | 6006 | 1.955 | 2.337 | 5.29 | 205.9 | 1 | 2 | 127 | 46.0 | no |

### Arrival rate — open loop, evenly paced

Same, with deterministic spacing.

| rate/s | ok | muted | TTFA p50 | p95 | p99 | RTF p50 | RTF p95 | audio s | gap p95 | queue p50 | queue p95 | depth max | audio-s/s | client-bound |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1.0 | 20/20 | 0 | 200 | 225 | 225 | 0.421 | 0.429 | 5.29 | 38.2 | 1 | 2 | 3 | 5.0 | no |
| 2.0 | 20/20 | 0 | 235 | 249 | 249 | 0.475 | 0.486 | 5.29 | 51.6 | 1 | 1 | 6 | 9.0 | no |
| 4.0 | 40/40 | 0 | 254 | 269 | 275 | 0.629 | 0.662 | 5.21 | 61.0 | 1 | 2 | 14 | 17.4 | no |
| 8.0 | 80/80 | 0 | 308 | 355 | 379 | 1.105 | 1.211 | 5.29 | 125.0 | 1 | 2 | 50 | 23.4 | no |
| 12.0 | 120/120 | 0 | 717 | 1573 | 1700 | 1.571 | 1.687 | 5.29 | 190.3 | 1 | 2 | 90 | 32.4 | no |
| 16.0 | 160/160 | 0 | 2653 | 5273 | 5397 | 1.873 | 2.241 | 5.29 | 195.7 | 1 | 1 | 125 | 45.1 | no |

### Burst — all requests at once

The artificial thundering herd: every request arrives simultaneously. A real worst case, not a typical one.

| burst | ok | muted | TTFA p50 | p95 | p99 | RTF p50 | RTF p95 | audio s | gap p95 | queue p50 | queue p95 | depth max | audio-s/s | client-bound |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 8 | 8/8 | 0 | 192 | 217 | 217 | 0.485 | 0.503 | 5.38 | 55.2 | 2 | 3 | 8 | 16.4 | no |
| 16 | 16/16 | 0 | 218 | 219 | 219 | 0.549 | 0.564 | 5.21 | 63.4 | 3 | 4 | 16 | 28.9 | no |
| 32 | 32/32 | 0 | 272 | 305 | 305 | 0.692 | 0.712 | 5.29 | 107.2 | 6 | 9 | 32 | 45.0 | no |
| 64 | 64/64 | 0 | 3302 | 3610 | 3914 | 1.187 | 1.392 | 5.21 | 148.9 | 11 | 21 | 64 | 47.8 | no |

### Text length

TTFA should stay flat as text grows; if it climbs, something is buffering the whole utterance before sending.

| prompt | chars | ok | muted | TTFA p50 | p95 | p99 | RTF p50 | RTF p95 | audio s | gap p95 |
|---|---|---|---|---|---|---|---|---|---|---|
| short | 23 | 20/20 | 0 | 151 | 153 | 153 | 0.353 | 0.355 | 2.39 | 29.8 |
| medium | 58 | 20/20 | 0 | 152 | 161 | 161 | 0.351 | 0.351 | 5.21 | 31.6 |
| long | 157 | 20/20 | 0 | 152 | 155 | 155 | 0.351 | 0.351 | 13.48 | 31.7 |

### Language and voice

| lang | chars | voice | ok | muted | TTFA p50 | p95 | p99 | RTF p50 | RTF p95 | audio s | gap p95 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| hi | 43 | Kavya | 12/12 | 0 | 152 | 154 | 154 | 0.351 | 0.352 | 3.93 | 31.7 |
| bn | 30 | Ishita | 12/12 | 0 | 152 | 155 | 155 | 0.352 | 0.353 | 3.33 | 31.7 |
| ta | 44 | Anitha | 12/12 | 0 | 152 | 154 | 154 | 0.351 | 0.352 | 4.44 | 31.7 |
| te | 37 | Sravani | 12/12 | 0 | 152 | 153 | 153 | 0.352 | 0.352 | 3.50 | 31.6 |
| mr | 31 | Anagha | 12/12 | 0 | 151 | 153 | 153 | 0.352 | 0.353 | 3.58 | 31.6 |
| gu | 30 | Dhara | 12/12 | 0 | 152 | 154 | 154 | 0.352 | 0.353 | 3.24 | 31.6 |

## Configuration — `after`

| field | value |
|---|---|
| host | ip-172-31-23-34 |
| GPU | NVIDIA RTX PRO 6000 Blackwell Server Edition, 97887 MiB, 595.91.07, 12.0 |
| model | orpheus-indic (/models/indic-speak) |
| quantization | fp8 |
| endpoint under test | POST /v1/audio/speech (response_format=pcm) |
| gateway | http://127.0.0.1:8100 |
| gpu_memory_utilization | 0.90 |
| max_num_seqs | 64 |
| decoder.max_batch | 64 |
| max_model_len | 8192 |
| temperature / repetition_penalty | 0.6 / 1.0 |
| voice / style / language | Kavya / none / hi |
| run (UTC) | 2026-09-18T10:38:30Z |
| KV cache (engine boot) | Available KV cache memory: 80.76 GiB · GPU KV cache size: 756,128 tokens · Maximum concurrency for 8,192 tokens per request: 92.30x |

### Single request (concurrency 1, n=20)

| metric | value |
|---|---|
| requests ok | 20/20 |
| muted (runaway) | 0 |
| TTFA p50 / p95 / p99 (ms) | 154 / 156 / 156 |
| TTFA min / max (ms) | 154 / 156 |
| RTF p50 / p95 | 0.358 / 0.358 |
| audio duration p50 (s) | 5.29 |
| total per request p50 (s) | 1.89 |
| chunks per request p50 | 62 |
| inter-chunk gap p50 / p95 / max (ms) | 29.8 / 31.9 / 32.6 |
| GPU util p50 / max (%) | 100 / 100 |
| VRAM max (MiB) | 88856 |
| power p50 / max (W) | 284 / 289 |

### Concurrency — closed loop

A fixed pool of callers; a new request starts only when one finishes. No queue by construction, so TTFA here is service time.

| conc | ok | muted | TTFA p50 | p95 | p99 | RTF p50 | RTF p95 | audio s | gap p95 | req/s | audio-s/s | GPU% | VRAM MiB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 20/20 | 0 | 152 | 160 | 160 | 0.351 | 0.353 | 5.21 | 29.8 | 0.55 | 2.9 | 100 | 88856 |
| 2 | 20/20 | 0 | 167 | 180 | 180 | 0.404 | 0.409 | 5.29 | 34.2 | 0.94 | 5.0 | 100 | 88856 |
| 4 | 20/20 | 0 | 202 | 223 | 223 | 0.443 | 0.463 | 5.38 | 41.8 | 1.66 | 8.8 | 100 | 88856 |
| 8 | 20/20 | 0 | 242 | 269 | 269 | 0.483 | 0.523 | 5.21 | 59.7 | 2.77 | 14.4 | 100 | 88856 |
| 12 | 20/20 | 0 | 202 | 282 | 282 | 0.541 | 0.605 | 5.29 | 83.1 | 3.10 | 16.9 | 100 | 88856 |
| 16 | 20/20 | 0 | 200 | 311 | 311 | 0.589 | 0.611 | 5.38 | 93.1 | 3.92 | 20.7 | 100 | 88856 |
| 24 | 24/24 | 0 | 215 | 251 | 251 | 0.629 | 0.648 | 5.21 | 92.1 | 2.75 | 16.3 | 100 | 88856 |
| 32 | 32/32 | 0 | 273 | 275 | 275 | 0.682 | 0.697 | 5.29 | 96.2 | 8.55 | 45.5 | 100 | 88856 |
| 48 | 48/48 | 0 | 309 | 365 | 410 | 0.768 | 0.793 | 5.21 | 107.9 | 11.54 | 60.9 | 100 | 88856 |
| 64 | 64/64 | 0 | 455 | 601 | 605 | 0.859 | 0.895 | 5.29 | 124.8 | 13.74 | 72.5 | 100 | 88856 |

### Arrival rate — open loop, Poisson

Arrival times fixed before the run and launched on schedule regardless of whether the server keeps up. TTFA is measured from the **scheduled** arrival, so queueing is counted rather than hidden.

| rate/s | ok | muted | TTFA p50 | p95 | p99 | RTF p50 | RTF p95 | audio s | gap p95 | queue p50 | queue p95 | depth max | audio-s/s | client-bound |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1.0 | 20/20 | 0 | 209 | 252 | 252 | 0.450 | 0.496 | 5.38 | 50.9 | 1 | 2 | 7 | 5.2 | no |
| 2.0 | 20/20 | 0 | 234 | 268 | 268 | 0.514 | 0.559 | 5.29 | 67.1 | 1 | 2 | 11 | 7.4 | no |
| 4.0 | 40/40 | 0 | 262 | 296 | 305 | 0.724 | 0.773 | 5.21 | 85.4 | 1 | 1 | 22 | 18.8 | no |
| 8.0 | 80/80 | 0 | 312 | 362 | 380 | 1.090 | 1.231 | 5.29 | 130.1 | 1 | 1 | 60 | 35.2 | no |
| 12.0 | 120/120 | 0 | 355 | 431 | 446 | 1.402 | 1.604 | 5.29 | 170.5 | 1 | 2 | 105 | 48.0 | no |
| 16.0 | 160/160 | 0 | 395 | 566 | 592 | 1.623 | 1.908 | 5.21 | 234.2 | 1 | 2 | 151 | 59.7 | no |

### Arrival rate — open loop, evenly paced

Same, with deterministic spacing.

| rate/s | ok | muted | TTFA p50 | p95 | p99 | RTF p50 | RTF p95 | audio s | gap p95 | queue p50 | queue p95 | depth max | audio-s/s | client-bound |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1.0 | 20/20 | 0 | 197 | 215 | 215 | 0.416 | 0.429 | 5.29 | 38.2 | 1 | 2 | 3 | 5.0 | no |
| 2.0 | 20/20 | 0 | 231 | 243 | 243 | 0.471 | 0.482 | 5.21 | 51.7 | 1 | 2 | 6 | 8.9 | no |
| 4.0 | 40/40 | 0 | 249 | 269 | 273 | 0.629 | 0.655 | 5.29 | 62.0 | 1 | 2 | 15 | 17.4 | no |
| 8.0 | 80/80 | 0 | 300 | 342 | 368 | 1.065 | 1.232 | 5.29 | 123.8 | 1 | 2 | 53 | 32.6 | no |
| 12.0 | 120/120 | 0 | 347 | 434 | 450 | 1.677 | 1.790 | 5.21 | 183.1 | 1 | 2 | 107 | 34.4 | no |
| 16.0 | 160/160 | 0 | 396 | 577 | 595 | 2.097 | 2.187 | 5.21 | 251.2 | 1 | 2 | 157 | 43.4 | no |

### Burst — all requests at once

The artificial thundering herd: every request arrives simultaneously. A real worst case, not a typical one.

| burst | ok | muted | TTFA p50 | p95 | p99 | RTF p50 | RTF p95 | audio s | gap p95 | queue p50 | queue p95 | depth max | audio-s/s | client-bound |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 8 | 8/8 | 0 | 193 | 194 | 194 | 0.477 | 0.485 | 5.38 | 47.1 | 2 | 3 | 8 | 16.4 | no |
| 16 | 16/16 | 0 | 206 | 206 | 206 | 0.545 | 0.552 | 5.29 | 66.0 | 3 | 4 | 16 | 29.2 | no |
| 32 | 32/32 | 0 | 274 | 321 | 321 | 0.646 | 0.674 | 5.21 | 93.5 | 7 | 10 | 32 | 48.0 | no |
| 64 | 64/64 | 0 | 432 | 508 | 508 | 0.873 | 0.898 | 5.21 | 124.9 | 12 | 22 | 64 | 71.8 | no |

### Text length

TTFA should stay flat as text grows; if it climbs, something is buffering the whole utterance before sending.

| prompt | chars | ok | muted | TTFA p50 | p95 | p99 | RTF p50 | RTF p95 | audio s | gap p95 |
|---|---|---|---|---|---|---|---|---|---|---|
| short | 23 | 20/20 | 0 | 151 | 152 | 152 | 0.350 | 0.352 | 2.30 | 29.7 |
| medium | 58 | 20/20 | 0 | 152 | 152 | 152 | 0.348 | 0.348 | 5.21 | 29.7 |
| long | 157 | 20/20 | 0 | 152 | 152 | 152 | 0.348 | 0.351 | 12.97 | 29.7 |

### Language and voice

| lang | chars | voice | ok | muted | TTFA p50 | p95 | p99 | RTF p50 | RTF p95 | audio s | gap p95 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| hi | 43 | Kavya | 12/12 | 0 | 152 | 152 | 152 | 0.349 | 0.349 | 4.35 | 29.7 |
| bn | 30 | Ishita | 12/12 | 0 | 151 | 152 | 152 | 0.350 | 0.350 | 3.07 | 29.7 |
| ta | 44 | Anitha | 12/12 | 0 | 151 | 154 | 154 | 0.348 | 0.349 | 4.52 | 29.7 |
| te | 37 | Sravani | 12/12 | 0 | 152 | 153 | 153 | 0.349 | 0.350 | 3.50 | 29.7 |
| mr | 31 | Anagha | 12/12 | 0 | 151 | 152 | 152 | 0.349 | 0.350 | 3.75 | 29.7 |
| gu | 30 | Dhara | 12/12 | 0 | 152 | 154 | 154 | 0.350 | 0.350 | 3.24 | 29.7 |
