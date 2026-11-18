"""Turn a call's AI DPG log lines into signals.

Only structured lines are read, as Blue Dots asked:

* ``orchestrator.stream_turn_complete`` (agent_core): one per turn, with
  ``next_subagent_id`` (the phase the call moved to), ``intent`` and
  ``tool_used``. Some turns (first turn, fixed lines, goodbye) only have a
  free-text line today; Blue Dots is adding the structured line to every
  turn, so the free text is deliberately ignored.
* ``RestApiAdapter.execute`` (action_gateway): one per tool call, with
  ``tool_name`` and ``status`` (``success`` / ``failure``). Request and
  response bodies are not read: they are only logged at DEBUG level.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.services.call_output.bluedots.loki import LogLine

TURN_COMPLETE = "orchestrator.stream_turn_complete"
TOOL_OPERATION = "RestApiAdapter.execute"


@dataclass
class Turn:
    ts_ns: int
    trace_id: str | None
    phase: str | None
    intent: str | None
    tool_used: bool | None


@dataclass
class ToolCall:
    ts_ns: int
    trace_id: str | None
    tool: str
    ok: bool
    error: str | None = None


@dataclass
class CallSignals:
    turns: list[Turn] = field(default_factory=list)
    tools: list[ToolCall] = field(default_factory=list)

    @property
    def phases(self) -> list[str]:
        return [turn.phase for turn in self.turns if turn.phase]

    @property
    def last_phase(self) -> str | None:
        phases = self.phases
        return phases[-1] if phases else None

    def reached(self, *phases: str) -> bool:
        wanted = set(phases)
        return any(phase in wanted for phase in self.phases)

    def succeeded(self, tool: str) -> int:
        return sum(1 for call in self.tools if call.tool == tool and call.ok)

    def failed(self, tool: str) -> int:
        return sum(1 for call in self.tools if call.tool == tool and not call.ok)

    @property
    def empty(self) -> bool:
        return not self.turns and not self.tools

    def to_dict(self) -> dict[str, Any]:
        return {
            "phases": self.phases,
            "turns": [asdict(turn) for turn in self.turns],
            "tools": [asdict(call) for call in self.tools],
        }


def extract(lines: list[LogLine]) -> CallSignals:
    signals = CallSignals()
    for line in sorted(lines, key=lambda item: item.ts_ns):
        attrs = line.attributes
        trace_id = line.record.get("traceid")
        if line.record.get("body") == TURN_COMPLETE:
            tool_used = attrs.get("tool_used")
            signals.turns.append(
                Turn(
                    ts_ns=line.ts_ns,
                    trace_id=trace_id,
                    phase=(str(attrs["next_subagent_id"]) if attrs.get("next_subagent_id") else None),
                    intent=(str(attrs["intent"]) if attrs.get("intent") else None),
                    tool_used=bool(tool_used) if tool_used is not None else None,
                )
            )
        elif attrs.get("operation") == TOOL_OPERATION and attrs.get("tool_name"):
            status = str(attrs.get("status") or "").lower()
            signals.tools.append(
                ToolCall(
                    ts_ns=line.ts_ns,
                    trace_id=trace_id,
                    tool=str(attrs["tool_name"]),
                    ok=status == "success",
                    error=(str(attrs["error"]) if attrs.get("error") else None),
                )
            )
    return signals
