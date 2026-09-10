"""Buffer Pipecat pipeline metrics and PUT them to the CallMetrics collection at call end."""

from __future__ import annotations

from typing import Any, Literal

from loguru import logger

from apps.runtime.services.backend import backend_client

ProcessorStage = Literal["stt", "llm", "tts"]


def _model_to_dict(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {k: _model_to_dict(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_model_to_dict(v) for v in value]
    return value


class CallMetricsWriter:
    """Accumulate pipeline metrics in memory and persist once when the call ends."""

    def __init__(
        self,
        *,
        org_id: str,
        call_id: str,
        session_label: str,
        processor_stages: dict[str, ProcessorStage] | None = None,
    ) -> None:
        self._org_id = org_id
        self._call_id = call_id
        self._session_label = session_label
        # Pipeline role map: FrameProcessor.name → stage. Prefer this over
        # guessing from class-name substrings (OrpheusTTS contains "STT").
        self._processor_stages = dict(processor_stages or {})
        self._flushed = False
        self._transport: dict[str, Any] | None = None
        self._turns: list[dict[str, Any]] = []
        self._latencies: dict[str, Any] = {
            "first_bot_speech_secs": None,
            "user_to_bot_secs": [],
            "breakdowns": [],
        }

    @property
    def call_id(self) -> str:
        return self._call_id

    def record_transport_report(self, report: Any) -> None:
        self._transport = {
            "start_time": report.start_time,
            "bot_connected_secs": report.bot_connected_secs,
            "client_connected_secs": report.client_connected_secs,
        }

    def record_turn_started(self, turn_number: int) -> None:
        self._turns.append({"turn_number": turn_number, "started": True})

    def record_turn_ended(
        self,
        turn_number: int,
        duration: float,
        was_interrupted: bool,
    ) -> None:
        self._turns.append(
            {
                "turn_number": turn_number,
                "duration_secs": duration,
                "was_interrupted": was_interrupted,
            }
        )

    def record_user_bot_latency(self, latency_seconds: float) -> None:
        self._latencies["user_to_bot_secs"].append(latency_seconds)

    def record_first_bot_speech_latency(self, latency_seconds: float) -> None:
        self._latencies["first_bot_speech_secs"] = latency_seconds

    def record_latency_breakdown(self, breakdown: Any) -> None:
        payload = _model_to_dict(breakdown)
        if isinstance(payload, dict) and self._processor_stages:
            for entry in payload.get("ttfb") or []:
                if not isinstance(entry, dict):
                    continue
                stage = self._processor_stages.get(entry.get("processor") or "")
                if stage:
                    entry["stage"] = stage
        self._latencies["breakdowns"].append(payload)

    def _build_summary(self) -> dict[str, Any]:
        completed_turns = [turn for turn in self._turns if "duration_secs" in turn]
        user_latencies = self._latencies["user_to_bot_secs"]

        summary: dict[str, Any] = {
            "turn_count": len(completed_turns),
            "interrupted_turn_count": sum(
                1 for turn in completed_turns if turn.get("was_interrupted")
            ),
        }

        if user_latencies:
            summary["user_bot_latency_avg_secs"] = sum(user_latencies) / len(
                user_latencies
            )
            summary["user_bot_latency_min_secs"] = min(user_latencies)
            summary["user_bot_latency_max_secs"] = max(user_latencies)

        return summary

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self._build_summary(),
            "transport": self._transport,
            "turns": self._turns,
            "latencies": self._latencies,
        }

    @property
    def has_content(self) -> bool:
        return bool(
            self._transport
            or self._turns
            or self._latencies["user_to_bot_secs"]
            or self._latencies["first_bot_speech_secs"] is not None
            or self._latencies["breakdowns"]
        )

    async def flush(self) -> None:
        """PUT aggregated metrics to the CallMetrics collection (once per call)."""
        if self._flushed or not self._call_id:
            return

        self._flushed = True
        if not self.has_content:
            logger.debug(
                "Skipping metrics flush — no metrics collected call_id={}",
                self._call_id,
            )
            return

        try:
            await backend_client.upsert_call_metrics(
                self._call_id,
                self._org_id,
                self.to_dict(),
            )
            logger.info("Persisted call metrics call_id={}", self._call_id)
        except Exception:
            logger.warning(
                "Failed to persist call metrics call_id={}",
                self._call_id,
                exc_info=True,
            )
