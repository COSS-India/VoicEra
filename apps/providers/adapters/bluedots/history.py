"""Shape the outbound message list for BlueDots (current turn only).

Pipecat keeps the whole conversation in the pipeline's ``LLMContext`` and hands
it to the service on every turn. BlueDots only wants the standing preamble plus
the current user turn — shaped here on the request, not on the context, so
aggregators, the transcript, and metrics still see the full conversation.
"""

from __future__ import annotations

from typing import Any

Messages = list[dict[str, Any]]

_PREAMBLE_ROLES = frozenset({"system", "developer"})


def trim_to_current_turn(messages: Messages) -> Messages:
    """Keep the preamble plus every message from the last user turn onward.

    The tail starts at the last ``user`` message rather than at the last
    message, because a turn that called a tool ends as ``user`` ->
    ``assistant`` (tool_calls) -> ``tool``, and an OpenAI endpoint rejects a
    ``tool`` message whose call is missing. Taking the whole tail keeps that
    exchange intact while still dropping every earlier turn.
    """
    last_user = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if messages[index].get("role") == "user"
        ),
        None,
    )
    if last_user is None:
        return messages

    preamble = [
        message
        for message in messages[:last_user]
        if message.get("role") in _PREAMBLE_ROLES
    ]
    return preamble + messages[last_user:]


__all__ = ["trim_to_current_turn"]
