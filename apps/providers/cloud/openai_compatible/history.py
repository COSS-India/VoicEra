"""Shape the outbound message list for endpoints that want less than all of it.

Pipecat keeps the whole conversation in the pipeline's ``LLMContext`` and hands
it to the service on every turn, system prompt first. Some endpoints want less:
one that stores its own session state only needs the current turn, and one that
composes its own instructions ignores whatever system prompt we send.

Both are shaped here — on the request, not on the context — so the aggregators,
the transcript, and the metrics keep seeing the full conversation as before.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Messages = list[dict[str, Any]]

# Roles that make up the standing preamble rather than a conversation turn.
_PREAMBLE_ROLES = frozenset({"system", "developer"})


def trim_to_current_turn(messages: Messages) -> Messages:
    """Keep the preamble plus every message from the last user turn onward.

    The tail starts at the last ``user`` message rather than at the last
    message, because a turn that called a tool ends as ``user`` ->
    ``assistant`` (tool_calls) -> ``tool``, and an OpenAI endpoint rejects a
    ``tool`` message whose call is missing. Taking the whole tail keeps that
    exchange — and any knowledge-base excerpts injected into the user message —
    intact while still dropping every earlier turn.
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
        # Nothing said yet (an opening greeting run, say) — there is no history
        # to drop, so send what we were given.
        return messages

    preamble = [
        message
        for message in messages[:last_user]
        if message.get("role") in _PREAMBLE_ROLES
    ]
    return preamble + messages[last_user:]


def drop_system_prompt(messages: Messages) -> Messages:
    """Drop every system / developer message, leaving the conversation alone."""
    kept = [
        message
        for message in messages
        if message.get("role") not in _PREAMBLE_ROLES
    ]
    if not kept:
        # Only a preamble to send, so dropping it would leave an empty request
        # the endpoint must reject. Send it and let the endpoint ignore it.
        return messages
    return kept


def message_shaper(
    *,
    history_mode: str,
    system_prompt_mode: str,
) -> Callable[[Messages], Messages] | None:
    """Compose the trims for one config, or ``None`` when nothing is trimmed.

    Order matters: the turn is cut first, while the preamble is still there to
    be recognised, and only then is the preamble itself dropped.
    """
    steps: list[Callable[[Messages], Messages]] = []
    if history_mode == "current_turn":
        steps.append(trim_to_current_turn)
    if system_prompt_mode == "omit":
        steps.append(drop_system_prompt)
    if not steps:
        return None

    def shape(messages: Messages) -> Messages:
        for step in steps:
            messages = step(messages)
        return messages

    return shape


__all__ = ["drop_system_prompt", "message_shaper", "trim_to_current_turn"]
