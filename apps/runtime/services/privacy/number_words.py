"""Spoken numbers to digits, for PII redaction only.

Speech recognition writes numbers the way they were said, not as digits:
"nine eight seven six ...", "नौ आठ सात ...", "ಒಂಬತ್ತು ಎಂಟು ...". The Indic
Nemotron and Indic Transcribe checkpoints have an ``<|itn|>`` (inverse text
normalisation) token in their vocabulary, but it is untrained, so digits never
come back from the model itself (see ``model-server/stt/indic-transcribe``).

``normalise()`` rewrites runs of number words as digits so that the redaction
patterns can see them, and returns a map from every position in the rewritten
text back to the original text. The rewritten text is never stored or logged:
only the spans it finds are applied to the original text.

Covered:

- English, Hindi and Kannada: digits, teens, tens and their compounds
  ("ninety eight", "अट्ठानवे", "ತೊಂಬತ್ತೆಂಟು"), "double"/"triple", and years
  ("twenty twenty one", "two thousand five", "दो हज़ार इक्कीस").
- Marathi, Bengali, Gujarati, Punjabi, Odia, Tamil, Telugu and Malayalam:
  the digits zero to nine, the way phone numbers and IDs are usually read out.
- English ordinals ("fifteenth"), so dates like "fifteenth December" resolve.

Quantities are left alone: spoken numbers right before a quantity word
("hundred", "सौ", "लाख", "ನೂರು") or a unit ("rupees", "किलो", "ರೂಪಾಯಿ"), or right
after a currency word, are not rewritten, so prices never look like identifiers.

Digits written with commas are read the way they are meant: "9,876,543,210" and
"98,76,54,321" as one number, "9, 8, 7, 6" as digits read out one at a time.

Romanised Hindi ("ek do teen") is not covered: "do", "teen" and "char" are
common English words.
"""

from __future__ import annotations

import bisect
import re
import unicodedata
from dataclasses import dataclass
from itertools import pairwise

# --------------------------------------------------------------------------- #
# Lexicon
# --------------------------------------------------------------------------- #

_UNIT, _TEEN, _TENS, _PAIR = "unit", "teen", "tens", "pair"
_MULT, _OH, _ORDINAL, _THOUSAND, _AND = "mult", "oh", "ordinal", "thousand", "and"
_SCALE = "scale"

_NUKTAS = dict.fromkeys(map(ord, "\u093c\u09bc\u0a3c\u0abc\u0b3c\u0cbc"))
_JOINERS = dict.fromkeys(map(ord, "\u200c\u200d"))


def fold(word: str) -> str:
    """Spelling-insensitive key: NFC, casefolded, nukta and joiners removed.

    Devanagari chandrabindu is folded into anusvara, so "पाँच" and "पांच" match.
    """
    word = unicodedata.normalize("NFD", word).casefold()
    word = word.translate(_NUKTAS).translate(_JOINERS).replace("\u0901", "\u0902")
    return unicodedata.normalize("NFC", word)


_LEXICON: dict[str, tuple[str, int]] = {}


def _add(kind: str, value: int, *words: str) -> None:
    for word in words:
        _LEXICON[fold(word)] = (kind, value)


def _kind_for(value: int) -> str:
    if value < 10:
        return _UNIT
    if value < 20:
        return _TEEN
    return _TENS if value % 10 == 0 else _PAIR


# English
for _value, _word in enumerate(
    [
        "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
        "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
        "seventeen", "eighteen", "nineteen"
    ]
):
    _add(_kind_for(_value), _value, _word)
_add(_UNIT, 0, "nought", "naught")
for _value, _word in zip(
    range(20, 100, 10),
    ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"],
):
    _add(_TENS, _value, _word)
_add(_TENS, 40, "fourty")
_add(_MULT, 2, "double", "डबल", "ಡಬಲ್")
_add(_MULT, 3, "triple", "treble", "ट्रिपल", "ಟ್ರಿಪಲ್")
_add(_OH, 0, "oh", "o")
for _value, _word in enumerate(
    [
        "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth",
        "ninth", "tenth", "eleventh", "twelfth", "thirteenth", "fourteenth",
        "fifteenth", "sixteenth", "seventeenth", "eighteenth", "nineteenth", "twentieth"
    ],
    start=1,
):
    _add(_ORDINAL, _value, _word)
