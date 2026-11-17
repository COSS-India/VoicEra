"""
Cache-aware streaming ASR session with optional once-per-utterance auto-LID.

Manual language (e.g. language=\"hi\"): existing encode→prompt→decode each step.
Auto language (language=\"auto\"):

  first ~2s of streaming encoder steps (encode only, retain encoded + caches)
       → existing LID probe on mean-pooled pre-prompt frames
       → configure prompt/VocabSlicer WITHOUT reset
       → RNNT-decode retained frames (no re-encode)
       → continue streaming with the same encoder caches
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import torch

from .nemotron_lid_asr import SAMPLE_RATE, classify_from_encoded
from . import streaming_engine as _eng
from .streaming_engine import (
    configure_decoder_language,
    get_initial_cache,
    get_streaming_params,
    resolve_prompt_lang,
    stream_decode_encoded,
    stream_encode_step,
)

# Mel context for bit-stable online preprocessor windows (same as model-server).
MEL_LEFT_CTX_FRAMES = 3
MEL_RIGHT_CTX_FRAMES = 2

# Prefer streaming chunk geometry over an exact 2.000s offline window.
LID_MIN_AUDIO_S = float(os.environ.get("LID_MIN_AUDIO_S", "2.0"))


@dataclass
class RetainedEncode:
    encoded: torch.Tensor
    encoded_len: torch.Tensor
    frames_consumed: int


@dataclass
class StepResult:
    text: str = ""
    status: str = "streaming"  # waiting_lid | lid_locked | streaming | lid_incomplete | final
    language: Optional[str] = None
    lang_code: Optional[str] = None
    confidence: Optional[float] = None
    encoder_forwards: int = 0
    lid_runs: int = 0
    extras: dict = field(default_factory=dict)


class StreamingASRSession:
    """
    One utterance of cache-aware streaming ASR.

    language=\"auto\" enables automatic LID on the first LID_MIN_AUDIO_S of
    streaming-encoder output. language=<code> preserves manual ASR behavior.
    """

    def __init__(
        self,
        model,
        *,
        language: str = "auto",
        lid_clf=None,
        lid_langs: list[str] | None = None,
        lid_codes: dict[str, str] | None = None,
        session_id: str = "sess",
        lid_min_audio_s: float = LID_MIN_AUDIO_S,
    ):
        self.model = model
        self.session_id = session_id
        self.language_code = language.strip().lower()
        self.auto_lid = self.language_code == "auto"
        self.lid_clf = lid_clf
        self.lid_langs = lid_langs or []
        self.lid_codes = lid_codes or {}
        self.lid_min_audio_s = float(lid_min_audio_s)

        if self.auto_lid and (lid_clf is None or not lid_langs or not lid_codes):
            raise ValueError("auto language requires lid_clf, lid_langs, and lid_codes")

        p = get_streaming_params(model)
        self.chunk_size = p["chunk_size"]
        self.shift_size = p["shift_size"]
        self.pre_encode_cache_size = p["pre_encode_cache_size"]
        self.drop_extra_pre_encoded = p["drop_extra_pre_encoded"]
        self.sampling_frames = p["sampling_frames"]
        self.hop = p["hop_length"]
        self.feat_in = p["feat_in"]

        self.target_lang: Optional[str] = None
        if not self.auto_lid:
            self.target_lang = resolve_prompt_lang(self.language_code)
            configure_decoder_language(model, self.target_lang)

        self._reset_utterance_state()

    # ------------------------------------------------------------------ state

    def _reset_utterance_state(self):
        """Clear LID + encoder/decoder state for a new utterance/session."""
        self.cache_channel, self.cache_time, self.cache_len = get_initial_cache(self.model, 1)
        self.prev_hyp = None
        self.prev_pred_out = None
        self.step_num = 0

        self.raw = np.zeros(0, dtype=np.float32)
        self.raw_offset = 0
        self.mel_done = 0
        self.mel_buffer: Optional[torch.Tensor] = None
        self.mel_base = 0
        self.buffer_idx = 0

        self.last_text = ""
        self.encoder_forwards_at_start = int(getattr(self.model, "_encoder_stream_forwards", 0))
        self.encoder_forwards = 0
        self.lid_runs = 0
        self.lid_done = False
        self.lid_incomplete = False
        self.detected_language: Optional[str] = None
        self.detected_code: Optional[str] = None
        self.detected_confidence: Optional[float] = None
        self.retained: list[RetainedEncode] = []
        self.lid_audio_s = 0.0
        self._reset_called_for_lid = False  # must stay False after LID lock

        if self.auto_lid:
            self.target_lang = None
            print(f"[LID_START] session={self.session_id} min_audio_s={self.lid_min_audio_s}")

    def reset_utterance(self):
        """Public reset for a new utterance on the same connection."""
        self._reset_utterance_state()

    def set_language_manual(self, lang_code: str):
        """
        Manual language change — resets streaming state (existing behavior).

        Do NOT use this after auto-LID; use configure_decoder_language instead.
        """
        self.language_code = lang_code.strip().lower()
        self.auto_lid = self.language_code == "auto"
        if self.auto_lid:
            self.target_lang = None
        else:
            self.target_lang = resolve_prompt_lang(self.language_code)
            configure_decoder_language(self.model, self.target_lang)
        self._reset_utterance_state()
        self._reset_called_for_lid = True  # only for manual path bookkeeping

    # ------------------------------------------------------------------ audio

    def append_pcm(self, audio: np.ndarray):
        if audio.size == 0:
            return
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        self.raw = np.concatenate((self.raw, audio))

    def append_int16_bytes(self, raw_bytes: bytes):
        audio = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        self.append_pcm(audio)

    def _mel_window(self, final: bool):
        first = max(0, self.mel_done - MEL_LEFT_CTX_FRAMES)
        w0 = first * self.hop
        if w0 < self.raw_offset:
            return None
        seg = self.raw[w0 - self.raw_offset :]
        if len(seg) == 0:
            return None
        n_frames = len(seg) // self.hop + 1
        drop_l = self.mel_done - first
        drop_r = 0 if final else MEL_RIGHT_CTX_FRAMES
        keep = n_frames - drop_l - drop_r
        if keep <= 0:
            return None
        return np.ascontiguousarray(seg), drop_l, keep

    def _commit_mel(self, mel: torch.Tensor, drop_l: int, keep: int):
        new = mel[:, :, drop_l : drop_l + keep]
        if new.size(-1) == 0:
            return
        self.mel_buffer = new if self.mel_buffer is None else torch.cat((self.mel_buffer, new), dim=-1)
        self.mel_done += new.size(-1)
        keep_from = max(0, (self.mel_done - MEL_LEFT_CTX_FRAMES) * self.hop)
        if keep_from > self.raw_offset:
            cut = keep_from - self.raw_offset
            self.raw = self.raw[cut:]
            self.raw_offset += cut

    def _grow_mel(self, final: bool = False):
        window = self._mel_window(final)
        if window is None:
            return
        seg, drop_l, keep = window
        seg_t = torch.from_numpy(seg).unsqueeze(0).to(_eng.DEVICE)
        seg_len = torch.tensor([len(seg)], device=_eng.DEVICE, dtype=torch.long)
        with torch.inference_mode():
            mel, _ = self.model.preprocessor(input_signal=seg_t, length=seg_len)
        self._commit_mel(mel, drop_l, keep)

    def _available_frames(self) -> int:
        if self.mel_buffer is None:
            return 0
        return self.mel_buffer.size(-1) - self.buffer_idx

    def has_full_chunk(self) -> bool:
        need = self.chunk_size[0] if self.step_num == 0 else self.chunk_size[1]
        return self._available_frames() >= need

    def _build_chunk(self):
        first = self.step_num == 0
        chunk = self.chunk_size[0] if first else self.chunk_size[1]
        shift = self.shift_size[0] if first else self.shift_size[1]
        pre_cache = self.pre_encode_cache_size[0] if first else self.pre_encode_cache_size[1]
        drop_extra = 0 if first else self.drop_extra_pre_encoded
        min_frames = self.sampling_frames[0] if first else self.sampling_frames[1]

        take = min(chunk, self._available_frames())
        if take < min_frames:
            return None

        with torch.inference_mode():
            audio_chunk = self.mel_buffer[:, :, self.buffer_idx : self.buffer_idx + take]
            if pre_cache == 0:
                chunk_with_cache = audio_chunk
            else:
                start = max(0, self.buffer_idx - pre_cache)
                cache_pre = self.mel_buffer[:, :, start : self.buffer_idx]
                if cache_pre.size(-1) < pre_cache:
                    pad = torch.zeros(
                        (1, self.feat_in, pre_cache - cache_pre.size(-1)),
                        device=self.mel_buffer.device,
                        dtype=self.mel_buffer.dtype,
                    )
                    cache_pre = torch.cat((pad, cache_pre), dim=-1)
                chunk_with_cache = torch.cat((cache_pre, audio_chunk), dim=-1)
        return chunk_with_cache.contiguous(), shift, take, drop_extra

    def _advance_buffer(self, shift: int, take: int):
        consumed = min(shift, take)
        self.buffer_idx += consumed
        self.step_num += 1
        retain = self.pre_encode_cache_size[1]
        if self.buffer_idx > retain:
            cut = self.buffer_idx - retain
            self.mel_buffer = self.mel_buffer[:, :, cut:].contiguous()
            self.mel_base += cut
            self.buffer_idx = retain
        return consumed

    # ------------------------------------------------------------------ steps

    def _encode_one(self, chunk, drop_extra, keep_all: bool) -> RetainedEncode:
        before = int(getattr(self.model, "_encoder_stream_forwards", 0))
        lengths = torch.full((1,), chunk.size(-1), device=chunk.device, dtype=torch.long)
        encoded, encoded_len, cc, ct, cl = stream_encode_step(
            self.model,
            chunk,
            lengths,
            self.cache_channel,
            self.cache_time,
            self.cache_len,
            keep_all_outputs=keep_all,
            drop_extra=drop_extra,
        )
        after = int(getattr(self.model, "_encoder_stream_forwards", 0))
        self.encoder_forwards += max(0, after - before)
        self.cache_channel, self.cache_time, self.cache_len = cc, ct, cl
        return RetainedEncode(encoded=encoded, encoded_len=encoded_len, frames_consumed=0)

    def _decode_one(self, retained: RetainedEncode) -> str:
        assert self.target_lang is not None
        text, hyps, pred = stream_decode_encoded(
            self.model,
            retained.encoded,
            retained.encoded_len,
            self.target_lang,
            previous_hypotheses=self.prev_hyp,
        )
        self.prev_hyp = hyps
        self.prev_pred_out = pred
        if text:
            self.last_text = text
        return self.last_text

    def _run_lid_and_decode_retained(self) -> StepResult:
        """LID once on concatenated retained pre-prompt frames, then decode each chunk."""
        assert self.auto_lid and not self.lid_done
        if not self.retained:
            self.lid_incomplete = True
            return StepResult(
                status="lid_incomplete",
                encoder_forwards=self.encoder_forwards,
                lid_runs=self.lid_runs,
            )

        t0 = time.perf_counter()
        # Concatenate along time for mean-pool / probe (same pre-prompt representation).
        frames = []
        total_t = 0
        for r in self.retained:
            t = int(r.encoded_len[0].item())
            frames.append(r.encoded[:, :, :t])
            total_t += t
        cat = torch.cat(frames, dim=-1)
        cat_len = torch.tensor([total_t], device=cat.device, dtype=torch.long)

        language, code, conf, _probs = classify_from_encoded(
            self.lid_clf, self.lid_langs, self.lid_codes, cat, cat_len
        )
        self.lid_runs += 1
        lid_ms = (time.perf_counter() - t0) * 1000.0

        # Configure decoder WITHOUT resetting encoder caches / retained frames.
        prompt_lang = resolve_prompt_lang(code)
        configure_decoder_language(self.model, prompt_lang)
        self.target_lang = prompt_lang
        self.detected_language = language
        self.detected_code = code
        self.detected_confidence = conf
        self.lid_done = True

        print(
            f"[LID_RESULT] language={language} code={code} "
            f"confidence={conf:.4f} latency_ms={lid_ms:.1f} "
            f"encoder_forwards={self.encoder_forwards} retained_chunks={len(self.retained)}"
        )
        print(f"[ASR_START] language={prompt_lang} session={self.session_id}")

        # Decode retained chunks in order (no re-encode).
        text = ""
        for r in self.retained:
            text = self._decode_one(r)
        # Keep retained list for tests; clear is optional. Do not re-encode.
        return StepResult(
            text=text,
            status="lid_locked",
            language=language,
            lang_code=code,
            confidence=conf,
            encoder_forwards=self.encoder_forwards,
            lid_runs=self.lid_runs,
            extras={
                "lid_ms": lid_ms,
                "reset_after_lid": self._reset_called_for_lid,
                "cache_preserved": True,
            },
        )

    def step(self, is_last_chunk: bool = False) -> StepResult:
        built = self._build_chunk()
        if built is None:
            return StepResult(
                text=self.last_text,
                status="waiting_lid" if (self.auto_lid and not self.lid_done) else "streaming",
                language=self.detected_language,
                lang_code=self.detected_code,
                confidence=self.detected_confidence,
                encoder_forwards=self.encoder_forwards,
                lid_runs=self.lid_runs,
            )

        chunk, shift, take, drop_extra = built
        retained = self._encode_one(chunk, drop_extra, keep_all=is_last_chunk)
        consumed = self._advance_buffer(shift, take)
        retained.frames_consumed = consumed
        self.lid_audio_s += consumed * self.hop / float(SAMPLE_RATE)

        if self.auto_lid and not self.lid_done:
            self.retained.append(retained)
            if self.lid_audio_s >= self.lid_min_audio_s or is_last_chunk:
                if self.lid_audio_s < self.lid_min_audio_s and is_last_chunk:
                    # Explicit incomplete handling — do not guess a language.
                    self.lid_incomplete = True
                    print(
                        f"[LID_INCOMPLETE] session={self.session_id} "
                        f"audio_s={self.lid_audio_s:.3f} < {self.lid_min_audio_s}"
                    )
                    return StepResult(
                        status="lid_incomplete",
                        encoder_forwards=self.encoder_forwards,
                        lid_runs=self.lid_runs,
                        extras={"lid_audio_s": self.lid_audio_s},
                    )
                return self._run_lid_and_decode_retained()
            return StepResult(
                status="waiting_lid",
                encoder_forwards=self.encoder_forwards,
                lid_runs=self.lid_runs,
                extras={"lid_audio_s": self.lid_audio_s},
            )

        # Manual language, or post-LID: decode this chunk (already encoded once).
        text = self._decode_one(retained)
        return StepResult(
            text=text,
            status="streaming",
            language=self.detected_language or self.language_code,
            lang_code=self.detected_code or self.language_code,
            confidence=self.detected_confidence,
            encoder_forwards=self.encoder_forwards,
            lid_runs=self.lid_runs,
        )

    def process_available(self, final: bool = False) -> list[StepResult]:
        self._grow_mel(final=final)
        out: list[StepResult] = []
        while self.has_full_chunk():
            out.append(self.step(is_last_chunk=False))
            if self.lid_incomplete:
                break
        return out

    def flush(self) -> StepResult:
        """End of utterance: commit mel tail and drain chunks."""
        self._grow_mel(final=True)
        last = StepResult(
            text=self.last_text,
            status="final",
            language=self.detected_language or (None if self.auto_lid else self.language_code),
            lang_code=self.detected_code or (None if self.auto_lid else self.language_code),
            confidence=self.detected_confidence,
            encoder_forwards=self.encoder_forwards,
            lid_runs=self.lid_runs,
        )
        while self.has_full_chunk():
            # Mark last model chunk so keep_all_outputs can flush the tail.
            need = self.chunk_size[0] if self.step_num == 0 else self.chunk_size[1]
            remaining_after = self._available_frames() - need
            next_need = self.chunk_size[1]
            is_last = remaining_after < next_need
            last = self.step(is_last_chunk=is_last)
            if self.lid_incomplete:
                last.status = "lid_incomplete"
                return last
        if self.auto_lid and not self.lid_done:
            self.lid_incomplete = True
            last.status = "lid_incomplete"
            print(
                f"[LID_INCOMPLETE] session={self.session_id} flush "
                f"audio_s={self.lid_audio_s:.3f}"
            )
            return last
        last.status = "final"
        last.text = self.last_text
        return last
