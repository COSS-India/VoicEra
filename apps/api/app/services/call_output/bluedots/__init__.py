"""Blue Dots ``call_output``: funnel fields from AI DPG (Agent Core) logs.

Agent Core does not produce ``call_output``. Every turn and tool call is
logged to its Loki, keyed by ``session_id = <caller_phone>:<call_id>``
(the ``call_id`` VoicEra sends in ``metadata``). This adapter reads one
call's lines, turns them into signals (phase per turn, tool outcomes) and
maps those, plus the VoicEra transcript, onto funnel fields.
"""