_add(_ORDINAL, 30, "thirtieth")
_add(_THOUSAND, 1000, "thousand", "हज़ार", "हजार", "ಸಾವಿರ", "ಸಾವಿರದ")
_add(_AND, 0, "and", "और", "ಮತ್ತು")
_add(
    _SCALE, 100, "hundred", "hundreds", "lakh", "lakhs", "lac", "crore", "crores", "dozen",
    "सौ", "लाख", "करोड़", "शंभर", "ನೂರು", "ಲಕ್ಷ", "ಕೋಟಿ",
)

# Words after a number that make it a quantity, never an identifier.
UNIT_WORDS = frozenset(
    fold(word)
    for word in (
        "rupees", "rupee", "rs", "inr", "paise", "kilo", "kilos", "kg", "kgs", "gram", "grams",
        "quintal", "quintals", "ton", "tons", "tonne", "tonnes", "litre", "litres", "liter",
        "liters", "acre", "acres", "hectare", "hectares", "bag", "bags", "percent", "km",
        "metre", "metres", "meter", "meters", "days", "months", "years", "minutes", "hours",
        "रुपये", "रुपए", "रुपया", "रुपयों", "रु", "पैसे", "किलो", "ग्राम", "क्विंटल", "टन",
        "लीटर", "एकड़", "एकर", "हेक्टेयर", "बोरी", "प्रतिशत", "दिन", "महीने", "साल",
        "ರೂಪಾಯಿ", "ರೂ", "ಕೆಜಿ", "ಕಿಲೋ", "ಕ್ವಿಂಟಾಲ್", "ಎಕರೆ", "ಲೀಟರ್", "ದಿನ", "ವರ್ಷ",
    )
)
# Words before a number that make it an amount.
CURRENCY_WORDS = frozenset(fold(word) for word in ("rs", "rupees", "inr", "रु", "रुपये", "ರೂ"))
_COMMA_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})*,\d{3}")
_COMMA_GAP = re.compile(r"\s*,\s*|\s+")

