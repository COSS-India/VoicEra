"""Map Blue Dots call signals onto ``call_output`` funnel fields.

PROVISIONAL. The field names and values below follow the funnel Blue Dots
described (answered > consent > jobs heard > applied > drop reason). They
must be checked against Raya's output spec (``KKB Slim Output.md``) so Blue
Dots' receiver works unchanged; until then ``call_output.schema`` is
``bluedots.call_output.provisional.v1``. Everything that would change is in
this module.

Rules, from the AI DPG phases (see the Blue Dots prompt guide) and tools:

* answered    only answered calls get here (unanswered calls are skipped).
* consent     True when a write succeeded (``save_profile`` or ``apply_job``;
              AI DPG gates every write on consent recorded in the session);
              False when the call reached ``consent_declined``; otherwise
              None (not asked on this call, e.g. a returning caller who did
              not apply).
* jobs_heard  True when the call reached ``job_details`` or ``apply_confirm``,
              or an application went through; False when no ``fetch_jobs``
              succeeded; otherwise the transcript decides (a successful
              search can still end in "no jobs here"), or None without an LLM.
* applied     an ``apply_job`` call succeeded.
* drop_reason for calls that did not apply: chosen by the LLM from
              ``DROP_REASONS``, or None without an LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.call_output.bluedots.signals import CallSignals

SCHEMA = "bluedots.call_output.provisional.v1"

DROP_REASONS = (
    "hung_up_or_disengaged",
    "not_interested",
    "already_employed",
    "no_suitable_jobs",
    "declined_consent",
    "call_back_later",
    "language_barrier",
    "technical_issue",
    "other",
)

JOBS_SHOWN_PHASES = ("job_details", "apply_confirm")
CONSENT_DECLINED_PHASES = ("consent_declined",)


@dataclass
class Judgement:
    """What the LLM read from the transcript (any field may be None)."""

    jobs_read_out: bool | None = None
    drop_reason: str | None = None
    model: str | None = None


def needs_jobs_judgement(signals: CallSignals) -> bool:
    applied = signals.succeeded("apply_job") > 0
    return (
        not applied
        and not signals.reached(*JOBS_SHOWN_PHASES)
        and signals.succeeded("fetch_jobs") > 0
    )


def needs_drop_judgement(signals: CallSignals) -> bool:
    return signals.succeeded("apply_job") == 0


def build(signals: CallSignals, judgement: Judgement | None = None) -> tuple[dict[str, Any], dict[str, str]]:
    """Return ``(call_output, sources)``; ``sources`` says where each field came from."""
    sources: dict[str, str] = {}
    applications = signals.succeeded("apply_job")
    applied = applications > 0
    sources["applied"] = "apply_job succeeded" if applied else "no successful apply_job"

    if applied or signals.succeeded("save_profile"):
        consent: bool | None = True
        sources["consent"] = "a consent-gated write succeeded"
    elif signals.reached(*CONSENT_DECLINED_PHASES):
        consent = False
        sources["consent"] = "phase consent_declined"
    else:
        consent = None
        sources["consent"] = "not observed on this call"

    if applied or signals.reached(*JOBS_SHOWN_PHASES):
        jobs_heard: bool | None = True
        sources["jobs_heard"] = "phase job_details/apply_confirm or applied"
    elif signals.succeeded("fetch_jobs") == 0:
        jobs_heard = False
        sources["jobs_heard"] = "no successful fetch_jobs"
    elif judgement is not None and judgement.jobs_read_out is not None:
        jobs_heard = judgement.jobs_read_out
        sources["jobs_heard"] = "transcript (llm)"
    else:
        jobs_heard = None
        sources["jobs_heard"] = "jobs fetched; transcript not judged"

    if applied:
        drop_reason = None
        sources["drop_reason"] = "applied"
    elif judgement is not None and judgement.drop_reason:
        drop_reason = judgement.drop_reason
        sources["drop_reason"] = "transcript (llm)"
    else:
        drop_reason = None
        sources["drop_reason"] = "transcript not judged"

    output = {
        "schema": SCHEMA,
        "answered": True,
        "consent": consent,
        "jobs_heard": jobs_heard,
        "applied": applied,
        "applications": applications,
        "last_phase": signals.last_phase,
        "drop_reason": drop_reason,
    }
    return output, sources
