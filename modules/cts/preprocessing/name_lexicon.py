"""Malayalam Christian-name lexicon for CTS payee-name matching.

Malayalam Christian names (George, Thomas, John, etc.) are of Greek/Aramaic/Hebrew
origin, brought to Kerala via the St. Thomas tradition and Portuguese colonialism.
No phonemic transliteration rule can recover the conventional English spelling from
the Malayalam script form — "ജോർജ്ജ്" sounds like "joorjj" but maps to "george".

This module provides:
  lookup_token(token, script) → canonical English form | None
  apply_lexicon(text, script) → text with known tokens replaced by canonical forms

Called from payee_normalizer.payee_names_match BEFORE transliteration so the
Brahmic engine handles the remainder (standard Hindu names, place names, etc.).
"""
from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────────────
#  Malayalam Christian-name lexicon
#  Keys: Malayalam script strings (NFC normalised)
#  Values: canonical English form, lowercase ASCII
# ─────────────────────────────────────────────────────────────────────────────

_MALAYALAM_LEXICON: dict[str, str] = {
    # George — most common Kerala Christian male name
    "ജോർജ്ജ്":      "george",
    "ജോർജ്":        "george",    # alternate single-ജ spelling
    "ജോർജ്ജ":       "george",    # without final virama
    "ജോർജ":         "george",
    "ജോർജ്ജ്കുട്ടി": "georgekutty",
    "ജോർജ്കുട്ടി":  "georgekutty",
    "ജോർജ്ജി":      "georgy",

    # Thomas
    "തോമസ്":        "thomas",
    "തോമസ":         "thomas",
    "ത്തോമസ്":      "thomas",
    "തോമസ്കുട്ടി":  "thomaskutty",

    # John / Johny
    "ജോൺ":           "john",
    "ജോൺസ്":         "johns",
    "ജോണി":          "johny",
    "ജോൺകുട്ടി":    "johnkutty",

    # Joseph / Jose
    "ജോസഫ്":         "joseph",
    "ജോസ്":          "jose",
    "ജോസേഫ്":        "joseph",
    "ജോസ്കുട്ടി":   "josekutty",

    # Paul
    "പോൾ":           "paul",
    "പോൾസ്":         "pauls",

    # Peter
    "പീറ്റർ":        "peter",
    "പേദ്രോ":        "pedro",

    # Philip
    "ഫിലിപ്പ്":      "philip",
    "ഫിലിപ്":        "philip",
    "ഫിലിപ്പോസ്":   "philipoos",

    # Mathew / Matthew (Kerala spelling is Mathew)
    "മത്തായി":       "mathew",
    "മാത്യൂ":        "mathew",
    "മത്തേൽ":        "mathew",

    # Jacob / Kochukoshy
    "ജേക്കബ്":       "jacob",
    "ജേക്കബ്":       "jacob",
    "കൊച്ചുകൊശി":   "kochukoshy",

    # Abraham / Aboobacker (also used by Christians)
    "അബ്രഹാം":       "abraham",
    "ഇബ്രഹീം":       "ibrahim",

    # Simon
    "സൈമൺ":          "simon",
    "ശിമോൻ":         "simon",

    # Stephen
    "സ്റ്റീഫൻ":      "stephen",
    "ഇസ്തഫാൻ":       "stephen",

    # Francis / Francis Xavier
    "ഫ്രാൻസിസ്":     "francis",
    "ഫ്രാൻസ്":       "france",

    # Sebastian
    "സെബാസ്ത്യൻ":   "sebastian",
    "സേബ്":          "sebi",

    # Vincent
    "വിൻസെന്റ്":    "vincent",

    # Xavier
    "സേവ്യർ":        "xavier",

    # Michael
    "മൈക്കിൾ":       "michael",
    "മൈക്കൽ":        "michael",

    # Andrew
    "ആൻ്ഡ്രൂ":       "andrew",
    "ആൻ്ഡ്രൂ":       "andrew",

    # Mark
    "മാർക്ക്":       "mark",
    "മർക്കോസ്":      "markose",

    # Luke
    "ലൂക്ക":         "luke",
    "ലൂക്കോസ്":      "lukose",

    # Alexander
    "അലക്സാണ്ടർ":   "alexander",
    "അലക്സ്":        "alex",

    # Nicholas
    "നിക്കോളാസ്":   "nicholas",
    "നിക്കോ":        "niko",

    # Christian female names
    "മേരി":          "mary",
    "മറിയം":         "mariam",
    "മറിയ":          "maria",
    "മറിയാമ്മ":      "mariamma",
    "മേരിക്കുട്ടി": "marykutty",

    "എലിസബത്ത്":    "elizabeth",
    "ഏലിശ്ബ":        "elishba",

    "ആൻ":            "ann",
    "അന്ന":          "anna",
    "അന്നമ്മ":       "annamma",
    "ആനി":           "annie",

    "തങ്കമ്മ":       "thankamma",
    "ഷേർളി":         "sherley",
    "ഷൈനി":          "shainy",
    "ലൈലാ":          "laila",
    "ജ്യോതി":        "jyothi",

    "റോസ്":          "rose",
    "റോസമ്മ":        "rosamma",
    "ഗ്രേസ്":        "grace",

    "ജൂലി":          "julie",
    "ജൂലിയ":         "julia",

    "ബിന്ദു":        "bindu",
    "ബീന":           "beena",
    "ജിന":           "jina",

    # Common surnames / family names used as given names
    "ചെറിയാൻ":       "cheriyan",
    "കുര്യൻ":        "kurian",
    "ഈപ്പൻ":         "ippen",
    "കൊച്ചൻ":        "kochan",
    "ഔസേഫ്":         "ouseph",
    "ഔസ്":           "ous",
    "ഗീവർഗ്ഗീസ്":   "geevarghese",
}

MALAYALAM_LEXICON_SIZE: int = len(_MALAYALAM_LEXICON)


# ─────────────────────────────────────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────────────────────────────────────

def lookup_token(token: str, script: str) -> str | None:
    """Return canonical English form for a single Malayalam script token.

    Returns None if:
    - script is not "malayalam"
    - token is not found in the lexicon
    - token is empty / whitespace / Latin
    """
    if script != "malayalam":
        return None
    token = token.strip()
    if not token:
        return None
    return _MALAYALAM_LEXICON.get(token)


def apply_lexicon(text: str, script: str) -> str:
    """Replace known lexicon tokens in text with their canonical English forms.

    Splits text on whitespace, checks each token against the lexicon.
    Tokens not found in the lexicon are returned unchanged — the caller's
    transliterator handles them.

    Non-Malayalam scripts are returned unchanged (fast path).
    """
    if script != "malayalam":
        return text
    text = text.strip()
    if not text:
        return text
    parts = text.split()
    out = []
    for part in parts:
        canonical = _MALAYALAM_LEXICON.get(part)
        out.append(canonical if canonical is not None else part)
    return " ".join(out)
