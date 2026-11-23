"""LanguageJudge: evidence combination, thresholds and text selection.

Score fixtures mirror what the live IndicLID service returned for the same
kind of text (see ``test_indiclid_live.py``): native kn/ta/te script ~1.0,
Marathi in Devanagari ~1.0, Hindi often on ``mai_Deva``, and Dravidian speech
written in Devanagari with no kn/ta/te signal.
"""

from __future__ import annotations

from apps.runtime.services.language_switch.lid.indiclid import TextEvidence, script_of
from apps.runtime.services.language_switch.lid.judge import LanguageJudge

KN = "ನಮಸ್ಕಾರ ನೀವು ಹೇಗಿದ್ದೀರಿ"
KN_DEVA = "नमस्कार निवु हेगिद्दीरी"
TA = "வணக்கம் நீங்கள் எப்படி இருக்கிறீர்கள்"
TE = "నమస్కారం మీరు ఎలా ఉన్నారు"
HI = "मुझे अपने खाते की जानकारी चाहिए"
MR = "मला माझ्या खात्याची माहिती हवी आहे"


def ev(text: str, **scores: float) -> TextEvidence:
    full = {lang: scores.get(lang, 0.0) for lang in ("kn", "hi", "mr", "ta", "te")}
    return TextEvidence(
        text=text,
        script=script_of(text),
        scores=full,
        other_mass=max(0.0, 1.0 - sum(full.values())),
    )


def judge(active: str, allowed=("kn", "hi", "mr", "ta", "te"), **kw) -> LanguageJudge:
    return LanguageJudge(allowed_languages=allowed, active_language=active, **kw)


# ---- the cases from the task ------------------------------------------------


def test_kannada_main_with_devanagari_nemotron_stays_kannada():
    j = judge("kn")
    d = j.decide(ev(KN, kn=1.0), ev(KN_DEVA, mr=0.572, hi=0.022))
    assert d.outcome == "stay" and d.language == "kn"
    assert d.reason == "weak_evidence"
    assert d.scores["mr"] < 0.8 and d.scores["kn"] == 0.0  # main kn vote ignored
    assert d.text == KN and d.text_source == "main"


def test_devanagari_is_never_read_as_kannada():
    d = judge("hi").decide(ev(HI, hi=1.0), ev(KN_DEVA))
    assert d.scores["kn"] == 0.0 and d.outcome == "stay"


def test_hindi_active_kannada_speech_switches_to_kannada_with_nemotron_text():
    d = judge("hi").decide(ev("आप कैसे हैं नमस्ते"), ev(KN, kn=1.0))
    assert (d.outcome, d.language, d.text, d.text_source) == ("switch", "kn", KN, "nemotron")
    assert d.scores["kn"] == 1.0


def test_kannada_active_marathi_speech_switches_to_marathi():
    d = judge("kn").decide(ev(KN), ev(MR, mr=1.0))
    assert (d.outcome, d.language, d.text_source) == ("switch", "mr", "nemotron")


def test_tamil_and_telugu_from_nemotron_switch():
    assert judge("hi").decide(None, ev(TA, ta=1.0)).language == "ta"
    assert judge("kn").decide(None, ev(TE, te=1.0)).language == "te"


def test_kannada_active_hindi_speech_needs_hindi_evidence():
    # Real Hindi often scores 0 for hi (mass on Maithili): stay, retry next turn.
    assert judge("kn").decide(ev(KN), ev(HI, hi=0.0)).reason == "no_evidence"
    assert judge("kn").decide(ev(KN), ev(HI, hi=0.81)).language == "hi"


# ---- combining both transcripts ---------------------------------------------


def test_main_hindi_vote_conflicts_with_nemotron_marathi():
    d = judge("hi").decide(ev(HI, hi=1.0), ev(MR, mr=1.0))
    assert d.outcome == "stay" and d.reason == "conflict"


def test_weak_main_hindi_does_not_block_confident_marathi():
    d = judge("hi").decide(ev(HI, hi=0.2), ev(MR, mr=1.0))
    assert d.outcome == "switch" and d.language == "mr"


