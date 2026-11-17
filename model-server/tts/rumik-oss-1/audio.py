"""Output container/codec encoding: 24 kHz mono s16le PCM -> a response format.

**This file is adapted from tts/orpheus/src/orpheus_server/audio.py, and the
duplication is deliberate.** The TTS slot's build context is
`./tts/${TTS_MODEL}` -- one model folder, nothing above it -- so a shared
`tts/_common/` could only be reached by adding `additional_contexts` to
compose.model-server.yml, and the whole premise of the slot is that adding a
model never touches that file. A copy inside the folder is the cost of that
guarantee. If you fix a bug here, fix it there too; the two files are the same
logic over the same sample rate (SNAC and Mimi are both 24 kHz mono).

Which formats survive being sent in pieces was measured in that folder, and the
answer is not the obvious one: libsndfile SEEKS BACK AND PATCHES THE HEADER on
close. That is invisible if you inspect the finished buffer, but in a stream
those first bytes left long ago and the patch never reaches the client. So the
test that matters is whether the *concatenation of the emitted chunks* decodes,
not whether the final buffer does:

    format  header patched  chunk-concatenation decodes?
    pcm     n/a             yes
    wav     n/a (1)         yes
    mp3     yes             yes, +~80 ms of encoder padding (2)
    flac    yes             NO - bogus sample count in STREAMINFO
    opus    no              yes, but there is nothing to stream

    (1) WAV is written by this module, not libsndfile, using a max-length header.
    (2) Standard for streamed MP3: without the patched Xing header a decoder
        cannot trim encoder delay. Harmless for playback.

Hence `pcm` and `mp3` stream; `wav`, `flac` and `opus` are buffered so their
headers are correct -- which is also better for the common case of a client
writing the response straight to a file.
"""
from __future__ import annotations

import io
import struct

import numpy as np

#: Mimi's output rate. Read back from the codec's own feature extractor at
#: startup and asserted against this, so a codec revision that changed it fails
#: at load rather than producing audio at the wrong speed.
SAMPLE_RATE = 24000

# Format name -> (soundfile format, soundfile subtype, media type)
_SPEC: dict[str, tuple[str | None, str | None, str]] = {
    "pcm": (None, None, "audio/pcm"),
    "wav": ("WAV", "PCM_16", "audio/wav"),
    "mp3": ("MP3", None, "audio/mpeg"),
    "flac": ("FLAC", None, "audio/flac"),
    "opus": ("OGG", "OPUS", "audio/ogg"),
}

SUPPORTED_FORMATS = tuple(_SPEC)

#: Formats whose bytes can be emitted progressively and still decode. See the
#: module docstring: measured against chunk concatenation, not the final buffer.
STREAMING_FORMATS = frozenset({"pcm", "mp3"})


def media_type(fmt: str) -> str:
    return _SPEC[fmt][2]


def streams_incrementally(fmt: str) -> bool:
    """True if this format may be delivered as chunks rather than one body."""
    return fmt in STREAMING_FORMATS


def encodes_incrementally(fmt: str) -> bool:
    """True if ``make_encoder(fmt, streaming=True)`` really emits bytes as it is fed.

    Distinct from :func:`streams_incrementally`, which answers whether a format
    may be sent as a chunked HTTP *body*. WAV is excluded there so its RIFF
    length stays truthful, but it encodes incrementally perfectly well -- which
    is what SSE needs, since each delta is framed by the event stream rather
    than by the container.

    ``flac`` and ``opus`` fail both tests: their encoders buffer everything
    until close, so over SSE they would emit no deltas at all and then one
    enormous one.
    """
    return fmt in STREAMING_FORMATS or fmt == "wav"


# ---------------------------------------------------------------------------
# WAV headers
# ---------------------------------------------------------------------------
def wav_header(data_size: int, rate: int = SAMPLE_RATE, bits: int = 16, channels: int = 1) -> bytes:
    byte_rate = rate * channels * bits // 8
    block_align = channels * bits // 8
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_size, b"WAVE",
        b"fmt ", 16, 1, channels, rate, byte_rate, block_align, bits,
        b"data", data_size,
    )


def wrap_wav(pcm: bytes) -> bytes:
    """A complete WAV file with a correct length field."""
    return wav_header(len(pcm)) + pcm


def streaming_wav_header() -> bytes:
    """Header for a WAV of unknown length.

    Declares the largest legal data size so players keep reading instead of
    stopping at the declared end. The length field is deliberately wrong -- use
    this only when the total is genuinely unknown.
    """
    return wav_header(0xFFFFFFF0 - 36)


