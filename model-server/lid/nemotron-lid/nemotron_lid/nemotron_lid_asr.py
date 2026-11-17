"""
Nemotron encoder LID.

Pipeline:
  audio → preprocessor → encoder → mean-pool → linear LID probe → language + confidence

The `.nemo` checkpoint is used only as a frozen feature extractor.
"""

from __future__ import annotations

import inspect
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import torch

from .nemotron_languages import APP_LID_LANGS, filter_app_lid_langs
from .nemotron_languages import NAME_TO_WIRE as LANG_NAME_TO_CODE

SAMPLE_RATE = 16000


def install_hydra_patch() -> None:
    import hydra._internal.instantiate._instantiate2 as hydra_instantiate

    orig = hydra_instantiate._call_target

    def _safe(_target_, _partial_, args, kwargs, full_key):
        try:
            sig = inspect.signature(_target_)
            if not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                valid = set(sig.parameters.keys())
                kwargs = {k: v for k, v in kwargs.items() if k in valid}
        except Exception:
            pass
        return orig(_target_, _partial_, args, kwargs, full_key)

    hydra_instantiate._call_target = _safe


def load_encoder(nemo_path: Path, device: str):
    """Load Nemotron checkpoint frozen for encoder-only feature extraction."""
    install_hydra_patch()
    import nemo.collections.asr as nemo_asr

    print(f"[load] Nemotron checkpoint: {nemo_path}")
    print(f"[load] device={device}")
    t0 = time.perf_counter()
    try:
        model = nemo_asr.models.ASRModel.restore_from(str(nemo_path), map_location=device, strict=True)
    except RuntimeError as e:
        msg = str(e)
        if "Unexpected key(s)" in msg and "Missing key(s)" not in msg and "size mismatch" not in msg:
            model = nemo_asr.models.ASRModel.restore_from(str(nemo_path), map_location=device, strict=False)
        else:
            raise
    model.eval()
    model.freeze()
    if hasattr(model.preprocessor, "featurizer"):
        model.preprocessor.featurizer.dither = 0.0
    print(
        f"[load] {type(model).__name__} / encoder={type(model.encoder).__name__}  "
        f"({time.perf_counter() - t0:.1f}s)"
    )
    return model


# Back-compat alias.
load_asr = load_encoder


def load_probe(probe_dir: Path):
    """
    Load linear probe + label mapping from probe_dir.

    Language names and wire codes come from label_mapping.json.
    Order follows mapping["label_names"] filtered to APP_LID_LANGS.
    """
    clf = joblib.load(probe_dir / "linear_lid_probe.joblib")
    mapping = json.loads((probe_dir / "label_mapping.json").read_text())
    raw_langs = list(mapping["label_names"])
    langs = filter_app_lid_langs(raw_langs)
    if set(raw_langs) != set(APP_LID_LANGS) or set(langs) != set(APP_LID_LANGS):
        raise RuntimeError(
            f"probe languages {raw_langs} are not exactly the supported set {APP_LID_LANGS}"
        )
    map_codes = mapping.get("lang_codes") or {}
    codes: dict[str, str] = {}
    for L in langs:
        code = map_codes.get(L) or LANG_NAME_TO_CODE.get(L)
        if not code:
            raise KeyError(f"no language code for {L!r} in label_mapping.json")
        codes[L] = code
    print(f"[load] probe: {probe_dir / 'linear_lid_probe.joblib'}")
    print(f"[load] mapping: {probe_dir / 'label_mapping.json'}")
    print(f"[load] languages ({len(langs)}): {langs}")
    print(f"[load] codes: {codes}")
    return clf, langs, codes


def load_audio_16k_mono(path: Path) -> np.ndarray:
    try:
        import torchaudio

        wav, sr = torchaudio.load(str(path))
        if wav.size(0) > 1:
            wav = wav.mean(dim=0, keepdim=True)
        wav = wav.squeeze(0)
        if sr != SAMPLE_RATE:
            wav = torchaudio.functional.resample(wav, sr, SAMPLE_RATE)
        return wav.numpy().astype(np.float32, copy=False)
    except Exception:
        pass
    import librosa

    audio, _ = librosa.load(str(path), sr=SAMPLE_RATE, mono=True)
    return np.asarray(audio, dtype=np.float32)


def classify(clf, emb: np.ndarray, langs: list[str]) -> tuple[str, np.ndarray]:
    if hasattr(clf, "predict_proba"):
        proba = clf.predict_proba(emb.reshape(1, -1))[0]
    else:
        pred_id = int(clf.predict(emb.reshape(1, -1))[0])
        proba = np.zeros(len(langs), dtype=np.float64)
        proba[pred_id] = 1.0
    pred_id = int(np.argmax(proba))
    return langs[pred_id], np.asarray(proba, dtype=np.float64)


