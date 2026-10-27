"""Live check of transcript translation against QA's reported mistranslations.

Sends two real transcripts (prompt examples + held-out) through translate_transcript() using the org's
configured LLM provider (costs two completions per run) and checks each line
for the expected English. Unit tests only check the prompt text; this checks
what the model actually returns.

    docker exec -w /app -e PYTHONPATH=/app -e ORG_ID=<org_id> voicera_oss_api python scripts/translation_eval.py
"""

import os
import sys

from app.services.translation_service import _SYSTEM_PROMPT, translate_transcript

PROMPT_EXAMPLES = """call_id=eval
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
PROMPT_EXAMPLES_EXPECTED = [
    (["i am speaking from voicera"], ["this is", "speaking to", "speaking with"]),
    (["hello"], ["hello, hello", "hello hello", "namaste"]),
    (["sure", "yes"], ["gee"]),
    (["like what"], ["such as"]),
    (["9, 8, 7, 5, 4, 3, 2, 1"], ["mine", "1 my", "1, my"]),
    (["9, 8, 7, 5, 4, 3, 2, 1"], ["mine", "1 my", "1, my"]),
    (["frustrat"], ["out of my mind"]),
    (["yes, yes"], []),
]

# Same QA failure classes, but no source line appears in the system prompt —
# passing PROMPT_EXAMPLES alone only shows the model can copy its examples.
HELD_OUT = """call_id=eval-held-out
---
[2026-10-20T11:00:00.000+00:00] assistant: Namaste, KisanMitra se bol rahi hoon
[2026-10-20T11:00:02.000+00:00] user: हैलो नमस्कार
[2026-10-20T11:00:04.000+00:00] user: जी हाँ, बोलिए
[2026-10-20T11:00:08.000+00:00] user: मेरा नंबर छह शून्य चार दो पाँच है मेरा
[2026-10-20T11:00:12.000+00:00] user: छह शून्य चार दोहैमेरा
[2026-10-20T11:00:16.000+00:00] user: इन लोगों ने तो नाक में दम कर दिया है
[2026-10-20T11:00:20.000+00:00] user: नहीं नहीं, अभी नहीं"""

HELD_OUT_EXPECTED = [
    (["i am speaking from kisanmitra"], ["this is", "speaking to", "speaking with"]),
    (["hello"], ["hello, hello", "hello hello"]),
    (["yes"], ["gee"]),
    (["6, 0, 4, 2, 5"], ["mine", "5 my", "5, my"]),
    (["6, 0, 4, 2"], ["mine", "2 my", "2, my"]),
    (["annoy", "fed up", "harass", "pester", "sick of", "trouble", "fed-up", "miserable", "difficult", "hell"], ["nose"]),
    (["no, no"], []),
]


def run(name: str, transcript: str, expected: list, org_id: str) -> int:
    result = translate_transcript(transcript, "en", org_id)
    lines = [line for line in result.split("\n") if line.startswith("[")]
    assert len(lines) == len(expected), result
    failed = 0
    for line, (want_any, want_none) in zip(lines, expected):
        text = line.lower()
        ok = any(w in text for w in want_any) and not any(w in text for w in want_none)
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'} [{name}] {line}")
    return failed


def main() -> int:
    for line in HELD_OUT.split("\n")[2:]:
        content = line.split(": ", 1)[1]
        assert content not in _SYSTEM_PROMPT, f"held-out line leaked into prompt: {content}"
    org_id = os.environ["ORG_ID"]
    failed = run("prompt-examples", PROMPT_EXAMPLES, PROMPT_EXAMPLES_EXPECTED, org_id)
    failed += run("held-out", HELD_OUT, HELD_OUT_EXPECTED, org_id)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