# Hindi, 0-99. Common spelling variants are listed; nukta and chandrabindu
# differences are already handled by fold().
_HINDI: dict[int, tuple[str, ...]] = {
    0: ("शून्य", "सुन्न", "ज़ीरो", "जीरो"), 1: ("एक",), 2: ("दो",), 3: ("तीन",),
    4: ("चार",), 5: ("पाँच", "पांच"), 6: ("छह", "छः", "छै"), 7: ("सात",),
    8: ("आठ",), 9: ("नौ",), 10: ("दस",), 11: ("ग्यारह",), 12: ("बारह",),
    13: ("तेरह",), 14: ("चौदह",), 15: ("पंद्रह", "पन्द्रह"), 16: ("सोलह",),
    17: ("सत्रह",), 18: ("अठारह",), 19: ("उन्नीस",), 20: ("बीस",),
    21: ("इक्कीस",), 22: ("बाईस",), 23: ("तेईस",), 24: ("चौबीस",),
    25: ("पच्चीस",), 26: ("छब्बीस",), 27: ("सत्ताईस", "सत्ताइस"),
    28: ("अट्ठाईस", "अठाईस"), 29: ("उनतीस", "उन्तीस"), 30: ("तीस",),
    31: ("इकतीस", "इकत्तीस"), 32: ("बत्तीस",), 33: ("तैंतीस", "तेंतीस", "तेतीस"),
    34: ("चौंतीस", "चौतीस"), 35: ("पैंतीस", "पैतीस"), 36: ("छत्तीस",),
    37: ("सैंतीस", "सैतीस"), 38: ("अड़तीस",), 39: ("उनतालीस", "उन्तालीस"),
    40: ("चालीस",), 41: ("इकतालीस",), 42: ("बयालीस", "बियालीस"),
    43: ("तैंतालीस", "तेंतालीस"), 44: ("चवालीस", "चौवालीस", "चौआलीस"),
    45: ("पैंतालीस", "पैतालीस"), 46: ("छियालीस", "छयालीस"),
    47: ("सैंतालीस", "सैतालीस"), 48: ("अड़तालीस",), 49: ("उनचास", "उनन्चास"),
    50: ("पचास",), 51: ("इक्यावन", "इक्कावन"), 52: ("बावन",),
    53: ("तिरपन", "तिरेपन"), 54: ("चौवन", "चौव्वन"), 55: ("पचपन",),
    56: ("छप्पन",), 57: ("सत्तावन", "सतावन"), 58: ("अट्ठावन", "अठावन"),
    59: ("उनसठ",), 60: ("साठ",), 61: ("इकसठ",), 62: ("बासठ",),
    63: ("तिरसठ", "तिरेसठ"), 64: ("चौंसठ", "चौसठ"), 65: ("पैंसठ", "पैसठ"),
    66: ("छियासठ",), 67: ("सड़सठ", "सरसठ"), 68: ("अड़सठ",), 69: ("उनहत्तर",),
    70: ("सत्तर",), 71: ("इकहत्तर",), 72: ("बहत्तर",), 73: ("तिहत्तर",),
    74: ("चौहत्तर",), 75: ("पचहत्तर",), 76: ("छिहत्तर", "छियत्तर"),
    77: ("सतहत्तर",), 78: ("अठहत्तर",), 79: ("उन्यासी", "उनासी", "उनयासी"),
    80: ("अस्सी",), 81: ("इक्यासी",), 82: ("बयासी", "बियासी"), 83: ("तिरासी",),
    84: ("चौरासी",), 85: ("पचासी",), 86: ("छियासी",), 87: ("सत्तासी",),
    88: ("अट्ठासी", "अठासी"), 89: ("नवासी",), 90: ("नब्बे",),
    91: ("इक्यानवे", "इक्यानबे"), 92: ("बानवे", "बानबे"), 93: ("तिरानवे", "तिरानबे"),
    94: ("चौरानवे", "चौरानबे"), 95: ("पचानवे", "पचानबे"), 96: ("छियानवे", "छियानबे"),
    97: ("सत्तानवे", "सत्तानबे"), 98: ("अट्ठानवे", "अट्ठानबे", "अठानवे"),
    99: ("निन्यानवे", "निन्यानबे"),
}
for _value, _words in _HINDI.items():
    _add(_kind_for(_value), _value, *_words)

# Kannada: digits, teens and tens, and the tens + digit compounds, which join
# with sandhi ("ಇಪ್ಪತ್ತು" + "ಒಂದು" -> "ಇಪ್ಪತ್ತೊಂದು").
_KANNADA_UNITS: dict[int, tuple[str, ...]] = {
    0: ("ಸೊನ್ನೆ", "ಸೊನ್ನಿ", "ಶೂನ್ಯ", "ಜೀರೋ", "ಝೀರೋ"), 1: ("ಒಂದು",), 2: ("ಎರಡು",),
    3: ("ಮೂರು",), 4: ("ನಾಲ್ಕು",), 5: ("ಐದು",), 6: ("ಆರು",), 7: ("ಏಳು",),
    8: ("ಎಂಟು",), 9: ("ಒಂಬತ್ತು", "ಒಂಭತ್ತು"),
}
_KANNADA_TEENS: dict[int, tuple[str, ...]] = {
    10: ("ಹತ್ತು",), 11: ("ಹನ್ನೊಂದು",), 12: ("ಹನ್ನೆರಡು",), 13: ("ಹದಿಮೂರು",),
    14: ("ಹದಿನಾಲ್ಕು",), 15: ("ಹದಿನೈದು",), 16: ("ಹದಿನಾರು",), 17: ("ಹದಿನೇಳು",),
    18: ("ಹದಿನೆಂಟು",), 19: ("ಹತ್ತೊಂಬತ್ತು", "ಹತ್ತೊಂಭತ್ತು"),
}
_KANNADA_TENS: dict[int, tuple[str, ...]] = {
    20: ("ಇಪ್ಪತ್ತು",), 30: ("ಮೂವತ್ತು",), 40: ("ನಲವತ್ತು", "ನಲ್ವತ್ತು"),
    50: ("ಐವತ್ತು",), 60: ("ಅರವತ್ತು",), 70: ("ಎಪ್ಪತ್ತು",),
    80: ("ಎಂಬತ್ತು", "ಎಂಭತ್ತು"), 90: ("ತೊಂಬತ್ತು", "ತೊಂಭತ್ತು"),
}
# Ending that replaces the final "ು" of a tens word for each digit.
_KANNADA_JOIN: dict[int, tuple[str, ...]] = {
    1: ("ೊಂದು",), 2: ("ೆರಡು",), 3: ("ಮೂರು",), 4: ("ನಾಲ್ಕು",), 5: ("ೈದು",),
    6: ("ಾರು",), 7: ("ೇಳು",), 8: ("ೆಂಟು",), 9: ("ೊಂಬತ್ತು", "ೊಂಭತ್ತು"),
}
for _table in (_KANNADA_UNITS, _KANNADA_TEENS, _KANNADA_TENS):
    for _value, _words in _table.items():
        _add(_kind_for(_value), _value, *_words)
