"""Optional per-call hooks for LLM services (duck-typed from the runtime pipeline)."""

from __future__ import annotations


class ParticipantPhoneMixin:
    _participant_phone: str | None = None
    _use_participant_phone: bool = False

    def set_participant_phone(self, phone: str | None) -> None:
        if not self._use_participant_phone:
            return
        self._participant_phone = (phone or "").strip() or None
