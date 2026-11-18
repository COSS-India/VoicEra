---
title: Post-call call_output
description: Fields worked out after each answered call, carried on the call record and the webhook.
---

`apps/api/app/services/call_output/`. An agent opts in with `config.call_output`; VoicEra then works out `call_output` for each of its answered calls, stores it on the call log and sends it in the [post-call webhook](webhooks). What the fields are and where they come from depends on the provider.

## Turn it on

```json
{ "config": { "call_output": { "enabled": true, "provider": "bluedots" } } }
```

`provider` is required when `enabled` is true. A `PATCH` whose `config` leaves out `call_output` keeps the current setting.

## Lifecycle

`call_output_status` on the call log:

| Status | Meaning |
| --- | --- |
| `pending` | Due shortly after the call ends (`CALL_OUTPUT_DELAY_SECONDS`, default 45) |
| `computing` | A worker has it |
| `ready` | `call_output` is set |
| `skipped` | The call was not answered (`busy`, `no_answer`, `failed`, `cancelled`); `call_output` is `{}` |
| `failed` | Gave up after `CALL_OUTPUT_MAX_ATTEMPTS`; `call_output_error` says why |

Answered or not is decided when the output is computed: the telephony hangup can mark a call `completed` before the runtime marks it `answered`. A call still not `answered` after the attempts run out is `skipped`.

The `arq-worker` runs `dispatch_call_outputs` every 10 seconds. The post-call webhook waits for a `pending` output so the event carries it, for up to `CALL_OUTPUT_WEBHOOK_MAX_WAIT_SECONDS` (default 600); after that it is sent with whatever status the output has.

`GET /calls/{call_id}` returns `call_output`, `call_output_status`, `call_output_error` and `call_output_at`.

### `POST /calls/{call_id}/call-output/recompute`

Bearer. `202` with `{call_id, call_output_status}`. Works it out again now (attempts reset). `409` when the call has not ended or its agent has no provider.

## Provider: `bluedots`

Blue Dots' conversation runs in AI DPG's Agent Core, which produces no `call_output`. The provider reads the call's lines from AI DPG's Loki, keyed by `session_id = <caller_phone>:<call_id>`, and only the structured lines:

* `orchestrator.stream_turn_complete` (agent_core): the phase each turn moved to (`next_subagent_id`).
* `RestApiAdapter.execute` (action_gateway): each tool call's `tool_name` and `status`.

It maps them, plus the VoicEra transcript, onto the funnel:

| Field | Rule |
| --- | --- |
| `answered` | Always true (unanswered calls are skipped) |
| `consent` | `true` when a consent-gated write succeeded (`save_profile` or `apply_job`); `false` when the call reached `consent_declined`; otherwise `null` |
| `jobs_heard` | `true` when the call reached `job_details` or `apply_confirm`, or applied; `false` when no `fetch_jobs` succeeded; otherwise read from the transcript (`null` without a model) |
| `applied` | An `apply_job` call succeeded |
| `applications` | Number of successful `apply_job` calls |
| `last_phase` | The last phase recorded |
| `drop_reason` | For calls that did not apply, read from the transcript: one of `hung_up_or_disengaged`, `not_interested`, `already_employed`, `no_suitable_jobs`, `declined_consent`, `call_back_later`, `language_barrier`, `technical_issue`, `other` (`null` without a model) |

<Warning>
The field names and values are provisional (`call_output.schema` = `bluedots.call_output.provisional.v1`) until they are checked against Raya's output spec, so Blue Dots' receiver works unchanged. They all live in `bluedots/funnel.py`.
</Warning>

If no log lines are found yet, the provider retries until `CALL_OUTPUT_LOG_GRACE_SECONDS` (default 180) after the call ended; after that a call with no lines is treated as having no turns. The raw signals behind each output (phases, tool outcomes, where each field came from) are stored on the call log as `call_output_signals` for audits.

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `BLUEDOTS_LOKI_URL` | — | AI DPG Loki, reachable from the worker (e.g. on the AI DPG Docker network) |
| `BLUEDOTS_LOKI_SELECTOR` | `{job=~"agent_core\|action_gateway"}` | LogQL stream selector |
| `BLUEDOTS_LOKI_TIMEOUT_SECONDS` | `10` | Per query |
| `CALL_OUTPUT_LLM_BASE_URL` | — | Any OpenAI-compatible endpoint, e.g. `https://api.openai.com/v1` |
| `CALL_OUTPUT_LLM_MODEL` | — | e.g. `gpt-4.1-mini` |
| `CALL_OUTPUT_LLM_API_KEY` | — | Key for that endpoint |
| `CALL_OUTPUT_LLM_JSON_MODE` | `true` | Send `response_format: json_object`; turn off for servers that reject it |
| `CALL_OUTPUT_DELAY_SECONDS` | `45` | Wait after the call before the first attempt |
| `CALL_OUTPUT_RETRY_SECONDS` | `30` | Between attempts |
| `CALL_OUTPUT_MAX_ATTEMPTS` | `6` | Before `failed` |
| `CALL_OUTPUT_LOG_GRACE_SECONDS` | `180` | How long missing logs mean "not there yet" |
| `CALL_OUTPUT_WEBHOOK_MAX_WAIT_SECONDS` | `600` | Longest the webhook waits |

Without the `CALL_OUTPUT_LLM_*` settings the step still runs; only `jobs_heard` (when ambiguous) and `drop_reason` are left `null`.