for _tens, _words in _KANNADA_TENS.items():
    for _word in _words:
        for _unit, _endings in _KANNADA_JOIN.items():
            for _ending in _endings:
                _add(_PAIR, _tens + _unit, _word[:-1] + _ending)
            if _unit in (3, 4):
                # "ಇಪ್ಪತ್ಮೂರು" as well as "ಇಪ್ಪತ್ತಮೂರು".
                _add(_PAIR, _tens + _unit, _word[:-2] + _endings[0])

# Other supported Indic languages: digits zero to nine.
_OTHER_DIGITS: dict[str, tuple[tuple[str, ...], ...]] = {
    "marathi": (("शून्य",), ("एक",), ("दोन",), ("तीन",), ("चार",), ("पाच",),
                ("सहा",), ("सात",), ("आठ",), ("नऊ",)),
    "bengali": (("শূন্য",), ("এক",), ("দুই",), ("তিন",), ("চার",), ("পাঁচ",),
                ("ছয়", "ছয়"), ("সাত",), ("আট",), ("নয়", "নয়")),
    "gujarati": (("શૂન્ય",), ("એક",), ("બે",), ("ત્રણ",), ("ચાર",), ("પાંચ",),
                 ("છ",), ("સાત",), ("આઠ",), ("નવ",)),
    "punjabi": (("ਸਿਫ਼ਰ", "ਜ਼ੀਰੋ"), ("ਇੱਕ", "ਇਕ"), ("ਦੋ",), ("ਤਿੰਨ",), ("ਚਾਰ",),
                ("ਪੰਜ",), ("ਛੇ",), ("ਸੱਤ",), ("ਅੱਠ",), ("ਨੌਂ", "ਨੌ")),
    "odia": (("ଶୂନ", "ଶୂନ୍ୟ"), ("ଏକ",), ("ଦୁଇ",), ("ତିନି",), ("ଚାରି",),
             ("ପାଞ୍ଚ",), ("ଛଅ",), ("ସାତ",), ("ଆଠ",), ("ନଅ",)),
    "tamil": (("பூஜ்ஜியம்", "பூஜ்யம்", "சுழியம்"), ("ஒன்று", "ஒண்ணு"),
              ("இரண்டு", "ரெண்டு"), ("மூன்று", "மூணு"), ("நான்கு", "நாலு"),
              ("ஐந்து", "அஞ்சு"), ("ஆறு",), ("ஏழு",), ("எட்டு",), ("ஒன்பது",)),
    "telugu": (("సున్నా",), ("ఒకటి",), ("రెండు",), ("మూడు",), ("నాలుగు",),
               ("ఐదు",), ("ఆరు",), ("ఏడు",), ("ఎనిమిది",), ("తొమ్మిది",)),
    "malayalam": (("പൂജ്യം",), ("ഒന്ന്",), ("രണ്ട്",), ("മൂന്ന്",), ("നാല്",),
                  ("അഞ്ച്",), ("ആറ്",), ("ഏഴ്",), ("എട്ട്",), ("ഒൻപത്", "ഒമ്പത്")),
}
for _digits in _OTHER_DIGITS.values():
    for _value, _words in enumerate(_digits):
        for _word in _words:
            _LEXICON.setdefault(fold(_word), (_UNIT, _value))
_add(_TEEN, 10, "दहा")