def mean_pool_encoded(encoded: torch.Tensor, encoded_len: torch.Tensor) -> np.ndarray:
    """
    Mean-pool pre-prompt encoder frames → (D,) float32 embedding.

    Same pooling used by encode_mean_pool / probe training. Does not run the
    encoder or modify the classifier.
    """
    T = int(encoded_len[0].item())
    if T <= 0:
        raise RuntimeError("encoder returned empty sequence")
    return encoded[0, :, :T].float().mean(dim=-1).cpu().numpy().astype(np.float32)


def classify_from_encoded(
    clf,
    langs: list[str],
    lang_codes: dict[str, str],
    encoded: torch.Tensor,
    encoded_len: torch.Tensor,
) -> tuple[str, str, float, dict[str, float]]:
    """
    Existing LID probe on already-computed pre-prompt encoder output.

    mean-pool → StandardScaler → LogisticRegression (unchanged probe).
    """
    emb = mean_pool_encoded(encoded, encoded_len)
    language, proba = classify(clf, emb, langs)
    if language not in lang_codes:
        raise KeyError(f"no language code for predicted language {language!r}")
    conf = float(proba[langs.index(language)])
    probs = {langs[i]: float(proba[i]) for i in range(len(langs))}
    return language, lang_codes[language], conf, probs


@dataclass
class LidResult:
    language: str
    lang_code: str
    confidence: float
    probabilities: dict[str, float]
    duration_s: float
    encoder_s: float
    lid_s: float
    total_s: float
    timing: dict = field(default_factory=dict)


@torch.inference_mode()
def encode_mean_pool(
    model,
    audio: np.ndarray,
    device: str,
    use_fp16: bool = False,
) -> tuple[np.ndarray, float]:
    """Preprocessor + encoder + mean-pool → (D,) embedding and encoder wall time."""
    if audio.ndim != 1:
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    audio = np.ascontiguousarray(audio, dtype=np.float32)
    if audio.size < SAMPLE_RATE // 20:
        raise RuntimeError("audio too short (<50 ms)")

    wav = torch.from_numpy(audio).unsqueeze(0).to(device)
    wav_len = torch.tensor([wav.shape[1]], device=device, dtype=torch.long)

    t0 = time.perf_counter()
    mel, mel_len = model.preprocessor(input_signal=wav, length=wav_len)
    if use_fp16 and str(device).startswith("cuda"):
        with torch.autocast(device_type="cuda", dtype=torch.float16):
            encoded, encoded_len = model.encoder(audio_signal=mel, length=mel_len)
    else:
        encoded, encoded_len = model.encoder(audio_signal=mel, length=mel_len)
    encoder_s = time.perf_counter() - t0

    T = int(encoded_len[0].item())
    if T <= 0:
        raise RuntimeError("encoder returned empty sequence")
    emb = encoded[0, :, :T].float().mean(dim=-1).cpu().numpy().astype(np.float32)
    return emb, encoder_s


def encode_pre_prompt(model, audio, device, use_fp16: bool = False):
    emb, encoder_s = encode_mean_pool(model, audio, device, use_fp16=use_fp16)
    return None, None, emb, encoder_s


def run_lid(
    model,
    clf,
    langs: list[str],
    lang_codes: dict[str, str],
    audio: np.ndarray,
    device: str,
    use_fp16: bool = False,
) -> LidResult:
    """Encoder → mean-pool → LID classifier."""
    t_all = time.perf_counter()
    emb, encoder_s = encode_mean_pool(model, audio, device, use_fp16=use_fp16)

    t1 = time.perf_counter()
    language, proba = classify(clf, emb, langs)
    lid_s = time.perf_counter() - t1

    if language not in lang_codes:
        raise KeyError(f"no language code for predicted language {language!r}")
    lang_code = lang_codes[language]

    total_s = time.perf_counter() - t_all
    return LidResult(
        language=language,
        lang_code=lang_code,
        confidence=float(proba[langs.index(language)]),
        probabilities={langs[i]: float(proba[i]) for i in range(len(langs))},
        duration_s=float(audio.size) / SAMPLE_RATE,
        encoder_s=encoder_s,
        lid_s=lid_s,
        total_s=total_s,
        timing={
            "encoder_ms": encoder_s * 1000,
            "lid_ms": lid_s * 1000,
            "total_ms": total_s * 1000,
        },
    )


def format_result(r: LidResult) -> str:
    return "\n".join(
        [
            f"Language: {r.language} ({r.lang_code})",
            f"Confidence: {r.confidence * 100:.1f}%",
            (
                f"Latency: encoder={r.encoder_s * 1000:.0f} ms  "
                f"LID={r.lid_s * 1000:.1f} ms  "
                f"total={r.total_s * 1000:.0f} ms  "
                f"(audio {r.duration_s:.2f}s)"
            ),
        ]
    )
