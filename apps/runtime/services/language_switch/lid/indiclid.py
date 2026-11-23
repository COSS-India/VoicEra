"""Client for the deployed AI4Bharat IndicLID text service (``POST /predict``).

The service runs the native-script FTN model. For each text it returns scores
for kn/hi/mr/ta/te plus the mass on every other class (``other_languages_mass``)
and the overall top label. Text that is more than 50% Latin is rejected with
HTTP 400 for the whole batch, so such texts are filtered out locally first.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

import httpx
from loguru import logger

# Unicode blocks of the scripts the five target languages are written in.
_SCRIPT_RANGES = (
    ("Deva", 0x0900, 0x097F),
    ("Taml", 0x0B80, 0x0BFF),
    ("Telu", 0x0C00, 0x0C7F),
    ("Knda", 0x0C80, 0x0CFF),
)
# Same routing threshold as the service: more Latin than this is rejected.
_LATIN_REJECT_THRESHOLD = 0.5


def script_of(text: str) -> str:
    """Dominant script of ``text``: Deva, Knda, Taml, Telu, Latn, or ``other``."""
    counts: Counter[str] = Counter()
    for char in text:
        if not char.isalpha():
            continue
        code = ord(char)
        if code < 0x80:
            counts["Latn"] += 1
            continue
        for name, low, high in _SCRIPT_RANGES:
            if low <= code <= high:
                counts[name] += 1
                break
        else:
            counts["other"] += 1
    return counts.most_common(1)[0][0] if counts else "other"


def latin_fraction(text: str) -> float:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for char in letters if char.isascii()) / len(letters)


@dataclass(frozen=True)
class TextEvidence:
    """IndicLID scores for one transcript."""

    text: str
    script: str
    scores: dict[str, float] = field(default_factory=dict)  # kn/hi/mr/ta/te
    other_mass: float = 0.0
    top_label: str = ""
    top_score: float = 0.0


class IndicLidClient:
    """Score transcripts with one batched ``/predict`` call."""

    def __init__(self, base_url: str, *, timeout_s: float = 1.5) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_s)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def score(self, texts: Sequence[str]) -> list[TextEvidence | None]:
        """Return evidence aligned with ``texts``.

        Entries are ``None`` for empty or Latin-dominant texts, and every entry
        is ``None`` when the service fails, times out or answers malformed JSON.
        """
        out: list[TextEvidence | None] = [None] * len(texts)
        cleaned = {
            index: " ".join(text.split())
            for index, text in enumerate(texts)
            if text.strip() and latin_fraction(text) <= _LATIN_REJECT_THRESHOLD
        }
        if not cleaned:
            return out
        try:
            client = await self._get_client()
            response = await client.post(
                f"{self._base_url}/predict",
                json={"texts": list(cleaned.values())},
            )
            response.raise_for_status()
            results = response.json()["results"]
            if len(results) != len(cleaned):
                raise ValueError(f"expected {len(cleaned)} results, got {len(results)}")
            for index, result in zip(cleaned, results, strict=True):
                out[index] = TextEvidence(
                    text=texts[index].strip(),
                    script=script_of(texts[index]),
                    scores={r["lang"]: float(r["score"]) for r in result["ranking"]},
                    other_mass=float(result["other_languages_mass"]),
                    top_label=str(result["top_overall_label"]),
                    top_score=float(result["top_overall_score"]),
                )
        except Exception as exc:
            logger.warning("IndicLID predict failed: {}", exc)
            return [None] * len(texts)
        return out

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
