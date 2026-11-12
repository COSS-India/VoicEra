"""Shaping transcripts into OpenAI Realtime events.

This file is model-agnostic on purpose: it holds the part of the protocol that
must be identical across every STT model in the slot, so that switching model
cannot change what a caller receives. Nothing here knows how audio is decoded.

**It is vendored, not shared.** An identical copy lives in each STT model
folder, because a model folder is meant to be something you copy into place --
importing across folders would break that. Duplication is the deliberate cost;
drift is not allowed, and the tests fail if the copies stop matching. Fix a bug
here and copy the file, do not patch one folder.

The delta rule is the whole reason this exists as a unit:

    a delta is one whole word, and it is not sent until it cannot change

Two separate mistakes are being avoided, and they were made in that order.

**Whole words, not characters.** Comparing transcript snapshots character by
character looks correct until the decoder resolves a partial token -- hearing
"नम" and then "नमस्ते". That is a character-prefix extension, so a character diff
emits "स्ते" as its own delta; each delta carries a trailing space, so the
consumer assembles "नम स्ते". One word, broken in half.

**Append-only, not withdraw-and-resend.** The first fix caught the revision but
signalled it by advancing `content_index`, on the reading that a consumer would
start a new content part and discard the old one. The spec does not say that.
`content_index` is "the index of the content part in the item's content array"
-- a position, not a version. A consumer doing the obvious thing, concatenating
the deltas it receives, assembles "नम नमस्ते दुनिया" and keeps the withdrawn
fragment. The whole reason for speaking a published protocol is that a client
we did not write is correct by default, and that reading made correctness
depend on a convention only this repo knows.

So a word is held until it is settled, and settled means one of:

  * a later word exists, which is proof the decoder has moved past it, or
  * it has been unchanged for `debounce_s`, or
  * the turn ended.

The trailing word is the only one ever in doubt, so this costs at most one word
of interim latency and never delays a word that has a successor. Holding it
until turn end instead -- the fully safe option -- was rejected because a
one-word utterance would then show nothing at all until the speaker stopped,
which is the opposite of what interim transcripts are for.

`content_index` survives as an escape hatch for the case this cannot cover: a
decoder that changes a word *after* it was released. AlignAtt commits tokens,
so a released word changing is not expected -- but "not expected" is not
"impossible", and silently emitting a contradiction is worse than signalling one
badly. If that path ever fires in practice, the debounce is too short.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable

#: How long a trailing word must sit unchanged before it is released, when no
#: following word has arrived to settle it. Comfortably longer than the decode
#: tick (240 ms at the shipped geometry would settle it on the next tick anyway)
#: and short enough to stay under the ~290 ms at which words are spoken.
DEBOUNCE_S = 0.20


def event_id() -> str:
    return f"event_{uuid.uuid4().hex[:16]}"


def item_id() -> str:
    return f"item_{uuid.uuid4().hex[:16]}"


def normalize_ws(text: str) -> str:
    return " ".join(text.split())


def word_prefix_extends(last_emitted: str, full_text: str) -> bool:
    """True when full_text keeps every word already emitted (maybe adds more).

    Word-wise, not character-wise. "hel" -> "hello" is a character-prefix
    extension and a word-prefix *revision*, and the second reading is the one
    that produces a transcript a human would accept.
    """
    last_words = last_emitted.split()
    full_words = full_text.split()
    if not last_words:
        return True
    if len(full_words) < len(last_words):
        return False
    return full_words[: len(last_words)] == last_words


class DeltaEmitter:
    """Turns successive transcript snapshots into transcription delta events.

    A decoder hands over what it currently believes the whole utterance says,
    repeatedly, revising as it goes. This converts that into the append-only
    stream of whole words the OpenAI Realtime protocol describes.
    """

    def __init__(self, debounce_s: float = DEBOUNCE_S, clock=time.monotonic) -> None:
        #: Words already sent to the client. Append-only by construction.
        self.emitted_text = ""
        #: The trailing word, seen but not yet released.
        self.pending_word = ""
        self.pending_since = 0.0
        #: The whole snapshot the pending word came from, so releasing it later
        #: restores exactly the text that was current when it was held.
        self._pending_full = ""
        self._flush_task: asyncio.Task | None = None
        self.content_index = 0
        self.item_id = item_id()
        self._debounce_s = debounce_s
        self._clock = clock

    def reset(self) -> None:
        self._cancel_flush()
        self.emitted_text = ""
        self.pending_word = ""
        self.pending_since = 0.0
        self._pending_full = ""
        self.content_index = 0
        self.item_id = item_id()

    def _cancel_flush(self) -> None:
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_task.cancel()
        self._flush_task = None

    def _schedule_flush(self, send: Callable[[dict], Awaitable[None]]) -> None:
        """Promise the held word within `debounce_s`, whatever the producer does.

        Releasing it on the next snapshot alone is not a promise this class can
        keep: it depends on the decoder continuing to produce snapshots. A
        model that emits one interim and then goes quiet -- which is exactly
        what a short utterance looks like -- would hold its only word until the
        turn ended, which is the failure the debounce exists to avoid.
        """
        self._cancel_flush()
        try:
            self._flush_task = asyncio.get_running_loop().create_task(self._flush_later(send))
        except RuntimeError:
            # No loop (a synchronous test driving the clock by hand). The
            # next update or `completed` still releases it.
            self._flush_task = None

    async def _flush_later(self, send: Callable[[dict], Awaitable[None]]) -> None:
        try:
            await asyncio.sleep(self._debounce_s)
        except asyncio.CancelledError:
            return
        word, full = self.pending_word, self._pending_full
        if not word:
            return
        self.pending_word = ""
        self.emitted_text = full
        await self._emit(word, send)

    async def _emit(self, word: str, send: Callable[[dict], Awaitable[None]]) -> None:
        await send({
            "type": "conversation.item.input_audio_transcription.delta",
            "event_id": event_id(),
            "item_id": self.item_id,
            "content_index": self.content_index,
            # The trailing space is what makes deltas concatenable. It is only
            # correct because each delta is a whole word.
            "delta": word if word.endswith(" ") else f"{word} ",
        })

    async def update(
        self,
        full_text: str,
        send: Callable[[dict], Awaitable[None]],
    ) -> None:
        """Release whatever `full_text` has settled since the last call."""
        full = normalize_ws(full_text)
        if not full:
            return
        words = full.split()

        if self.emitted_text and not word_prefix_extends(self.emitted_text, full):
            # A word that was already released has changed. See the module
            # docstring: this is not expected, and staying silent would emit a
            # transcript that contradicts itself with nothing to say so.
            self.content_index += 1
            self.emitted_text = ""
            self.pending_word = ""

        released = self.emitted_text.split()

        # Every word but the last has a successor, which is proof the decoder
        # has moved past it. Those are safe to send.
        settled = words[:-1]
        for word in settled[len(released):]:
            await self._emit(word, send)
        if len(settled) > len(released):
            self.emitted_text = " ".join(settled)
            released = settled

        if len(released) >= len(words):
            # Nothing left in this snapshot that has not gone out.
            self._cancel_flush()
            self.pending_word = ""
            return

        # The trailing word is the only one that can still change. Hold it until
        # it has sat unchanged long enough to trust, or until a successor
        # arrives on a later call and settles it above.
        tail = words[-1]
        now = self._clock()
        if tail != self.pending_word:
            self.pending_word = tail
            self.pending_since = now
            self._pending_full = full
            self._schedule_flush(send)
        elif now - self.pending_since >= self._debounce_s:
            self._cancel_flush()
            self.pending_word = ""
            self.emitted_text = full
            await self._emit(tail, send)

    async def completed(
        self,
        transcript: str,
        send: Callable[[dict], Awaitable[None]],
    ) -> None:
        """Flush the held word, then declare the turn's transcript final.

        The flush matters: without it the last word of every turn would reach a
        delta-only consumer solely inside `completed`, which is a different
        shape from every other word and the kind of difference that shows up as
        one missing word in someone else's UI.
        """
        self._cancel_flush()
        if self.pending_word:
            word = self.pending_word
            self.pending_word = ""
            self.emitted_text = normalize_ws(transcript) or self._pending_full
            await self._emit(word, send)
        await send({
            "type": "conversation.item.input_audio_transcription.completed",
            "event_id": event_id(),
            "item_id": self.item_id,
            "content_index": self.content_index,
            "transcript": transcript,
        })
