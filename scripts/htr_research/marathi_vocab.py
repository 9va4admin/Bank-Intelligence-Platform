"""Marathi vocabulary for handwriting data collection and testing (research use).

What a cheque carries: the amount in words, a payee name, a city, and a few fixed phrases.
This module holds those words and builds reproducible prompt sheets for writers to copy.

IMPORTANT: this list was written from general knowledge, not checked by a native Marathi speaker.
Marathi number words have several accepted spellings. Have a native speaker review the file
(see docs/research/marathi-vocabulary.md) before any sheet is printed.
"""
import random

# 0-100. Marathi number words are irregular, so each one is listed rather than built by a rule.
_UNITS = (
    "शून्य एक दोन तीन चार पाच सहा सात आठ नऊ दहा "
    "अकरा बारा तेरा चौदा पंधरा सोळा सतरा अठरा एकोणीस वीस "
    "एकवीस बावीस तेवीस चोवीस पंचवीस सव्वीस सत्तावीस अठ्ठावीस एकोणतीस तीस "
    "एकतीस बत्तीस तेहतीस चौतीस पस्तीस छत्तीस सदतीस अडतीस एकोणचाळीस चाळीस "
    "एक्केचाळीस बेचाळीस त्रेचाळीस चव्वेचाळीस पंचेचाळीस सेहेचाळीस सत्तेचाळीस अठ्ठेचाळीस एकोणपन्नास पन्नास "
    "एक्कावन्न बावन्न त्रेपन्न चोपन्न पंचावन्न छप्पन्न सत्तावन्न अठ्ठावन्न एकोणसाठ साठ "
    "एकसष्ठ बासष्ठ त्रेसष्ठ चौसष्ठ पासष्ठ सहासष्ठ सदुसष्ठ अडुसष्ठ एकोणसत्तर सत्तर "
    "एक्काहत्तर बाहत्तर त्र्याहत्तर चौर्‍याहत्तर पंच्याहत्तर शहात्तर सत्त्याहत्तर अठ्ठ्याहत्तर एकोणऐंशी ऐंशी "
    "एक्क्याऐंशी ब्याऐंशी त्र्याऐंशी चौऱ्याऐंशी पंच्याऐंशी शहाऐंशी सत्त्याऐंशी अठ्ठ्याऐंशी एकोणनव्वद नव्वद "
    "एक्क्याण्णव ब्याण्णव त्र्याण्णव चौऱ्याण्णव पंच्याण्णव शहाण्णव सत्त्याण्णव अठ्ठ्याण्णव नव्व्याण्णव शंभर"
).split()
NUMBER_WORDS = {i: w for i, w in enumerate(_UNITS)}

_HUNDRED_PREFIX = {2: "दोन", 3: "तीन", 4: "चार", 5: "पाच", 6: "सहा", 7: "सात", 8: "आठ", 9: "नऊ"}
_MAX_AMOUNT = 10**9 - 1  # up to 99 crore; cheques here are in rupees


def _below_thousand(n: int) -> list:
    parts = []
    hundreds, rest = divmod(n, 100)
    if hundreds == 1:
        parts.append(NUMBER_WORDS[100] if rest == 0 else "एकशे")
    elif hundreds:
        parts.append(_HUNDRED_PREFIX[hundreds] + "शे")
    if rest and not (hundreds == 1 and rest == 0):
        parts.append(NUMBER_WORDS[rest])
    return parts


def amount_to_words(amount: int) -> str:
    """A whole-rupee amount as Marathi words, in the Indian system (कोटी, लाख, हजार)."""
    if amount < 0 or amount > _MAX_AMOUNT:
        raise ValueError("amount out of range")
    if amount == 0:
        return NUMBER_WORDS[0]
    crore, rem = divmod(amount, 10**7)
    lakh, rem = divmod(rem, 10**5)
    thousand, rem = divmod(rem, 10**3)
    parts = []
    for value, unit in ((crore, "कोटी"), (lakh, "लाख"), (thousand, "हजार")):
        if value:
            parts += [NUMBER_WORDS[value], unit]
    parts += _below_thousand(rem)
    return " ".join(parts)


def amount_phrase(amount: int) -> str:
    """The amount as written on a cheque: रुपये ... फक्त."""
    return f"रुपये {amount_to_words(amount)} फक्त"


_DIGITS = str.maketrans("0123456789", "०१२३४५६७८९")


def to_devanagari_digits(text: str) -> str:
    return text.translate(_DIGITS)


# Words a payee or branch line is likely to carry. Public, common names only; no real customer data.
FIRST_NAMES_MALE = (
    "अमित सुनील प्रकाश रमेश सुरेश महेश संजय राजेश अनिल विजय दीपक अजय सचिन प्रशांत नितीन किरण गणेश सागर योगेश अभिजित "
    "राहुल मंगेश उमेश दिलीप शरद भाऊसाहेब तुकाराम ज्ञानेश्वर शिवाजी"
).split()
FIRST_NAMES_FEMALE = (
    "सुनीता सविता अनिता वैशाली स्मिता प्रिया सुषमा मीना शुभांगी अश्विनी पूजा रेखा ज्योती मंगल सुमती कविता नंदा उषा लता शारदा "
    "सरिता मनीषा सुवर्णा जयश्री"
).split()
SURNAMES = (
    "पाटील देशमुख कुलकर्णी जोशी देशपांडे शिंदे पवार जाधव गायकवाड कदम मोरे चव्हाण सावंत भोसले काळे घाडगे लोखंडे सुर्वे परब "
    "नाईक गावडे माने साळुंके इनामदार बर्वे गोखले दाते ठाकरे"
).split()
CITIES = (
    "मुंबई पुणे नागपूर नाशिक औरंगाबाद कोल्हापूर सोलापूर सातारा सांगली अमरावती ठाणे अहमदनगर जळगाव लातूर नांदेड रत्नागिरी "
    "परभणी धुळे अकोला बीड"
).split()
CHEQUE_TERMS = (
    "रुपये फक्त धारकास किंवा आदेशानुसार खाते कोटी लाख हजार शंभर पैसे श्री श्रीमती कुमारी सौ दिनांक शाखा बँक"
).split()


def all_words() -> list:
    """Every distinct word in the lists above, in a stable order."""
    seen, out = set(), []
    for w in (*NUMBER_WORDS.values(), *FIRST_NAMES_MALE, *FIRST_NAMES_FEMALE, *SURNAMES, *CITIES, *CHEQUE_TERMS,
              "एकशे", *(v + "शे" for v in _HUNDRED_PREFIX.values())):
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


def prompt_sheet(seed: int, size: int) -> list:
    """A reproducible list of (kind, text) items for one writer to copy by hand.

    Roughly 40% amounts in words, 30% names (first name plus surname), 15% cities, 15% fixed phrases.
    Different seeds give different sheets, so many writers cover many words.
    """
    rng = random.Random(seed)
    firsts = FIRST_NAMES_MALE + FIRST_NAMES_FEMALE
    items = []
    for i in range(size):
        r = i % 20
        if r < 8:
            amount = rng.choice([rng.randint(1, 99), rng.randint(100, 9999), rng.randint(10000, 9_999_999)])
            items.append(("number", amount_to_words(amount)))
        elif r < 14:
            items.append(("name", f"{rng.choice(firsts)} {rng.choice(SURNAMES)}"))
        elif r < 17:
            items.append(("city", rng.choice(CITIES)))
        else:
            items.append(("term", rng.choice(CHEQUE_TERMS)))
    rng.shuffle(items)
    return items
