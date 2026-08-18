"""Amount word parsers for 8 Indic scripts (non-Devanagari).

Devanagari (Hindi/Marathi) is handled by amount_words_parser.parse_hindi_amount_words().
This module provides parsers for: Tamil, Telugu, Kannada, Malayalam,
Gujarati, Bengali, Punjabi (Gurmukhi), Odia.

Algorithm (shared across all languages):
  1. Split amount-words text into tokens.
  2. Remove noise tokens (currency names, "only", etc.).
  3. Walk tokens left-to-right:
       - number token  → accumulate into `current`
       - scale token   → total += current * scale; current = 0
       - direct_value  → total += value directly (for compounds like "fifty-thousand")
       - unknown token → return None (undecidable)
  4. total += any remaining `current` (e.g. trailing rupee amount without scale).

Note on vocabulary coverage:
  Dictionaries cover ones (1–19), tens (20–90), common compounds at 5-unit
  boundaries (25, 35, 45, 55, 65, 75, 85, 95), and key one-offs needed for
  RBI-range amounts (₹1L–₹5Cr). Native-speaker review recommended before
  extending beyond common cheque denominations.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# ─────────────────────────────────────────────────────────────────────────────
#  Generic parser engine
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _LangConfig:
    number_words:  dict[str, int]        # word → value (additive before scale)
    scale_words:   dict[str, int]        # word → multiplier
    direct_values: dict[str, int]        # compound word → absolute value
    noise_tokens:  frozenset[str]


def _parse(words: str, cfg: _LangConfig) -> float | None:
    tokens = words.split()
    filtered = [t for t in tokens if t not in cfg.noise_tokens]
    if not filtered:
        return None

    total = 0.0
    current = 0.0
    for token in filtered:
        if token in cfg.direct_values:
            total += cfg.direct_values[token]
        elif token in cfg.scale_words:
            scale = cfg.scale_words[token]
            if current == 0:
                current = 1  # bare "lakh" = 1 lakh
            total += current * scale
            current = 0.0
        elif token in cfg.number_words:
            current += cfg.number_words[token]
        else:
            return None  # unknown token after noise filtering → undecidable
    total += current
    return total if total > 0 else None


# ─────────────────────────────────────────────────────────────────────────────
#  TAMIL (ta)
# ─────────────────────────────────────────────────────────────────────────────

_TAMIL = _LangConfig(
    number_words={
        # Ones
        "ஒன்று": 1,  "ஒரு": 1,
        "இரண்டு": 2, "இரு": 2,
        "மூன்று": 3,  "மூ": 3,
        "நான்கு": 4,
        "ஐந்து": 5,  "ஐ": 5,
        "ஆறு": 6,
        "ஏழு": 7,
        "எட்டு": 8,
        "ஒன்பது": 9,
        # Teens
        "பத்து": 10,
        "பதினொன்று": 11,
        "பன்னிரண்டு": 12,
        "பதின்மூன்று": 13,
        "பதினான்கு": 14,
        "பதினைந்து": 15,
        "பதினாறு": 16,
        "பதினேழு": 17,
        "பதினெட்டு": 18,
        "பத்தொன்பது": 19,
        # Tens
        "இருபது": 20,
        "முப்பது": 30,
        "நாற்பது": 40,
        "ஐம்பது": 50,
        "அறுபது": 60,
        "எழுபது": 70,
        "எண்பது": 80,
        "தொண்ணூறு": 90,
        # Compound tens+fives (common on cheques)
        "இருபத்தைந்து": 25,
        "முப்பத்தைந்து": 35,
        "நாற்பத்தைந்து": 45,
        "ஐம்பத்தைந்து": 55,
        "அறுபத்தைந்து": 65,
        "எழுபத்தைந்து": 75,
        "எண்பத்தைந்து": 85,
        "தொண்ணூற்றைந்து": 95,
        # Other useful compounds
        "இருபத்தொன்று": 21, "இருபத்திரண்டு": 22,
        "முப்பத்தொன்று": 31, "நாற்பத்தொன்று": 41,
        "ஐம்பத்தொன்று": 51, "அறுபத்தொன்று": 61,
        "எழுபத்தொன்று": 71, "எண்பத்தொன்று": 81,
        "தொண்ணூற்றொன்று": 91, "தொண்ணூற்றொன்பது": 99,
    },
    scale_words={
        "நூறு": 100,
        "ஆயிரம்": 1_000,
        "லட்சம்": 1_00_000,
        "கோடி": 1_00_00_000,
    },
    direct_values={},
    noise_tokens=frozenset({
        "ரூபாய்", "ரூபாயில்", "ரூபா", "ரூ", "ரூ.",
        "மட்டும்", "மட்டுமே", "மட்டமே", "மட்டு", "மட்டே",
        "மட்டும", "மட்டமே", "மட்டிலும்",
        "ஓன்லி", "மட்டமே",
    }),
)


def parse_tamil_amount_words(words: str) -> float | None:
    return _parse(words, _TAMIL)


# ─────────────────────────────────────────────────────────────────────────────
#  TELUGU (te)
# ─────────────────────────────────────────────────────────────────────────────

_TELUGU = _LangConfig(
    number_words={
        # Ones
        "ఒకటి": 1,  "ఒక": 1,
        "రెండు": 2,
        "మూడు": 3,
        "నాలుగు": 4,
        "ఐదు": 5,  "అయిదు": 5,
        "ఆరు": 6,
        "ఏడు": 7,
        "ఎనిమిది": 8,
        "తొమ్మిది": 9,
        # Teens
        "పది": 10,
        "పదకొండు": 11,
        "పన్నెండు": 12,
        "పదమూడు": 13,
        "పదినాలుగు": 14,
        "పదిహేను": 15,
        "పదహారు": 16,
        "పదిహేడు": 17,
        "పదెనిమిది": 18,
        "పందొమ్మిది": 19,
        # Tens
        "ఇరవై": 20,
        "ముప్పై": 30,
        "నలభై": 40,
        "యాభై": 50,
        "అరవై": 60,
        "డెబ్బది": 70,  "డెభ్భై": 70,
        "ఎనభై": 80,
        "తొంభై": 90,
        # Compound forms common on cheques
        "ఇరవైఐదు": 25,  "ముప్పైఐదు": 35,
        "నలభైఐదు": 45,  "యాభైఐదు": 55,
        "అరవైఐదు": 65,  "డెబ్బదిఐదు": 75,
        "ఎనభైఐదు": 85,  "తొంభైఐదు": 95,
    },
    scale_words={
        "వంద": 100,
        "వేయి": 1_000, "వేలు": 1_000,
        "లక్ష": 1_00_000, "లక్షలు": 1_00_000,
        "కోటి": 1_00_00_000, "కోట్లు": 1_00_00_000,
    },
    direct_values={},
    noise_tokens=frozenset({
        "రూపాయలు", "రూపాయి", "రూపా", "రూ", "రూ.",
        "మాత్రమే", "మాత్ర", "కేవలం",
    }),
)


def parse_telugu_amount_words(words: str) -> float | None:
    return _parse(words, _TELUGU)


# ─────────────────────────────────────────────────────────────────────────────
#  KANNADA (kn)
# ─────────────────────────────────────────────────────────────────────────────

_KANNADA = _LangConfig(
    number_words={
        # Ones
        "ಒಂದು": 1,
        "ಎರಡು": 2,
        "ಮೂರು": 3,
        "ನಾಲ್ಕು": 4,
        "ಐದು": 5,
        "ಆರು": 6,
        "ಏಳು": 7,
        "ಎಂಟು": 8,
        "ಒಂಭತ್ತು": 9,
        # Teens
        "ಹತ್ತು": 10,
        "ಹನ್ನೊಂದು": 11,
        "ಹನ್ನೆರಡು": 12,
        "ಹದಿಮೂರು": 13,
        "ಹದಿನಾಲ್ಕು": 14,
        "ಹದಿನೈದು": 15,
        "ಹದಿನಾರು": 16,
        "ಹದಿನೇಳು": 17,
        "ಹದಿನೆಂಟು": 18,
        "ಹತ್ತೊಂಭತ್ತು": 19,
        # Tens
        "ಇಪ್ಪತ್ತು": 20,
        "ಮೂವತ್ತು": 30,
        "ನಲ್ವತ್ತು": 40,
        "ಐವತ್ತು": 50,
        "ಅರವತ್ತು": 60,
        "ಎಪ್ಪತ್ತು": 70,
        "ಎಂಬತ್ತು": 80,
        "ತೊಂಬತ್ತು": 90,
        # Compound forms
        "ಇಪ್ಪತ್ತೈದು": 25,
        "ಮೂವತ್ತೈದು": 35,
        "ನಲ್ವತ್ತೈದು": 45,
        "ಐವತ್ತೈದು": 55,
        "ಅರವತ್ತೈದು": 65,
        "ಎಪ್ಪತ್ತೈದು": 75,
        "ಎಂಬತ್ತೈದು": 85,
        "ತೊಂಬತ್ತೈದು": 95,
    },
    scale_words={
        "ನೂರು": 100,
        "ಸಾವಿರ": 1_000,
        "ಲಕ್ಷ": 1_00_000,
        "ಕೋಟಿ": 1_00_00_000,
    },
    direct_values={},
    noise_tokens=frozenset({
        "ರೂಪಾಯಿ", "ರೂಪಾಯಿಗಳು", "ರೂ", "ರೂ.",
        "ಮಾತ್ರ", "ಮಾತ್ರವೇ", "ಕೇವಲ",
    }),
)


def parse_kannada_amount_words(words: str) -> float | None:
    return _parse(words, _KANNADA)


# ─────────────────────────────────────────────────────────────────────────────
#  MALAYALAM (ml)
# ─────────────────────────────────────────────────────────────────────────────

_MALAYALAM = _LangConfig(
    number_words={
        # Ones
        "ഒന്ന്": 1,  "ഒരു": 1,
        "രണ്ട്": 2,
        "മൂന്ന്": 3,
        "നാല്": 4,  "നാലു": 4,
        "അഞ്ച്": 5,
        "ആറ്": 6,
        "ഏഴ്": 7,
        "എട്ട്": 8,
        "ഒമ്പത്": 9,
        # Teens
        "പത്ത്": 10,
        "പതിനൊന്ന്": 11,
        "പന്ത്രണ്ട്": 12,
        "പതിമൂന്ന്": 13,
        "പതിനാല്": 14,
        "പതിനഞ്ച്": 15,
        "പതിനാറ്": 16,
        "പതിനേഴ്": 17,
        "പതിനെട്ട്": 18,
        "പത്തൊമ്പത്": 19,
        # Tens
        "ഇരുപത്": 20,
        "മുപ്പത്": 30,
        "നാല്പത്": 40,
        "അൻപത്": 50,
        "അമ്പത്": 50,
        "അറുപത്": 60,
        "എഴുപത്": 70,
        "എൺപത്": 80,
        "തൊണ്ണൂറ്": 90,
        # Compound forms
        "ഇരുപത്തഞ്ച്": 25,
        "മുപ്പത്തഞ്ച്": 35,
        "നാല്പത്തഞ്ച്": 45,
        "അൻപത്തഞ്ച്": 55,
        "അറുപത്തഞ്ച്": 65,
        "എഴുപത്തഞ്ച്": 75,
        "എൺപത്തഞ്ച്": 85,
        "തൊണ്ണൂറ്റഞ്ച്": 95,
    },
    scale_words={
        "നൂറ്": 100,
        "ആയിരം": 1_000,
        "ലക്ഷം": 1_00_000,
        "കോടി": 1_00_00_000,
    },
    # Compound Malayalam forms where scale is merged into the word
    direct_values={
        "അൻപതിനായിരം": 50_000,   # "fifty-thousand" as one word
        "ഇരുപതിനായിരം": 20_000,  # "twenty-thousand"
        "മുപ്പതിനായിരം": 30_000,
        "നാൽപ്പതിനായിരം": 40_000,
        "അറുപതിനായിരം": 60_000,
        "എഴുപതിനായിരം": 70_000,
        "എൺപതിനായിരം": 80_000,
        "തൊണ്ണൂറ്റിനായിരം": 90_000,
    },
    noise_tokens=frozenset({
        "രൂപ", "രൂപായ്", "രൂ", "രൂ.",
        "മാത്രം", "മാത്രമേ", "കേവലം",
    }),
)


def parse_malayalam_amount_words(words: str) -> float | None:
    return _parse(words, _MALAYALAM)


# ─────────────────────────────────────────────────────────────────────────────
#  GUJARATI (gu)
# ─────────────────────────────────────────────────────────────────────────────

_GUJARATI = _LangConfig(
    number_words={
        # Ones
        "એક": 1,
        "બે": 2,
        "ત્રણ": 3,
        "ચાર": 4,
        "પાંચ": 5,
        "છ": 6,
        "સાત": 7,
        "આઠ": 8,
        "નવ": 9,
        # Teens
        "દસ": 10,
        "અગિયાર": 11,
        "બાર": 12,
        "તેર": 13,
        "ચૌદ": 14,
        "પંદર": 15,
        "સોળ": 16,
        "સત્તર": 17,
        "અઢાર": 18,
        "ઓગણીસ": 19,
        # Tens
        "વીસ": 20,
        "ત્રીસ": 30,
        "ચાળીસ": 40,
        "પચાસ": 50,
        "સાઠ": 60,
        "સિત્તેર": 70,
        "એંસી": 80,
        "નેવું": 90,
        # Compound forms
        "પચ્ચીસ": 25,
        "પાંત્રીસ": 35,
        "પિસ્તાળીસ": 45,
        "પંચોતેર": 75,
        "પંચ્યાસી": 85,
        "પંચ્યાણું": 95,
    },
    scale_words={
        "સો": 100,
        "હજાર": 1_000,
        "લાખ": 1_00_000,
        "કરોડ": 1_00_00_000,
    },
    direct_values={},
    noise_tokens=frozenset({
        "રૂપિયા", "રૂ", "રૂ.", "ના",
        "માત્ર", "ફક્ત", "જ",
    }),
)


def parse_gujarati_amount_words(words: str) -> float | None:
    return _parse(words, _GUJARATI)


# ─────────────────────────────────────────────────────────────────────────────
#  BENGALI (bn)
# ─────────────────────────────────────────────────────────────────────────────

_BENGALI = _LangConfig(
    number_words={
        # Ones
        "এক": 1,
        "দুই": 2,  "দো": 2,
        "তিন": 3,
        "চার": 4,
        "পাঁচ": 5,
        "ছয়": 6,
        "সাত": 7,
        "আট": 8,
        "নয়": 9,
        # Teens
        "দশ": 10,
        "এগারো": 11,
        "বারো": 12,
        "তেরো": 13,
        "চোদ্দো": 14,
        "পনেরো": 15,
        "ষোলো": 16,
        "সতেরো": 17,
        "আঠারো": 18,
        "উনিশ": 19,
        # Tens
        "বিশ": 20,
        "ত্রিশ": 30,
        "চল্লিশ": 40,
        "পঞ্চাশ": 50,
        "ষাট": 60,
        "সত্তর": 70,
        "আশি": 80,
        "নব্বই": 90,
        # Compound forms
        "পঁচিশ": 25,
        "পঁয়ত্রিশ": 35,
        "পঁয়তাল্লিশ": 45,
        "পঁচাত্তর": 75,
        "পঁচাশি": 85,
        "পঁচানব্বই": 95,
    },
    scale_words={
        "শত": 100,
        "হাজার": 1_000,
        "লক্ষ": 1_00_000,  "লাখ": 1_00_000,
        "কোটি": 1_00_00_000,
    },
    direct_values={},
    noise_tokens=frozenset({
        "টাকা", "টা", "রুপি", "রু",
        "মাত্র", "কেবল", "শুধু",
    }),
)


def parse_bengali_amount_words(words: str) -> float | None:
    return _parse(words, _BENGALI)


# ─────────────────────────────────────────────────────────────────────────────
#  PUNJABI / GURMUKHI (pa)
# ─────────────────────────────────────────────────────────────────────────────

_PUNJABI = _LangConfig(
    number_words={
        # Ones
        "ਇੱਕ": 1,
        "ਦੋ": 2,
        "ਤਿੰਨ": 3,
        "ਚਾਰ": 4,
        "ਪੰਜ": 5,
        "ਛੇ": 6,
        "ਸੱਤ": 7,
        "ਅੱਠ": 8,
        "ਨੌ": 9,  "ਨੌਂ": 9,
        # Teens
        "ਦਸ": 10,
        "ਗਿਆਰਾਂ": 11,
        "ਬਾਰਾਂ": 12,
        "ਤੇਰਾਂ": 13,
        "ਚੌਦਾਂ": 14,
        "ਪੰਦਰਾਂ": 15,
        "ਸੋਲਾਂ": 16,
        "ਸਤਾਰਾਂ": 17,
        "ਅਠਾਰਾਂ": 18,
        "ਉਨੀ": 19,
        # Tens
        "ਵੀਹ": 20,
        "ਤੀਹ": 30,
        "ਚਾਲੀ": 40,
        "ਪੰਜਾਹ": 50,
        "ਸੱਠ": 60,
        "ਸੱਤਰ": 70,
        "ਅੱਸੀ": 80,
        "ਨੱਬੇ": 90,
        # Compound forms
        "ਪੱਚੀ": 25,
        "ਪੈਂਤੀ": 35,
        "ਪੈਂਤਾਲੀ": 45,
        "ਪੰਜਾਹਤਰ": 75,
        "ਪੰਜਾਸੀ": 85,
        "ਪੰਜਾਨਵੇ": 95,
    },
    scale_words={
        "ਸੌ": 100,
        "ਹਜ਼ਾਰ": 1_000,
        "ਲੱਖ": 1_00_000,
        "ਕਰੋੜ": 1_00_00_000,
    },
    direct_values={},
    noise_tokens=frozenset({
        "ਰੁਪਏ", "ਰੁਪਿਆ", "ਰੁ", "ਰੁ.",
        "ਕੇਵਲ", "ਸਿਰਫ਼", "ਮਾਤਰ",
    }),
)


def parse_punjabi_amount_words(words: str) -> float | None:
    return _parse(words, _PUNJABI)


# ─────────────────────────────────────────────────────────────────────────────
#  ODIA (or)
# ─────────────────────────────────────────────────────────────────────────────

_ODIA = _LangConfig(
    number_words={
        # Ones
        "ଏକ": 1,  "ଏକ": 1,
        "ଦୁଇ": 2,
        "ତିନି": 3,
        "ଚାରି": 4,
        "ପାଞ୍ଚ": 5,
        "ଛ": 6,
        "ସାତ": 7,
        "ଆଠ": 8,
        "ନଅ": 9,
        # Teens
        "ଦଶ": 10,
        "ଏଗାର": 11,
        "ବାର": 12,
        "ତେର": 13,
        "ଚଉଦ": 14,
        "ପନ୍ଦର": 15,
        "ଷୋହଳ": 16,
        "ସତର": 17,
        "ଅଠର": 18,
        "ଉଣେଇଶ": 19,
        # Tens
        "ବିଶ": 20,
        "ତିରିଶ": 30,
        "ଚାଳିଶ": 40,
        "ପଚାଶ": 50,
        "ଷାଠ": 60,
        "ସତ୍ତର": 70,
        "ଅଶ": 80,
        "ନବେ": 90,
        # Compounds
        "ପଚିଶ": 25,
        "ପଁଚିଶ": 25,
        "ପଞ୍ଚଷଠ": 65,
        "ପଞ୍ଚସତ": 75,
    },
    scale_words={
        "ଶହ": 100,
        "ହଜାର": 1_000,
        "ଲକ୍ଷ": 1_00_000,
        "କୋଟି": 1_00_00_000,
    },
    direct_values={},
    noise_tokens=frozenset({
        "ଟଙ୍କା", "ଟ", "ରୁ",
        "ମାତ୍ର", "କେବଳ",
    }),
)


def parse_odia_amount_words(words: str) -> float | None:
    return _parse(words, _ODIA)


# ─────────────────────────────────────────────────────────────────────────────
#  Dispatch by detected script
# ─────────────────────────────────────────────────────────────────────────────

_SCRIPT_PARSERS: dict[str, Callable[[str], float | None]] = {
    "tamil":     parse_tamil_amount_words,
    "telugu":    parse_telugu_amount_words,
    "kannada":   parse_kannada_amount_words,
    "malayalam": parse_malayalam_amount_words,
    "gujarati":  parse_gujarati_amount_words,
    "bengali":   parse_bengali_amount_words,
    "gurmukhi":  parse_punjabi_amount_words,
    "odia":      parse_odia_amount_words,
    # Devanagari is handled by amount_words_parser.parse_hindi_amount_words()
    # Returning None here causes the caller to fall through to that parser.
}


def parse_indic_amount_by_script(words: str, script: str) -> float | None:
    """Dispatch amount-word parsing to the correct language parser.

    Returns None for devanagari (caller uses parse_hindi_amount_words),
    and None for any unknown script.
    """
    parser = _SCRIPT_PARSERS.get(script)
    if parser is None:
        return None
    return parser(words)
