# Concurrency bench: streaming STT and TTS

These scripts measure how many requests a model server can handle at the same time and still keep up with real time. They cover the streaming STT model (indic-nemotron, over WebSocket) and the streaming TTS model (Orpheus, via `POST /v1/audio/speech`). They are plain HTTP and WebSocket clients, so they run from any machine that can reach the server, against any deployment of this model-server.

- [What the tests measure](#what-the-tests-measure)
- [Prerequisites](#prerequisites)
- [Preparing the server](#preparing-the-server)
- [Quick start](#quick-start)
- [Running the steps by hand](#running-the-steps-by-hand)
- [Metrics and the pass rule](#metrics-and-the-pass-rule)
- [Output](#output)
- [Reading the results, and caveats](#reading-the-results-and-caveats)
- [Diagnosing TTS runaways](#diagnosing-tts-runaways)
- [Troubleshooting](#troubleshooting)

## What the tests measure

For each concurrency level **N** (default 1, 2, 4, 8, 16, 32, 64, 128, 256) there are two tests:

| Test | How the N requests start | What it represents |
|---|---|---|
| **A: single batch** (`sync`) | All N at the same instant | The worst case: a burst hits the server at once |
| **B: random within 1 s** (`random`) | N start times drawn uniformly at random within a 1 s window, redrawn every round | Independent callers arriving close together. This is a Poisson process conditioned on exactly N arrivals. |

- **Rounds.** Each N is run 3 times (rounds) and the results are pooled, so one bad round cannot decide the verdict and N = 1 still produces a percentile. The server is allowed to go idle between rounds and between levels. Nothing stops early: every level runs even after one fails.
- **Warm-up.** Before measuring, the scripts send 5 single requests, then batches of 8, 64 and 256. These results are discarded, because a cold model can be slow for the first few requests at a new batch size. The warm-up has a 10-minute budget. A batch still running when the budget runs out is cut off with a warning, and the test goes ahead.
- **One request, by model:**
  - **STT.** Open the socket, stream one clip at real time in 160 ms frames, send `flush_eos`, then read the final transcript.
  - **TTS.** One streaming synthesis of a fixed sentence (`response_format=pcm`).

## Prerequisites

- **Python 3.10 or later** on the client machine. Install the dependencies with `./run.sh setup`, which creates `.venv`, or with `pip install -r requirements.txt`.
- **A running server** with the models you want to test. The standard model-server stack serves both models through its gateway, by default at `http://<host>:8100`.
- **A voice roster for the language.** The TTS server must list your chosen language at `/tts/v1/voices`.
- **An STT corpus**, which is either:
  - synthesised with the running TTS (the default), or
  - your own WAV recordings with transcripts.
- **Open-file limit.** At high N the client holds hundreds of sockets. `run.sh` raises `ulimit -n` itself, or warns if it cannot.

## Preparing the server

These scripts only send traffic. They do not start, stop or reconfigure anything. What they measure is the server **as configured**, so set it up for the question you are asking before you run them.

1. **Give the model a GPU to itself**, or at least note what else is running on it. Other workloads on the same card compete for compute and memory, and the result then describes the mix rather than the model.
2. **Raise the concurrency caps above the highest N you test.** If you don't, the server queues requests and you measure the cap, not the model. These are the model-server's variables:

   | Model | Variable | Stack default | Meaning |
   |---|---|---|---|
   | STT (indic-nemotron) | `NEMOTRON_MAX_BATCH` (sets `ASR_MAX_BATCH`) | 128 | Most streams batched into one model step |
   | TTS (Orpheus) | `ORPHEUS_MAX_NUM_SEQS` | 32 | Most sequences vLLM runs at once |
   | TTS (Orpheus) | `ORPHEUS_DECODER_MAX_BATCH` | 32 | Batch size of the audio decoder |
   | TTS (Orpheus) | `ORPHEUS_GPU_MEMORY_UTILIZATION` | 0.12 | Share of GPU memory vLLM may take, which sets its KV cache size |
   | TTS (Orpheus) | `ORPHEUS_WARMUP_WIDTHS` | 1,2,4,8,16,32 | Batch widths the server compiles at startup |

   To test up to N = 256 on a dedicated card, for example: `NEMOTRON_MAX_BATCH=256`, `ORPHEUS_MAX_NUM_SEQS=256`, `ORPHEUS_DECODER_MAX_BATCH=256`, `ORPHEUS_GPU_MEMORY_UTILIZATION=0.90`, `ORPHEUS_WARMUP_WIDTHS=1,2,4,8,16,32,64,128,256`. The Orpheus memory value must fit what the card has free; lower it when the card is shared.
3. **Wait until the server is healthy.** `GET /stt/health` should report `"status": "healthy"`, and `GET /tts/health` should report `"ready": true`.
4. **Record what you set.** Pass each setting with `--note`, or put it in the report yourself. The numbers mean nothing without the configuration.

## Quick start

```bash
cd model-server/tests/concurrency-bench
./run.sh setup                      # .venv + requirements
cp config.example.env config.env    # then edit STT_URL / TTS_URL / LANGUAGE
./run.sh all                        # corpus (first time) -> STT -> TTS -> report
```

The report is at `results/<RUN_ID>/report.md`. A full matrix takes roughly 15 minutes for STT and 25 minutes for TTS on a large GPU, plus warm-up, and longer on slower cards. Run it inside `tmux` or `screen` so a dropped SSH session doesn't end it.

**Optional: the TTS runaway rate at N = 1.** Run `./run.sh runaway` before the report. The report then includes the runaway rate (see [below](#reading-the-results-and-caveats)).

Every value in `config.env` can be overridden for one run, for example `LEVELS=1,2,4,8 ROUNDS=1 ./run.sh tts` for a smoke test. To run steps separately into the same results folder, export the run ID first:

```bash
export RUN_ID=my-gpu-2026-10-01
./run.sh stt
./run.sh tts
./run.sh report
```

## Running the steps by hand

`run.sh` only passes `config.env` to these scripts. Each script also runs on its own, and `--help` lists every option.

**1. Build the STT corpus.** This is done once per language. Either synthesise the clips with the running TTS:

```bash
python make_corpus.py synth --tts-url http://HOST:8100 --language mr \
    --voices Anagha,Chinmay --out corpus/mr
```

Or bring your own recordings: a folder of WAVs plus a CSV with the columns `file,text[,bucket]`. Clips are converted to 16 kHz mono. Without a `bucket` column, each clip is bucketed by length: short below 3.5 s, medium below 10 s, long otherwise.

```bash
python make_corpus.py import --wav-dir my_clips --transcripts my_clips/transcripts.csv \
    --language mr --out corpus/mr
```

Synthesised clips are checked before use. A clip that is silent, or far off the length its text should take, is re-synthesised up to three times and then dropped. The dropped clips are listed in `manifest.json`.

**2. Run the STT tests.**

```bash
python stt_load.py --url http://HOST:8100 --manifest corpus/mr/manifest.json \
    --language mr --out-dir results/run1 --note NEMOTRON_MAX_BATCH=256
```

**3. Run the TTS tests.**

```bash
python tts_load.py --url http://HOST:8100 --language mr --voice Anagha \
    --out-dir results/run1 --note ORPHEUS_MAX_NUM_SEQS=256
```

**4. Optional: the runaway check.** Details are in [Diagnosing TTS runaways](#diagnosing-tts-runaways).

```bash
python runaway_check.py --url http://HOST:8100 --language mr --n 200 --protocol ws \
    --out-dir results/run1
```

**5. Write the report.**

```bash
python report.py --results results/run1
```

Options you are likely to change:

| Option | Default | Scripts |
|---|---|---|
| `--levels` | `1,2,4,8,16,32,64,128,256` | stt, tts |
| `--mode` | `both` (`sync` = Test A, `random` = Test B) | stt, tts |
| `--rounds` | 3 | stt, tts |
| `--arrival-window` | 1.0 s | stt, tts |
| `--warmup-singles` / `--warmup-batches` / `--warmup-budget` | 5 / `8,64,256` / 600 s | stt, tts |
| `--bucket` | `medium` (short, medium, long or all) | stt |
| `--text`, `--length` | the medium sentence from `prompts/<lang>.json` | tts, runaway |
| `--gpu-index` | off | stt, tts |
| `--seed` | 1234 | stt, tts |
| `--percentile`, `--rtf-threshold`, `--runaways-fail` | p95, 1.0, off | report |
| `--protocol`, `--label`, `--save-normal` | http, none, 5 | runaway |

**Pointing at a model container directly** instead of the gateway. The STT container serves its health check at `/health`:

```bash
python stt_load.py --url http://HOST:8000 --health-path /health ...
```

The gateway adds one relay hop. That hop is usually negligible, but hitting the container directly takes it out of the numbers.

**Another language.** Add `prompts/<code>.json` with the same shape as `prompts/mr.json`: `corpus.short`, `corpus.medium`, `corpus.long_groups` and `tts_text.{short,medium,long}`. Then pass `--language <code>`. Keep each sentence to a single clause, with no full stop, danda or comma inside it. Orpheus is more likely to run away on multi-clause input, and that would contaminate a load test.

## Metrics and the pass rule

**RTF, the real-time factor, is the headline number.**

- **STT RTF** = time the server spent on the utterance ÷ audio duration. The server reports `latency_ms` on every partial transcript, covering batch-queue wait plus model step, and on the final transcript for the flush. RTF is their sum divided by the clip length. Below 1 the server keeps up with live speech. Above 1 a live caller falls further behind every second. If the server sends no `latency_ms`, RTF is reported as NOT MEASURED; the script never estimates it.
- **TTS RTF** = time to generate the whole response ÷ audio duration. Below 1 the audio arrives faster than it plays.

**Pass rule.** A level **passes** when there are **zero failed requests and p95 RTF < 1**, across the pooled rounds. The report shows p50, p95, p99 and max RTF for each level, PASS or FAIL, and "passes at every N up to …", which is the highest N before the first failure. The percentile and threshold can be changed at report time (`--percentile p99`, `--rtf-threshold 0.8`).

**Reported but not judged:**

| Metric | Meaning |
|---|---|
| STT *final* | Scheduled end of speech → final transcript |
| STT *1st partial* | Scheduled start of speech → first non-empty partial |
| STT *CER* | Character error rate against the clip's reference text, after punctuation and whitespace are normalised |
| TTS *TTFA* | Scheduled start → first audio byte |
| TTS *chunk gap* | Time between audio chunks; a large gap is an audible stall |
| TTS *audio s/s* | Seconds of audio produced per wall-clock second: throughput |
| *GPU mem / util* | nvidia-smi samples, only with `--gpu-index` on the GPU host |

**Timing method.** Every round's schedule is fixed before it starts, and latencies are measured from each request's **scheduled** time, not from when the client got round to sending it. Queueing anywhere, in the client, the network or the server, therefore shows up as latency instead of disappearing (the coordinated-omission problem). Percentiles use the nearest rank, with no interpolation.

## Output

Everything for one run is under `results/<RUN_ID>/`:

```
report.md                    the verdicts and tables
run.log                      console output
stt/  run_meta.json          settings, client host, git commit, server /health at start and end, notes
      warmup.json            what the warm-up did (discarded traffic)
      batch_sync.json        one summary per N, Test A (batch_random.json: Test B)
      requests_sync.jsonl    one line per request: N, round, clip, RTF, latencies, transcript, error
tts/  (same layout)          per request: RTF, TTFA, audio length, runaway flag, error
runaway/                     summary.json/.md, requests.jsonl, runaway_NNN.wav (if run)
```

The per-request files let later questions be answered without a rerun, such as a runaway rate, one slow clip, or one bad round.

## Reading the results, and caveats

- **"Passes up to N" is a property of the server's configuration, not just the model.** The caps in [Preparing the server](#preparing-the-server), the GPU, and whatever else shares the GPU all change it. Always report the verdict together with `run_meta.json` and your `--note`s.
- **Client-bound levels.** If the load generator itself falls behind (event-loop lag p95 > 50 ms), the level is marked *client-bound* and its numbers describe the client, not the server. Run the client on a machine with spare CPU, or a separate one, and rerun.
- **TTS runaways.** Orpheus sometimes does not stop by itself. The server's duration guard then cuts the response off at (characters ÷ 8) × 3 seconds of audio, which is 21 s for the 56-character default sentence. The scripts flag any response within 1% of that cap as a *runaway*. Runaways are counted and logged per request. They are included in RTF, because their RTF is normal, but they are not counted as failures unless `report.py --runaways-fail` is used. `runaway_check.py` measures the rate with no load (N = 1) and gives a 95% confidence interval. Use it to tell a model behaviour apart from a load effect.
- **CER depends on the corpus.** With synthesised clips, a clip where the TTS mis-spoke inflates CER even when the STT is right. Listen to outliers, which `requests_*.jsonl` lets you find, before drawing conclusions about accuracy.
- **Test B opens its sockets together.** For STT, each round opens its N sockets at the start and begins each utterance's speech at its random time. For TTS, each request is sent at its random time.
- **Repeatability.** Clip choice and arrival times come from `--seed`, so two runs with the same seed and settings send the same traffic.

## Diagnosing TTS runaways

`runaway_check.py` sends `--n` requests one at a time, with no load, and counts how many run to the duration guard. With `--protocol ws` it uses the Orpheus WebSocket (`/tts/v1/tts/ws` through the gateway). That route runs the same engine and guard as `/v1/audio/speech`, and its closing `done` frame reports, for every stream:

| Field | Values |
|---|---|
| `finish_reason` | `end_of_speech` (the model stopped itself), `text_eos` (stopped on the text end token), `max_tokens` (the guard cut it) |
| `soft_eos_ignored` | How many text end tokens the server dropped as padding because too little audio existed yet (`ORPHEUS_SOFT_TEXT_EOS`) |

`summary.md` cross-tabulates these for runaways against normal clips:

- **Runaways mostly had an ignored text end token, and normal clips mostly did not.** The soft text-eos rule is involved: the model tried to stop, the server treated the token as padding, and the model never produced end-of-speech.
- **Runaways had no ignored text end token.** The model never tried to stop, which is a sampling problem.

To test a hypothesis, change one server setting, restart the TTS container, wait until it is ready, and rerun with a label, so each run gets its own folder:

```bash
python runaway_check.py --url http://HOST:8100 --protocol ws --n 200 --out-dir results/rw \
    --label baseline --note "deployed settings"
# restart TTS with ORPHEUS_SOFT_TEXT_EOS=false, then:
python runaway_check.py --url http://HOST:8100 --protocol ws --n 200 --out-dir results/rw \
    --label soft-eos-off --note ORPHEUS_SOFT_TEXT_EOS=false
# likewise ORPHEUS_TEMPERATURE=0.4, ORPHEUS_REPETITION_PENALTY=1.1
```

When you turn `ORPHEUS_SOFT_TEXT_EOS` off, also listen for clips cut short: that setting exists to stop the text end token from truncating speech. Each folder also keeps `runaway_*.wav` and five `normal_*.wav` clips (`--save-normal`) to listen to side by side. With 200 requests per setting, the 95% confidence interval is about ±5 points around a 13% rate. Differences smaller than that need more requests.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `no JSON from …/health` warning | Wrong `--health-path`: `/stt/health` or `/tts/health` through the gateway, `/health` on the STT container. The test still runs, but idle checks and batching counters are off. |
| `voice … not in the roster` | List the voices with `curl 'http://HOST:8100/tts/v1/voices?language=mr'` and pick one. |
| Errors like `Too many open files` or connect failures at high N | Raise `ulimit -n` (at least 2 × max N + 64). Also check for a proxy or load balancer in front of the server that limits connections. |
| Every level FAILs with RTF near 1 even at small N | The server is probably capped or shared. Check the variables in [Preparing the server](#preparing-the-server) and `nvidia-smi`. |
| STT RTF shows NOT MEASURED | The server does not send `latency_ms`. The other STT metrics are still valid. |
| Nothing prints for a while | The warm-up batch of 256 can take minutes on a cold server. Progress lines are flushed as they happen, so silence means the server is busy, not that output is buffered. |
