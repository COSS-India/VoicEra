"""
Resolve the Nemotron `.nemo` checkpoint used by this package.

Priority:
  1. NEMOTRON_NEMO_PATH — explicit local path to the exact .nemo file
  2. Local cache under <package>/models/<filename> (or NEMOTRON_MODEL_CACHE_DIR)
  3. Download from Hugging Face using NEMOTRON_MODEL_REPO_ID
     (default: vedantahatti/nemotron-lid)

The required filename is fixed:
  indic_nemotron_v1_1_sft_600k_lr1-averaged-40k.nemo

No other checkpoint filename is accepted.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

NEMO_FILENAME = "indic_nemotron_v1_1_sft_600k_lr1-averaged-40k.nemo"
DEFAULT_REPO_ID = "vedantahatti/nemotron-lid"
# SHA256 of the exact packaged checkpoint (must match after download).
EXPECTED_NEMO_SHA256 = "58e85ea1bdcad81f1ebcb14b3e083ee3501c38b26b41356ea544f46d14f529ed"

_PKG_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CACHE = _PKG_ROOT / "models"


def _expected_filename() -> str:
    name = os.environ.get("NEMOTRON_MODEL_FILENAME", NEMO_FILENAME).strip()
    if name != NEMO_FILENAME:
        raise RuntimeError(
            f"Refusing NEMOTRON_MODEL_FILENAME={name!r}. "
            f"This package requires the exact file {NEMO_FILENAME!r}."
        )
    return NEMO_FILENAME


def _repo_id() -> str:
    return os.environ.get("NEMOTRON_MODEL_REPO_ID", DEFAULT_REPO_ID).strip() or DEFAULT_REPO_ID


def _cache_dir() -> Path:
    override = os.environ.get("NEMOTRON_MODEL_CACHE_DIR", "").strip()
    return Path(override) if override else _DEFAULT_CACHE


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _validate_local_nemo(path: Path, *, verify_hash: bool = True) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Nemotron checkpoint not found: {path}")
    if path.name != NEMO_FILENAME:
        raise RuntimeError(
            f"Refusing checkpoint {path.name!r}. "
            f"Expected exact filename {NEMO_FILENAME!r}."
        )
    if path.stat().st_size < 1_000_000_000:
        raise RuntimeError(
            f"Checkpoint looks too small ({path.stat().st_size} bytes): {path}. "
            f"Expected the full ~2.4 GB weights file."
        )
    if verify_hash:
        digest = sha256_file(path)
        if digest != EXPECTED_NEMO_SHA256:
            raise RuntimeError(
                "Checkpoint SHA256 mismatch.\n"
                f"  path    : {path}\n"
                f"  got     : {digest}\n"
                f"  expected: {EXPECTED_NEMO_SHA256}\n"
                "The file is not the checkpoint this package was validated against."
            )
    return path


def resolve_nemo_checkpoint(*, force_download: bool = False, verify_hash: bool = True) -> Path:
    """
    Return a local filesystem path to the required `.nemo` checkpoint.

    Raises RuntimeError with a clear message if the file cannot be obtained.
    """
    filename = _expected_filename()

    # 1) Explicit local override (must still be the exact filename + hash).
    explicit = os.environ.get("NEMOTRON_NEMO_PATH", "").strip()
    if explicit and not force_download:
        return _validate_local_nemo(Path(explicit), verify_hash=verify_hash)

    cache = _cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    local = cache / filename

    # 2) Cached copy
    if local.is_file() and not force_download:
        return _validate_local_nemo(local, verify_hash=verify_hash)

    # 3) Hugging Face download — only from the configured repo (no fallbacks).
    repo_id = _repo_id()
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or True

    try:
        from huggingface_hub import hf_hub_download
    except ImportError as e:
        raise RuntimeError(
            "huggingface_hub is required to download the Nemotron checkpoint. "
            "Install requirements.txt, then retry."
        ) from e

    print(f"[download] repo={repo_id}")
    print(f"[download] filename={filename}")
    print(f"[download] cache_dir={cache}")

    try:
        downloaded = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            local_dir=str(cache),
            token=token,
        )
    except Exception as e:
        raise RuntimeError(
            "Failed to download the Nemotron checkpoint.\n"
            f"  repo_id : {repo_id}\n"
            f"  filename: {filename}\n"
            f"  cache   : {cache}\n"
            "\n"
            "Checklist:\n"
            f"  1. Confirm {filename} exists in https://huggingface.co/{repo_id}\n"
            "  2. If the repo is private/gated, run `hf auth login` or export HF_TOKEN.\n"
            "  3. Or place the exact file locally and set NEMOTRON_NEMO_PATH.\n"
            "\n"
            "This package does not fall back to any other Hugging Face repository.\n"
            f"\nOriginal error: {type(e).__name__}: {e}"
        ) from e

    path = Path(downloaded)
    if path.name != filename:
        raise RuntimeError(
            f"Download returned unexpected file {path.name!r}; expected {filename!r}."
        )
    if not path.is_file():
        candidates = list(cache.rglob(filename))
        if not candidates:
            raise RuntimeError(
                f"Download finished but {filename} was not found under {cache}. "
                f"The Hugging Face repo may not contain the required checkpoint."
            )
        path = candidates[0]

    return _validate_local_nemo(path, verify_hash=verify_hash)