def test_both_transcripts_agreeing_sum_their_evidence():
    d = judge("hi").decide(ev(MR, mr=0.5), ev(MR, mr=0.5))
    assert d.scores["mr"] == 1.0 and d.language == "mr"


def test_same_language_stays():
    d = judge("hi").decide(ev(HI, hi=1.0), ev(HI, hi=1.0))
    assert d.outcome == "stay" and d.reason == "no_evidence"


def test_main_only_marathi_evidence_switches_hindi_agent():
    d = judge("hi").decide(ev(MR, mr=1.0), None)
    assert d.outcome == "switch" and d.language == "mr" and d.text_source == "main"


def test_nemotron_only_when_main_is_missing():
    d = judge("hi").decide(None, ev(KN, kn=1.0))
    assert d.language == "kn" and d.text == KN


# ---- empties, short text, candidate filtering ------------------------------


def test_no_text_stays():
    d = judge("kn").decide(None, None)
    assert (d.outcome, d.reason) == ("stay", "no_text")


def test_non_target_active_language_can_switch_out():
    # English agent: Latin text is never scored, Nemotron's Hindi can still win.
    d = judge("en", allowed=("en", "hi")).decide(None, ev(HI, hi=1.0))
    assert d.outcome == "switch" and d.language == "hi"


def test_languages_outside_the_agent_are_never_selected():
    d = judge("hi", allowed=("hi", "kn")).decide(None, ev(MR, mr=1.0))
    assert d.outcome == "stay" and "mr" not in d.scores


def test_region_suffixed_codes_are_normalised():
    d = judge("hi-IN", allowed=("hi-IN", "kn-IN")).decide(None, ev(KN, kn=1.0))
    assert d.language == "kn"


def test_usable_enforces_min_words():
    j = judge("hi", min_words=3)
    assert j.usable("हाँ") == "" and j.usable("हाँ ठीक है") == "हाँ ठीक है"
    assert j.usable("   ") == ""


# ---- cooldown and state ------------------------------------------------------


def test_switch_updates_active_and_cooldown_blocks_next_switch():
    j = judge("hi", cooldown_sec=3.0)
    assert j.decide(None, ev(KN, kn=1.0), now=100.0).outcome == "switch"
    assert j.active_language == "kn"
    d = j.decide(None, ev(TA, ta=1.0), now=101.0)
    assert (d.outcome, d.reason, j.active_language) == ("stay", "cooldown", "kn")
    assert j.decide(None, ev(TA, ta=1.0), now=104.0).language == "ta"


# ---- which transcript the LLM sees ------------------------------------------


def test_text_source_prefers_higher_score_when_both_match_script():
    d = judge("hi").decide(ev(MR, mr=0.95), ev(MR, mr=0.85))
    assert d.language == "mr" and d.text_source == "main"
    d = judge("hi").decide(ev(MR, mr=0.85), ev(MR, mr=0.95))
    assert d.text_source == "nemotron"


def test_text_source_tie_goes_to_nemotron():
    assert judge("hi").decide(ev(MR, mr=0.9), ev(MR, mr=0.9)).text_source == "nemotron"


def test_decision_carries_supporting_evidence():
    main, nem = ev(KN), ev(MR, mr=1.0)
    d = judge("kn").decide(main, nem)
    assert d.evidence == {"main": main, "nemotron": nem}
    assert d.scores["mr"] == 1.0


def test_switch_records_the_language_being_left():
    j = judge("hi")
    d = j.decide(ev(HI), ev(KN, kn=1.0), now=100.0)
    assert d.outcome == "switch" and d.language == "kn"
    assert d.previous_language == "hi"
    # The next switch leaves kn, not the original language.
    d2 = j.decide(ev(KN), ev(MR, mr=2.0), now=200.0)
    assert d2.outcome == "switch" and d2.language == "mr"
    assert d2.previous_language == "kn"


def test_previous_language_is_normalised_and_unset_on_stay():
    d = judge("Hi-IN").decide(ev(HI, hi=1.0), ev(HI, hi=1.0))
    assert d.outcome == "stay" and d.previous_language == ""
    d = judge("Hi-IN").decide(ev(HI), ev(KN, kn=1.0))
    assert d.previous_language == "hi"