# ---------------------------------------------------------------------------
# Encoders
# ---------------------------------------------------------------------------
class Encoder:
    """Incremental PCM -> container encoder.

    ``feed`` returns whatever encoded bytes are ready (possibly empty);
    ``close`` returns the trailing bytes. Concatenating every return value in
    order yields the complete file.
    """

    media_type = "application/octet-stream"

    def feed(self, pcm: bytes) -> bytes:
        raise NotImplementedError

    def close(self) -> bytes:
        raise NotImplementedError


class RawPcmEncoder(Encoder):
    """Headerless 24 kHz mono s16le -- what OpenAI's ``pcm`` format means."""

    media_type = "audio/pcm"

    def feed(self, pcm: bytes) -> bytes:
        return pcm

    def close(self) -> bytes:
        return b""


class StreamingWavEncoder(Encoder):
    """WAV with a max-length header up front, PCM appended as it arrives."""

    media_type = "audio/wav"

    def __init__(self) -> None:
        self._sent_header = False

    def feed(self, pcm: bytes) -> bytes:
        if self._sent_header:
            return pcm
        self._sent_header = True
        return streaming_wav_header() + pcm

    def close(self) -> bytes:
        return b"" if self._sent_header else streaming_wav_header()


class BufferedWavEncoder(Encoder):
    """Collects all PCM and emits a WAV with the correct length at close.

    Used for non-streaming responses so tools that trust the RIFF length field
    (Python's ``wave``, most editors) report the true duration.
    """

    media_type = "audio/wav"

    def __init__(self) -> None:
        self._pcm = bytearray()

    def feed(self, pcm: bytes) -> bytes:
        self._pcm += pcm
        return b""

    def close(self) -> bytes:
        return wrap_wav(bytes(self._pcm))


class IncrementalMp3Encoder(Encoder):
    """libsndfile-backed MP3 encoder that emits frames as they are produced.

    Writes into a growing in-memory file and returns whatever appeared since
    the last call. The buffer is never truncated, because libsndfile seeks
    within it; the memory cost is the encoded audio itself (well under a
    megabyte per minute of speech).

    MP3 is the only compressed format safe to use this way -- see the module
    docstring for the measurement behind that.
    """

    media_type = "audio/mpeg"

    def __init__(self) -> None:
        import soundfile as sf

        self._buffer = io.BytesIO()
        self._cursor = 0
        self._file = sf.SoundFile(
            self._buffer, mode="w", samplerate=SAMPLE_RATE, channels=1, format="MP3",
        )

    def _drain(self) -> bytes:
        view = self._buffer.getbuffer()
        try:
            if len(view) <= self._cursor:
                return b""
            chunk = bytes(view[self._cursor:])
        finally:
            del view                  # release the export before the next write
        self._cursor += len(chunk)
        return chunk

    def feed(self, pcm: bytes) -> bytes:
        if pcm:
            self._file.write(np.frombuffer(pcm, dtype="<i2"))
            self._file.flush()
        return self._drain()

    def close(self) -> bytes:
        self._file.close()
        return self._drain()


class BufferedSoundFileEncoder(Encoder):
    """Collects all PCM and encodes once at close, for flac and opus.

    These cannot be delivered progressively: FLAC's STREAMINFO sample count and
    Ogg's page structure are finalised when the file is closed, and a client
    that already received the original header cannot be sent the correction.
    Encoding in one pass yields a completely valid file instead of a subtly
    broken stream.
    """

    def __init__(self, fmt: str) -> None:
        sf_format, sf_subtype, mime = _SPEC[fmt]
        self.media_type = mime
        self._format = sf_format
        self._subtype = sf_subtype
        self._pcm = bytearray()

    def feed(self, pcm: bytes) -> bytes:
        self._pcm += pcm
        return b""

    def close(self) -> bytes:
        import soundfile as sf

        if not self._pcm:
            return b""
        out = io.BytesIO()
        sf.write(out, np.frombuffer(bytes(self._pcm), dtype="<i2"), SAMPLE_RATE,
                 format=self._format, subtype=self._subtype)
        return out.getvalue()


def make_encoder(fmt: str, streaming: bool) -> Encoder:
    """Build an encoder for ``fmt``.

    ``streaming`` only affects WAV, which can be written either with a
    send-immediately max-length header or as a buffered file with an accurate
    one. Every other format has exactly one correct strategy, decided by
    whether it survives chunking at all (see ``STREAMING_FORMATS``).
    """
    if fmt not in _SPEC:
        raise ValueError(f"unsupported response_format {fmt!r}; expected one of {list(_SPEC)}")
    if fmt == "pcm":
        return RawPcmEncoder()
    if fmt == "wav":
        return StreamingWavEncoder() if streaming else BufferedWavEncoder()
    if fmt == "mp3":
        return IncrementalMp3Encoder()
    return BufferedSoundFileEncoder(fmt)


def pcm_duration_seconds(pcm_bytes: int) -> float:
    return pcm_bytes / 2 / SAMPLE_RATE
