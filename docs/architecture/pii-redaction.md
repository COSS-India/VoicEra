# PII redaction: architecture

How the runtime keeps personal details (phone, Aadhaar, card, PAN, email, date of birth, OTP, long numbers) out of what it shows, logs and stores. For the settings and what is detected, see [Redacting PII in transcripts](../guides/operator/operations.md#redacting-pii-in-transcripts) and [Call recordings](../guides/operator/operations.md#call-recordings).

Everything here applies only with `PII_REDACTION_ENABLED=true`. With it off, nothing is redacted and recording works as before.

## Where redaction happens

The speech recognition, LLM and TTS providers work on the real text: the agent has to understand the caller. Redaction applies at every point where text or audio leaves the call: the test panel, the logs, the stored transcript and the stored recording.

```mermaid
flowchart LR
  caller(["Caller audio"]) --> stt["STT provider"]
  stt --> pipeline["Pipecat pipeline<br/>LLM context and TTS<br/>(unredacted, in memory only)"]

  pipeline --> rtvi["RedactingRTVIProcessor<br/>services/privacy/rtvi.py<br/>mode: live"]
  rtvi --> panel(["Browser test panel"])

  pipeline --> logs["log_patcher on every log line<br/>services/privacy/redaction.py<br/>mode: log"]
  logs --> logout(["Runtime logs"])

  pipeline --> tw["TranscriptWriter<br/>holds lines until the call ends"]
  tw --> redact["redact_turns_with_spans<br/>whole call as context<br/>mode: stored"]
  redact --> transcript[("MinIO<br/>transcript.txt")]

  pipeline --> rec["TimedAudioBufferProcessor<br/>caller and agent tracks<br/>held in memory"]
  redact -- "turn timings and<br/>redacted spans" --> mute["CallRecording.flush<br/>mute with tone, then mix"]
  rec --> mute
  mute --> recording[("MinIO<br/>recording")]

  carrier["Carrier recording<br/>Vi, Plivo"] -. "blocked: not started,<br/>webhook not stored" .-> carrierstore[("Carrier recording<br/>on CallLog")]

  classDef store fill:#eef,stroke:#557
  classDef redactor fill:#efe,stroke:#575
  class transcript,recording,carrierstore store
  class rtvi,logs,redact,mute redactor
```

| Path | Code | Mode | When |
| --- | --- | --- | --- |
| Test panel | `services/privacy/rtvi.py` (`RedactingRTVIProcessor`, added in `services/pipecat/factory.py`) | `live` | Each `user-transcription` and `bot-output` message. The streamed `bot-llm-text`, `bot-tts-text` and `bot-transcription` messages are dropped. |
| Runtime logs | `log_patcher` in `services/privacy/redaction.py`, installed in `apps/runtime/app.py` | `log` | Every log line, including Pipecat's and the STT adapters', and exception tracebacks (written without local variables). |
| Stored transcript | `services/storage/transcript.py` (`TranscriptWriter.render`) | `stored` | Once, at call end, over all turns together. |
| System recording | `services/storage/recording.py`, `services/privacy/audio.py` | uses the transcript's spans | At call end, after the transcript. |
| Carrier recording | `routes/telephony.py`, `routes/provider_recording.py`, `routes/plivo_telephony.py` | none | Not started, and webhooks are acknowledged with `200` and not stored, while redaction is on. |

## How one piece of text is redacted

`redact_text` (one line) and `redact_turns_with_spans` (a whole call) share the same steps. The text is rewritten into a normalised copy for matching; every match maps back to the original text, so only the original span is replaced.

```mermaid
flowchart TD
  input["Text from one turn"] --> digits["Indic digits to 0-9<br/>(eleven scripts, one character each,<br/>so offsets do not move)"]
  digits --> words["Number words to digits<br/>services/privacy/number_words.py<br/>English, Hindi, Kannada in full;<br/>digits 0-9 in eight more languages"]
  words --> qty{"Price, quantity<br/>or year?"}
  qty -- "yes: two thousand four hundred rupees,<br/>दो हज़ार चार सौ रुपये, twenty twenty five" --> keep["Left as words"]
  qty -- no --> norm["Normalised text<br/>nine eight seven six becomes 9 8 7 6"]
  keep --> norm
  norm --> patterns["Patterns in precedence order<br/>EMAIL, CARD (Luhn), PAN, PHONE,<br/>AADHAAR (Verhoeff), DOB, OTP, NUMBER"]
  patterns --> hints["Hints: OTP, email, phone words in this turn<br/>(stored: also the other speaker's previous turn)"]
  hints --> mode{"Mode"}
  mode -- "live, log" --> strict["Also: 4+ digits read out<br/>one at a time"]
  mode -- "log" --> ids["Keep IDs traceable:<br/>12+ char letter-and-digit tokens"]
  mode -- "stored" --> callrules["Whole-call rules<br/>(next diagram)"]
  strict --> out
  ids --> out
  callrules --> out["Each span replaced with<br/>[REDACTED_TEXT]"]
```

The placeholder is the same for every type, so a reader cannot tell what kind of detail was removed.

## Whole-call rules (stored transcript only)

Run by `_analyse_turns` in `services/privacy/redaction.py` after every turn has been through the steps above.

```mermaid
flowchart TD
  turns["All turns of the call,<br/>each with its spans and digit runs"] --> join["Join split numbers<br/>same speaker, at most one other turn between,<br/>joined digits must be a whole phone,<br/>Aadhaar or card number"]
  join --> known["Collect known identifiers<br/>every PHONE, AADHAAR, CARD<br/>and NUMBER of 9+ digits"]
  known --> frag["Redact parts of known identifiers<br/>5+ digits read out, or 7+ typed,<br/>anywhere in the call"]
  frag --> spans["Spans per turn"]
  spans --> text["Redacted transcript text"]
  spans --> timing["Turn timings with redacted spans<br/>(used to mute the recording)"]
```

A phone hint (`number`, `mobile`, `नंबर`, `ಮೊಬೈಲ್`, ...) in a turn or in the same speaker's previous turn lets digits typed in an unusual grouping count as a phone, and lets a grouped part (`76 54 32 10`) join with the rest of the number.

## Call end

The order matters: the recording is muted from what the transcript redaction found, so the transcript goes first. From `run_with_lifecycle` in `services/pipecat/lifecycle.py`:

```mermaid
sequenceDiagram
  participant L as lifecycle.py
  participant T as TranscriptWriter
  participant R as redaction.py
  participant API as API
  participant C as CallRecording
  participant M as MinIO

  L->>T: flush()
  T->>R: redact_turns_with_spans(all turns)
  R-->>T: redacted text + spans per turn
  T->>T: turn_timings = when each turn happened<br/>and what was redacted
  T->>M: transcript.txt (redacted)
  L->>API: finalize_call (status, end time)
  L->>C: flush(turn_timings)
  C->>C: plan_mutes: caller utterances and agent<br/>sentences with something redacted
  C->>C: mute with 1 kHz tone on that track, mix to mono
  C->>M: recording (muted)
  Note over C,M: If muting fails, nothing is uploaded.<br/>The unmuted audio is never written anywhere.
```

Failure handling:

- **Transcript redaction fails.** Each line falls back to the stricter `live` redaction, and every turn is marked for muting, so the recording is muted throughout.
- **Muting fails.** The recording is not stored at all.
- **A log line fails to redact.** It is written as `[REDACTION_FAILED]`, without its traceback.

## Muting the recording

`TimedAudioBufferProcessor` (`services/storage/recording.py`) records the caller and agent on separate tracks, on one clock that starts with the first audio frame. For each `TTSTextFrame` it notes when that agent sentence was spoken.

```mermaid
flowchart LR
  timings["Turn timings<br/>from the transcript"] --> plan["plan_mutes<br/>services/privacy/audio.py"]
  segments["Agent sentence times<br/>from TTSTextFrame"] --> plan
  plan --> uw["Caller windows<br/>whole utterance with anything redacted,<br/>0.5 s before, 0.3 s after"]
  plan --> aw["Agent windows<br/>sentence matched to the turn text,<br/>0.2 s either side"]
  uw --> mute["mute: 1 kHz tone<br/>on that track only"]
  aw --> mute
  mute --> mix["mix_audio to mono"] --> upload[("MinIO")]
```

The recording keeps its full length, so transcript timestamps still line up with it.

## Settings

| `CALL_RECORDING_ENABLED` | `PII_REDACTION_ENABLED` | Test panel, logs, transcript | System recording | Carrier recording |
| --- | --- | --- | --- | --- |
| `true` (default) | `false` (default) | Not redacted | Stored as recorded | Stored |
| `true` | `true` | Redacted | Stored with PII muted | Not started or stored |
| `false` | any | As per `PII_REDACTION_ENABLED` | Not recorded | Not started or stored |

## Limits

- What is not detected (names, postal addresses, Hindi numbers typed in English letters) is not redacted or muted.
- If the speech recognition mishears a number, the transcript holds the wrong words, and neither redaction nor muting can catch it.
- The STT, LLM and TTS providers receive the real text and audio. Their own logging and retention are governed by each provider.

## Code map

| File | Role |
| --- | --- |
| `apps/runtime/services/privacy/redaction.py` | Patterns, modes, whole-call rules, log patcher |
| `apps/runtime/services/privacy/number_words.py` | Number words and Indic digits to digits; prices and quantities left alone |
| `apps/runtime/services/privacy/rtvi.py` | Test panel redaction |
| `apps/runtime/services/privacy/audio.py` | Recording switches, turn timings, mute planning, tone |
| `apps/runtime/services/storage/transcript.py` | Transcript buffering, redaction at call end, turn timings |
| `apps/runtime/services/storage/recording.py` | Timed recorder, muted upload |
| `apps/runtime/services/pipecat/lifecycle.py` | Call-end order |
| `apps/runtime/tests/test_pii_redaction.py`, `test_recording_redaction.py` | Tests |
