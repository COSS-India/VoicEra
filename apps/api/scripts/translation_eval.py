"""Live check of transcript translation against QA's reported mistranslations.

Sends one real transcript through translate_transcript() using the org's
configured LLM provider (costs one completion per run) and checks each line
for the expected English. Unit tests only check the prompt text; this checks
what the model actually returns.

    docker exec -w /app -e ORG_ID=<org_id> voicera_oss_api python scripts/translation_eval.py
"""

import os
import sys

from app.services.translation_service import translate_transcript

TRANSCRIPT = """call_id=eval
---
[2026-10-19T09:00:00.000+00:00] assistant: Namaste, VoicEra se bol raha hoon
[2026-10-19T09:00:05.000+00:00] user: हलो नमस्ते
[2026-10-19T09:00:08.000+00:00] assistant: जी, कृपया बताएं कि मैं आपकी क्या मदद कर सकता हूँ।
[2026-10-19T09:00:12.000+00:00] user: जैसे कि
[2026-10-19T09:00:15.000+00:00] user: मेरा नंबर नौ आठ सात पाँच चार तीन दो एकहैमेरा
[2026-10-19T09:00:18.000+00:00] user: मेरा नंबर नौ आठ सात पाँच चार तीन दो एक है मेरा
[2026-10-19T09:00:20.000+00:00] user: मेरा दिमाग खराब हो गया है
[2026-10-19T09:00:25.000+00:00] user: ठीक है धन्यवाद हाँ हाँ"""

# (must contain any of, must not contain any of) per translated line, lowercase.
EXPECTED = [
    (["this is voicera"], ["speaking to", "speaking with"]),
    (["namaste"], ["hello hello"]),
    (["sure", "yes"], ["gee"]),
    (["like what"], ["such as"]),
    (["9, 8, 7, 5, 4, 3, 2, 1"], ["mine", "1 my", "1, my"]),
    (["9, 8, 7, 5, 4, 3, 2, 1"], ["mine", "1 my", "1, my"]),
    (["frustrat"], ["out of my mind"]),
    (["yes, yes"], []),
]


def main() -> int:
    result = translate_transcript(TRANSCRIPT, "en", os.environ["ORG_ID"])
    lines = [line for line in result.split("\n") if line.startswith("[")]
    assert len(lines) == len(EXPECTED), result
    failed = 0
    for line, (want_any, want_none) in zip(lines, EXPECTED):
        text = line.lower()
        ok = any(w in text for w in want_any) and not any(w in text for w in want_none)
        failed += not ok
        print(("PASS " if ok else "FAIL ") + line)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