# --------------------------------------------------------------------------- #
# Tokenising
# --------------------------------------------------------------------------- #

# A word is letters plus the combining marks Indic scripts need (vowel signs,
# virama, anusvara), which Python's \w does not include. Danda (U+0964/5) is
# punctuation. Indic digits are already ASCII by the time this runs.
WORD_CHAR = r"[^\W\d_]|[\u0900-\u0963\u0966-\u0d7f\u200c\u200d]"
WORD = rf"(?:{WORD_CHAR})+"
_TOKEN = re.compile(rf"(?P<word>{WORD})|(?P<digits>\d+)")
# Between two number tokens of one run: spaces, commas, hyphens, full stops.
_JOINABLE_GAP = re.compile(r"[ \t,.\-–]*")


@dataclass(frozen=True)
class _Token:
    start: int
    end: int
    kind: str  # one of the lexicon kinds, "digits", or "" for an ordinary word
    value: int
    text: str


@dataclass(frozen=True)
class Group:
    """One number as written in the rewritten text, e.g. "98" or "2021"."""

    digits: str
    start: int  # span in the original text
    end: int
    year: bool = False  # built from "twenty twenty one", "two thousand five", ...


@dataclass(frozen=True)
class Run:
    """Consecutive number words (and digits said between them) read as one number."""

    groups: tuple[Group, ...]
    start: int  # span in the original text
    end: int
    norm_start: int  # span in the rewritten text
    norm_end: int

    @property
    def digits(self) -> str:
        return "".join(group.digits for group in self.groups)

    @property
    def digit_by_digit(self) -> bool:
        return all(len(group.digits) == 1 for group in self.groups)

    @property
    def years(self) -> int:
        return sum(group.year for group in self.groups)


@dataclass(frozen=True)
class _Segment:
    norm_start: int
    norm_end: int
    start: int
    end: int
    verbatim: bool


@dataclass
class Normalised:
    """Rewritten text plus the map back to the original text."""

    text: str
    runs: list[Run]
    _segments: list[_Segment]
    _starts: list[int]

    def span(self, start: int, end: int) -> tuple[int, int]:
        """Original-text span covering the rewritten-text span ``[start, end)``."""
        return self._map(start, is_end=False), self._map(end, is_end=True)

    def _map(self, position: int, *, is_end: bool) -> int:
        probe = position - 1 if is_end else position
        index = max(0, bisect.bisect_right(self._starts, probe) - 1)
        segment = self._segments[index]
        if segment.verbatim:
            return segment.start + (position - segment.norm_start)
        return segment.end if is_end else segment.start


def _joinable(text: str, left: _Token, right: _Token) -> bool:
    return _JOINABLE_GAP.fullmatch(text, left.end, right.start) is not None


