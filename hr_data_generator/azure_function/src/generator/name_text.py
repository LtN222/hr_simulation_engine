"""Make generated foreign names storable in the CP1252 SQL name columns.

`dim_employee`/`dim_manager` name columns are VARCHAR with collation
SQL_Latin1_General_CP1_CI_AS, i.e. code page 1252. Names from Faker's Polish,
Romanian and Bulgarian locales contain characters that code page cannot hold
(Cyrillic, ł, ś, ą, ę, ș, ț, ă ...). Only Expat names go through this module;
Dutch names (e.g. with ë) are already CP1252-safe and stay untouched.
"""

import unicodedata

# Bulgarian Streamlined System (official romanization, 2009/2015 law).
_BULGARIAN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sht", "ъ": "a",
    "ь": "y", "ю": "yu", "я": "ya",
}

# Letters NFKD does not decompose into base letter + combining mark.
_UNDECOMPOSED = {
    "ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ø": "o", "Ø": "O",
    "ħ": "h", "Ħ": "H", "ı": "i",
}


def to_cp1252_latin(text):
    """Return `text` in Latin script that CP1252 can store.

    Bulgarian Cyrillic is romanized first; then any character CP1252 cannot
    encode is folded to plain ASCII. Characters CP1252 can store (é, ö, â, î
    ...) are kept as they are.
    """
    text = _romanize_bulgarian(text)
    return "".join(_fold_if_needed(character) for character in text)


def _romanize_bulgarian(text):
    if not any(character.lower() in _BULGARIAN for character in text):
        return text
    words = []
    for word in text.split(" "):
        lowered = word.lower()
        # Streamlined System: a final "ия" is written "ia" (Мария -> Maria).
        final_ia = lowered.endswith("ия") and len(lowered) > 2
        body = word[:-2] if final_ia else word
        result = "".join(_romanize_letter(character) for character in body)
        if final_ia:
            result += "ia"
        words.append(result)
    return " ".join(words)


def _romanize_letter(character):
    replacement = _BULGARIAN.get(character.lower())
    if replacement is None:
        return character
    return replacement.capitalize() if character.isupper() else replacement


def _fold_if_needed(character):
    try:
        character.encode("cp1252")
        return character
    except UnicodeEncodeError:
        pass
    if character in _UNDECOMPOSED:
        return _UNDECOMPOSED[character]
    folded = unicodedata.normalize("NFKD", character).encode("ascii", "ignore").decode("ascii")
    if not folded:
        raise ValueError(f"cannot fold {character!r} (U+{ord(character):04X}) to a CP1252-safe letter")
    return folded
