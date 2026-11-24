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
| `skipped` | The call was not answered (`busy`, `no_answer`, `failed`, `cancelled`); `call_output` is the provider's unanswered output (`{}` if it has none) |
| `failed` | Gave up after `CALL_OUTPUT_MAX_ATTEMPTS`; `call_output_error` says why |

Answered or not is decided when the output is computed: the telephony hangup can mark a call `completed` before the runtime marks it `answered`. A call still not `answered` after the attempts run out is `skipped`.

The `arq-worker` runs `dispatch_call_outputs` every 10 seconds. The post-call webhook waits for a `pending` output so the event carries it, for up to `CALL_OUTPUT_WEBHOOK_MAX_WAIT_SECONDS` (default 600); after that it is sent with whatever status the output has.

`GET /calls/{call_id}` returns `call_output`, `call_output_status`, `call_output_error` and `call_output_at`.

### `POST /calls/{call_id}/call-output/recompute`

Bearer. `202` with `{call_id, call_output_status}`. Works it out again now (attempts reset). `409` when the call has not ended or its agent has no provider.

## Provider: `bluedots`

`call_output` is Raya's **KKB Slim output**: the fields, values and rules in Blue Dots' `KKB Slim Output.md` ([AI-Agent-Prompts](https://github.com/Blue-Dots-Economy/AI-Agent-Prompts), `Blue Dots/KKB-Slim/`, commit `5056dd0`), so Blue Dots' receiver works unchanged. The spec is copied verbatim to `bluedots/kkb_slim_output.md`; to take a new version, replace that file and update `SPEC_SOURCE` in `bluedots/schema.py`.

Blue Dots' conversation runs in AI DPG's Agent Core, which produces no `call_output`. For each answered call the provider:

1. Reads the call's structured lines from AI DPG's Loki, keyed by `session_id = <caller_phone>:<call_id>`: `orchestrator.stream_turn_complete` (the phase each turn moved to) and `RestApiAdapter.execute` (each tool call's `tool_name`, `status` and `error`).
2. Runs the spec as the prompt over the VoicEra transcript, the call's input variables (`contact_name`, `location` from `custom_variables`) and those tool calls and phases, as Raya does. The prompt tells the model AI DPG's tool names. Each tool call goes as its name and outcome; an `apply_job` call also gives the applied job's `job_id` when AI DPG logged it (see below). No other arguments go to the model, so the caller's phone number, name and age from tool calls stay out of the request. Tool results are not given to the model either: AI DPG cuts them at 2,000 characters, so a job list usually lacks the jobs actually read out, and the model then listed jobs nobody offered. Job details come from what was said.
3. Holds the answer to the spec: every field present in the spec's order, enum values checked, counts as integers, job lists as complete objects. Anything off-spec becomes the spec's empty value (`"NA"`, `[]` or `0`). A PIN that is not exactly six digits is `"NA"`, never repaired.
4. Overrides what the system knows for certain, so the model cannot contradict a tool result:

| Field | Rule |
| --- | --- |
| `seeker_name` | `contact_name` from the contact list, else `"Unknown"` |
| `call_answered` | `"Yes"` when the caller said anything in the transcript |
| `call_engaged` | `"No"` with fewer than three caller turns |
| `applied_to_job`, `applications_count` | Successful `apply_job` calls; `jobs_applied` is cut to that many, `[]` when none |
| `jobs_failed_to_apply` | `[]` when no `apply_job` failed |
| `ready_for_interview` | `"NA"` when no application was attempted |
| `jobs_fetched` | `"Search"` when `fetch_jobs` ran, else `"No"` (AI DPG has no recommended-jobs tool) |
| `jobs_shown`, `jobs_recommended`, `jobs_offered_count`, `job_roles_offered` | Empty when no `fetch_jobs` succeeded |
| `consent_status` | `"Given"` when `save_profile` (Raya's `create_profile`) was called; `"Declined"` when the call reached `consent_declined`; else `"NA"` |
| `input_location_had_jobs` | `"NA"`: the job list is not in AI DPG's logs (see below) |
| `service_offered` | `"NA"` when no `fetch_services` succeeded (never a name the tool did not return) |
| `service_*` | `"NA"` when `services_pitched` is not `"Yes"` |
| `preference_mismatch_reason` | `"NA"` when the caller applied |

A call where the caller never spoke gets the unanswered output without a model call (`call_answered` `"No"`, `primary_topic` `"No engagement"`, everything else empty). Unanswered calls (`skipped`) get the same output.

<Warning>
Job objects are filled from what was said on the call, so `job_id` is `"NA"` except for an applied job, whose `job_id` comes from the `apply_job` arguments (logged only while AI DPG logs at DEBUG). Any `job_id` the model returns that is not an `apply_job` call's `job_id` is reset to `"NA"`. `input_location_had_jobs` stays `"NA"`.
</Warning>

If no log lines are found yet, the provider retries until `CALL_OUTPUT_LOG_GRACE_SECONDS` (default 180) after the call ended; after that a call with no lines is treated as having no tool calls. A model error or an answer that is not JSON is retried. Without the `CALL_OUTPUT_LLM_*` settings an answered call ends `failed`; set them and use recompute. What was overridden and why, plus the phases and tool calls behind each output, is stored on the call log as `call_output_signals`. Each tool call is counted once, from its final log line. When AI DPG logs at DEBUG, each one also keeps its `arguments` and `result` (AI DPG's response body, cut at 2,000 characters). The model gets only `apply_job`'s `job_id` from them, and the [Raya-format webhook](webhooks#raya-compatible-body) puts both in its transcript. Recompute on a call that was not answered writes the not-answered output, as scheduling does.

### Deployment

The `api` and `arq-worker` containers join AI DPG's external `dpg_net` Docker network (as the `runtime` does to reach the bridge), so `BLUEDOTS_LOKI_URL=http://loki:3100`. The agent's LLM URL is the AI DPG bridge: `http://reach_layer_bridge:8008/v1`.

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `BLUEDOTS_LOKI_URL` | — | AI DPG Loki, reachable from the worker (e.g. on the AI DPG Docker network) |
| `BLUEDOTS_LOKI_SELECTOR` | `{job=~"agent_core\|action_gateway"}` | LogQL stream selector |
| `BLUEDOTS_LOKI_TIMEOUT_SECONDS` | `10` | Per query |
| `CALL_OUTPUT_LLM_BASE_URL` | — | Any OpenAI-compatible endpoint, e.g. `https://api.openai.com/v1` |
| `CALL_OUTPUT_LLM_MODEL` | — | e.g. `gpt-4.1-mini` |
| `CALL_OUTPUT_LLM_API_KEY` | — | Key for that endpoint |
| `CALL_OUTPUT_LLM_TIMEOUT_SECONDS` | `90` | Per request (the prompt is long) |
| `CALL_OUTPUT_LLM_JSON_MODE` | `true` | Send `response_format: json_object`; turn off for servers that reject it |
| `CALL_OUTPUT_DELAY_SECONDS` | `45` | Wait after the call before the first attempt |
| `CALL_OUTPUT_RETRY_SECONDS` | `30` | Between attempts |
| `CALL_OUTPUT_MAX_ATTEMPTS` | `6` | Before `failed` |
| `CALL_OUTPUT_LOG_GRACE_SECONDS` | `180` | How long missing logs mean "not there yet" |
| `CALL_OUTPUT_WEBHOOK_MAX_WAIT_SECONDS` | `600` | Longest the webhook waits |