def _tokens(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    for match in _TOKEN.finditer(text):
        if match.group("digits"):
            token = _Token(match.start(), match.end(), "digits", 0, match.group())
        else:
            kind, value = _LEXICON.get(fold(match.group()), ("", 0))
            token = _Token(match.start(), match.end(), kind, value, match.group())
        # "twenty first" is one ordinal, 21st.
        previous = tokens[-1] if tokens else None
        if (
            previous is not None
            and token.kind == _ORDINAL
            and token.value < 10
            and previous.kind == _TENS
            and _joinable(text, previous, token)
        ):
            tokens.pop()
            token = _Token(previous.start, token.end, _ORDINAL, previous.value + token.value,
                           text[previous.start:token.end])
        tokens.append(token)
    return tokens


def _two_digit(tokens: list[_Token], index: int) -> tuple[int, int] | None:
    """Value 10-99 starting at ``tokens[index]`` and how many tokens it uses."""
    if index >= len(tokens):
        return None
    token = tokens[index]
    if token.kind in (_TEEN, _PAIR):
        return token.value, 1
    if token.kind == _TENS:
        nxt = tokens[index + 1] if index + 1 < len(tokens) else None
        if nxt is not None and nxt.kind == _UNIT and nxt.value > 0:
            return token.value + nxt.value, 2
        return token.value, 1
    if token.kind == "digits" and len(token.text) == 2:
        return int(token.text), 1
    return None


def _parse_run(tokens: list[_Token]) -> list[Group]:
    """Turn the tokens of one run into digit groups."""
    groups: list[Group] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        nxt = tokens[index + 1] if index + 1 < len(tokens) else None

        if token.kind == "digits":
            groups.append(Group(token.text, token.start, token.end))
            index += 1
            continue

        if token.kind == _MULT:
            if nxt is not None and (
                nxt.kind == _UNIT or (nxt.kind == "digits" and len(nxt.text) == 1)
            ):
                digit = str(nxt.value) if nxt.kind == _UNIT else nxt.text
                for _ in range(token.value):
                    groups.append(Group(digit, token.start, nxt.end))
                index += 2
            else:
                index += 1
            continue

        if token.kind == _OH:
            groups.append(Group("0", token.start, token.end))
            index += 1
            continue

        if token.kind == _UNIT:
            # "two thousand", "two thousand (and) twenty one" -> a year.
            if token.value == 2 and nxt is not None and nxt.kind == _THOUSAND:
                rest_at = index + 2
                if rest_at < len(tokens) and tokens[rest_at].kind == _AND:
                    rest_at += 1
                tail = _two_digit(tokens, rest_at)
                if tail is None and rest_at < len(tokens) and tokens[rest_at].kind == _UNIT:
                    tail = (tokens[rest_at].value, 1)
                if tail is not None:
                    value, used = tail
                    end = tokens[rest_at + used - 1].end
                    groups.append(Group(f"20{value:02d}", token.start, end, year=True))
                    index = rest_at + used
                else:
                    groups.append(Group("2000", token.start, nxt.end, year=True))
                    index += 2
                continue
            groups.append(Group(str(token.value), token.start, token.end))
            index += 1
            continue

        # Teens, tens and two-digit compounds.
        head = _two_digit(tokens, index)
        if head is None:
            index += 1
            continue
        value, used = head
        end = tokens[index + used - 1].end
        after = index + used
        # "nineteen eighty six", "twenty twenty one", "twenty oh five" -> a year.
        if value in (19, 20):
            year = _two_digit(tokens, after)
            if year is not None and year[0] >= 10:
                year_value, year_used = year
                groups.append(Group(f"{value}{year_value:02d}", token.start,
                                    tokens[after + year_used - 1].end, year=True))
                index = after + year_used
                continue
            if (
                after + 1 < len(tokens)
                and tokens[after].kind == _OH
                and tokens[after + 1].kind == _UNIT
            ):
                groups.append(Group(f"{value}0{tokens[after + 1].value}", token.start,
                                    tokens[after + 1].end, year=True))
                index = after + 2
                continue
        groups.append(Group(str(value), token.start, end))
        index = after
    return groups


def _is_number(token: _Token) -> bool:
    return token.kind in (_UNIT, _TEEN, _TENS, _PAIR, _MULT, "digits")


def _split_runs(text: str, tokens: list[_Token]) -> list[tuple[list[_Token], int]]:
    """Group number tokens that follow each other with only separators between.

    Returns each run with the index of the token after it.
    """
    runs: list[tuple[list[_Token], int]] = []
    current: list[_Token] = []
    position = 0

    def close() -> None:
        # A run never ends on a connective ("... five oh", "two thousand and").
        while current and current[-1].kind in (_OH, _AND):
            current.pop()
        if current:
            runs.append((list(current), tokens.index(current[-1], position) + 1))
        current.clear()

    for index, token in enumerate(tokens):
        if not current:
            position = index
        joinable = bool(current) and _joinable(text, current[-1], token)
        nxt = tokens[index + 1] if index + 1 < len(tokens) else None
        if _is_number(token):
            if current and not joinable:
                close()
            current.append(token)
            continue
        if current and joinable:
            last = current[-1]
            # "oh" only between number words: "nine oh eight".
            if token.kind == _OH and nxt is not None and _is_number(nxt):
                current.append(token)
                continue
            # "thousand" only in years: "two thousand (and) five".
            if token.kind == _THOUSAND and last.kind == _UNIT and last.value == 2:
                current.append(token)
                continue
            if token.kind == _AND and last.kind == _THOUSAND and nxt is not None and _is_number(nxt):
                current.append(token)
                continue
        close()
    close()
    return runs


def _is_quantity(text: str, tokens: list[_Token], run: list[_Token], after: int) -> bool:
    """A spoken amount: before a quantity word or unit, or after a currency word."""
    nxt = tokens[after] if after < len(tokens) else None
    if (
        nxt is not None
        and _joinable(text, run[-1], nxt)
        and (nxt.kind in (_SCALE, _THOUSAND) or fold(nxt.text) in UNIT_WORDS)
    ):
        return True
    if text[run[-1].end :].lstrip().startswith("%"):
        return True
    before = text[: run[0].start].rstrip()
    if before.endswith("\u20b9"):
        return True
    previous = [token for token in tokens if token.end <= run[0].start]
    if previous and fold(previous[-1].text) in CURRENCY_WORDS and _joinable(text, previous[-1], run[0]):
        return True
    # "two thousand four hundred": the year reading would be wrong.
    return any(token.kind == _THOUSAND for token in run) and nxt is not None and nxt.kind == _SCALE


def _typed_groups(text: str, run: list[_Token]) -> list[Group] | None:
    """Digits written with commas: one number ("9,876,543,210"), or pieces said one by one."""
    if len(run) < 2:
        return None
    span = text[run[0].start : run[-1].end]
    if _COMMA_NUMBER.fullmatch(span):
        return [Group("".join(token.text for token in run), run[0].start, run[-1].end)]
    gaps = [text[a.end : b.start] for a, b in pairwise(run)]
    # "9, 8, 7, 6" or "98, 76, 54, 32, 10": each piece said on its own.
    if (
        all(len(token.text) <= 5 for token in run)
        and any("," in gap for gap in gaps)
        and all(_COMMA_GAP.fullmatch(gap) for gap in gaps)
    ):
        return [Group(token.text, token.start, token.end) for token in run]
    return None


def normalise(text: str) -> Normalised:
    """Rewrite number words in ``text`` as digits (digits from one word per group)."""
    tokens = _tokens(text)
    pieces: list[str] = []
    segments: list[_Segment] = []
    position = 0  # in the original text
    norm_length = 0
    runs: list[Run] = []

    def emit(piece: str, start: int, end: int, *, verbatim: bool) -> None:
        nonlocal norm_length
        if not piece:
            return
        segments.append(_Segment(norm_length, norm_length + len(piece), start, end, verbatim))
        pieces.append(piece)
        norm_length += len(piece)

    replacements: list[tuple[int, int, list[Group] | str, bool]] = []
    for run_tokens, after in _split_runs(text, tokens):
        first, last = run_tokens[0], run_tokens[-1]
        if all(token.kind == "digits" for token in run_tokens):
            groups = _typed_groups(text, run_tokens)
            if groups:
                replacements.append((first.start, last.end, groups, False))
            continue
        if _is_quantity(text, tokens, run_tokens, after):
            continue
        groups = _parse_run(run_tokens)
        if groups:
            replacements.append((groups[0].start, groups[-1].end, groups, True))
    # Ordinals outside runs become "15th" so dates like "15th December" resolve.
    taken = [(start, end) for start, end, _, _ in replacements]
    for token in tokens:
        if token.kind == _ORDINAL and not any(s <= token.start < e for s, e in taken):
            replacements.append((token.start, token.end, f"{token.value}th", False))
    replacements.sort(key=lambda item: item[0])

    for start, end, replacement, is_word_run in replacements:
        emit(text[position:start], position, start, verbatim=True)
        if isinstance(replacement, str):
            emit(replacement, start, end, verbatim=False)
        else:
            norm_start = norm_length
            previous_end = start
            for index, group in enumerate(replacement):
                if index:
                    gap_start, gap_end = sorted((previous_end, group.start))
                    emit(" ", gap_start, gap_end, verbatim=False)
                emit(group.digits, group.start, group.end, verbatim=False)
                previous_end = group.end
            if is_word_run:
                runs.append(Run(tuple(replacement), start, end, norm_start, norm_length))
        position = end
    emit(text[position:], position, len(text), verbatim=True)
    if not segments:
        segments.append(_Segment(0, 0, 0, 0, True))

    return Normalised("".join(pieces), runs, segments, [s.norm_start for s in segments])
