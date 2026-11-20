"""Blue Dots ``call_output``: Raya's KKB Slim output, built from AI DPG.

Agent Core does not produce ``call_output``. Every turn and tool call is
logged to AI DPG's Loki, keyed by ``session_id = <caller_phone>:<call_id>``
(the ``call_id`` VoicEra sends in ``metadata``). This adapter reads one
call's lines (phases, tool outcomes), runs Blue Dots' KKB Slim output prompt
over the VoicEra transcript, and overrides the fields the tool calls settle.
"""
