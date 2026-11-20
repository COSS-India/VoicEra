"""The ``call_output`` shape Blue Dots receives: Raya's KKB Slim output.

The field list, values and rules come from ``KKB Slim Output.md`` in
Blue-Dots-Economy/AI-Agent-Prompts (copied next to this module as
``kkb_slim_output.md``; see ``SPEC_SOURCE``). Raya fills them by running that
prompt over the call. We do the same, then:

* ``normalise`` holds the LLM's answer to the spec: every field present, in
  the spec's order, enum values checked, counts as ints, job lists as lists
  of complete objects. Anything off-spec becomes the spec's empty value
  ("NA", [] or 0).
* ``apply_facts`` overrides the fields the system knows for certain (from the
  AI DPG tool calls and the call's inputs) and enforces the spec's
  cross-field rules, so the LLM cannot contradict a tool result.

AI DPG's tools differ from Raya's; ``TOOL_ALIASES`` maps them for the prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA = "bluedots.kkb_slim.v1"
SPEC_FILE = Path(__file__).with_name("kkb_slim_output.md")
SPEC_SOURCE = {
    "repo": "Blue-Dots-Economy/AI-Agent-Prompts",
    "path": "Blue Dots/KKB-Slim/KKB Slim Output.md",
    "commit": "5056dd0",
}

NA = "NA"

# Raya tool name -> AI DPG tool name.
TOOL_ALIASES = {
    "get_recommended_jobs": None,  # no equivalent in AI DPG
    "get_jobs": "fetch_jobs",
    "create_profile": "save_profile",
    "get_services": "fetch_services",
    "apply_job": "apply_job",
}

JOB_KEYS = (
    "job_id",
    "role",
    "company_name",
    "company_location",
    "salary_offered",
    "qualification_required",
)
FAILED_JOB_KEYS = JOB_KEYS + ("failure_reason",)

YES_NO = ("Yes", "No")

# Field -> allowed values (None: free text). Order is the spec's example order.
FIELDS: dict[str, tuple[str, ...] | str | None] = {
    "seeker_name": None,
    "call_answered": YES_NO,
    "call_engaged": YES_NO,
    "primary_topic": ("Job search", "Profile update", "No engagement"),
    "user_intent": ("Job Application", "Job Search", "Profile Update", "General", NA),
    "jobs_shown": YES_NO,
    "jobs_recommended": "jobs",
    "applied_to_job": YES_NO,
    "applications_count": "count",
    "jobs_applied": "jobs",
    "jobs_failed_to_apply": "failed_jobs",
    "ready_for_interview": ("Yes", "No", "Conditional", NA),
    "consent_status": ("Given", "Declined", NA),
    "preferred_location": None,
    "preference_mismatch_reason": ("Location", "Role", NA),
    "input_location_had_jobs": ("Yes", "No", NA),
    "nearest_landmark": None,
    "pin_code": "pin",
    "home_area": None,
    "services_pitched": YES_NO,
    "service_interest": ("Yes", "Maybe", "No", NA),
    "service_callback_slot": "callback_slot",
    "service_offered": None,
    "service_need_matched": (
        "Training", "Counselling", "Placement", "Financial", "Travel", "Other", NA,
    ),
    "jobs_interest": ("Yes", "No", "Unclear"),
    "jobs_fetched": ("Recommended", "Search", "Both", "No"),
    "jobs_offered_count": "count",
    "job_roles_offered": None,
    "job_no_match": ("Yes", "No", NA),
    "asked_job_location": YES_NO,
    "drop_reason": None,
    "call_later_request": "call_later",
    "final_summary": None,
}

CALLBACK_SLOTS = ("Morning", "Afternoon", "Evening", "Anytime")
_PIN = re.compile(r"^\d{6}$")
# Input locations that are not a place (spec 15c).
_LOCATION_SENTINELS = {"", "na", "any", "-", "none", "null"}


def empty_value(name: str) -> Any:
    kind = FIELDS[name]
    if kind in ("jobs", "failed_jobs"):
        return []
    if kind == "count":
        return 0
    return NA


def _text(value: Any) -> str:
    if value is None:
        return NA
    text = str(value).strip()
    return text or NA


def _enum(value: Any, allowed: tuple[str, ...]) -> str:
    text = _text(value)
    for option in allowed:
        if text.lower() == option.lower():
            return option
    return NA


def _count(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(number, 0)


def _jobs(value: Any, keys: tuple[str, ...]) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    jobs = []
    for item in value:
        if not isinstance(item, dict):
            continue  # the spec forbids flattened strings
        jobs.append({key: _text(item.get(key)) for key in keys})
    return jobs


def _callback_slot(value: Any) -> str:
    text = _text(value)
    for option in CALLBACK_SLOTS:
        if text.lower() == option.lower():
            return option
    if text.lower().startswith("other:") and text[6:].strip():
        return "Other: " + text[6:].strip()
    return NA


def _call_later(value: Any) -> str:
    text = _text(value)
    if text.lower().startswith("yes:") and text[4:].strip():
        return "Yes: " + text[4:].strip()
    return NA


def _pin(value: Any) -> str:
    text = _text(value)
    return text if _PIN.match(text) else NA  # never repaired (spec 15e)


def normalise(raw: Any) -> dict[str, Any]:
    """Every spec field, in order, with off-spec values replaced by the empty value."""
    data = raw if isinstance(raw, dict) else {}
    output: dict[str, Any] = {}
    for name, kind in FIELDS.items():
        value = data.get(name)
        if kind is None:
            output[name] = _text(value)
        elif kind == "count":
            output[name] = _count(value)
        elif kind == "jobs":
            output[name] = _jobs(value, JOB_KEYS)
        elif kind == "failed_jobs":
            output[name] = _jobs(value, FAILED_JOB_KEYS)
        elif kind == "pin":
            output[name] = _pin(value)
        elif kind == "callback_slot":
            output[name] = _callback_slot(value)
        elif kind == "call_later":
            output[name] = _call_later(value)
        else:
            output[name] = _enum(value, kind)  # type: ignore[arg-type]
    return output


@dataclass
class CallFacts:
    """What the system knows for certain about a call."""

    seeker_name: str = "Unknown"
    input_location: str = ""
    caller_turns: int = 0
    phases: list[str] = field(default_factory=list)
    # Tool outcomes by AI DPG tool name.
    calls: dict[str, int] = field(default_factory=dict)
    successes: dict[str, int] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)
    # Whether the job list the bot was given is available (it is not until
    # AI DPG logs tool results).
    job_list_known: bool = False

    def called(self, tool: str) -> bool:
        return self.calls.get(tool, 0) > 0

    def ok(self, tool: str) -> int:
        return self.successes.get(tool, 0)

    def failed(self, tool: str) -> int:
        return self.failures.get(tool, 0)


def input_location_is_place(location: str) -> bool:
    text = (location or "").strip()
    return text.lower() not in _LOCATION_SENTINELS and not text.isdigit()


def apply_facts(output: dict[str, Any], facts: CallFacts) -> tuple[dict[str, Any], dict[str, str]]:
    """Override what the system knows and enforce the spec's rules.

    Returns ``(output, sources)``; ``sources`` lists each overridden field and why.
    """
    out = dict(output)
    sources: dict[str, str] = {}

    def force(name: str, value: Any, why: str) -> None:
        if out.get(name) != value:
            sources[name] = why
        out[name] = value

    force("seeker_name", facts.seeker_name or "Unknown", "contact list (input)")
    force("call_answered", "Yes" if facts.caller_turns else "No", "caller turns in transcript")
    if facts.caller_turns < 3:
        force("call_engaged", "No", "fewer than three caller turns")

    # Applications: apply_job tool outcomes are the truth (spec 8-11).
    applied = facts.ok("apply_job")
    force("applied_to_job", "Yes" if applied else "No", "apply_job tool calls")
    force("applications_count", applied, "apply_job tool calls")
    if not applied:
        force("jobs_applied", [], "no successful apply_job")
    elif len(out["jobs_applied"]) > applied:
        force("jobs_applied", out["jobs_applied"][:applied], "trimmed to successful apply_job calls")
    if not facts.failed("apply_job"):
        force("jobs_failed_to_apply", [], "no failed apply_job")
    if not facts.called("apply_job"):
        force("ready_for_interview", NA, "no application attempted")

    # Jobs (spec 6, 7, 21-23).
    force("jobs_fetched", "Search" if facts.called("fetch_jobs") else "No", "fetch_jobs tool calls")
    if not facts.ok("fetch_jobs"):
        force("jobs_shown", "No", "no successful fetch_jobs")
        force("jobs_recommended", [], "no successful fetch_jobs")
        force("jobs_offered_count", 0, "no successful fetch_jobs")
        force("job_roles_offered", NA, "no successful fetch_jobs")
    if not facts.job_list_known or not input_location_is_place(facts.input_location):
        force("input_location_had_jobs", NA, "job list not available" if input_location_is_place(
            facts.input_location) else "input location is not a place")

    # Consent (spec 15): save_profile is AI DPG's create_profile.
    if facts.called("save_profile"):
        force("consent_status", "Given", "save_profile called")
    elif "consent_declined" in facts.phases:
        force("consent_status", "Declined", "phase consent_declined")
    else:
        force("consent_status", NA, "consent gate not passed on this call")

    # Services (spec 16-19): never a name the tool did not return.
    if not facts.ok("fetch_services"):
        force("service_offered", NA, "no successful fetch_services")
    if out["services_pitched"] != "Yes":
        for name in ("service_interest", "service_callback_slot", "service_offered", "service_need_matched"):
            force(name, NA, "no service offer")

    # Spec: preference_mismatch_reason is NA whenever the caller applied.
    if applied:
        force("preference_mismatch_reason", NA, "caller applied")
    return out, sources


def unanswered_output(seeker_name: str = "Unknown") -> dict[str, Any]:
    """The output for a call nobody spoke on (spec 2: call_answered "No")."""
    out = normalise({})
    out.update(
        seeker_name=seeker_name or "Unknown",
        call_answered="No",
        call_engaged="No",
        primary_topic="No engagement",
        user_intent=NA,
        jobs_shown="No",
        applied_to_job="No",
        services_pitched="No",
        jobs_interest="Unclear",
        jobs_fetched="No",
        asked_job_location="No",
    )
    return out


def seeker_name_from(call: dict[str, Any]) -> str:
    variables = call.get("custom_variables") or {}
    for key in ("contact_name", "seeker_name", "name"):
        value = str(variables.get(key) or "").strip()
        if value:
            return value
    return "Unknown"


def input_location_from(call: dict[str, Any]) -> str:
    variables = call.get("custom_variables") or {}
    return str(variables.get("location") or "").strip()
