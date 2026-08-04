
from __future__ import annotations

import re
import unicodedata


_FILLER_PATTERNS = (
    r"\bcould you\b",
    r"\bwould you\b",
    r"\bcan you\b",
    r"\bplease\b",
    r"\bi want you to\b",
    r"\bi need you to\b",
    r"\bfor me\b",
)

_CONTRACTIONS = {
    "don't": "do not",
    "can't": "cannot",
    "won't": "will not",
    "what's": "what is",
    "it's": "it is",
}


def normalize_input(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).strip().lower()
    for source, replacement in _CONTRACTIONS.items():
        value = value.replace(source, replacement)
    value = re.sub(r"(?<=\w)[\u2010-\u2015-](?=\w)", " ", value)
    value = value.replace("_", " ")
    value = re.sub(r"[?!,;]+", " ", value)
    value = re.sub(r"\s*:\s*", ": ", value)
    for pattern in _FILLER_PATTERNS:
        value = re.sub(pattern, " ", value)
    return " ".join(value.split())


def contains_phrase(text: str, phrase: str) -> bool:
    clean_phrase = normalize_input(phrase)
    if not clean_phrase:
        return False
    pattern = r"(?<!\w)" + re.escape(clean_phrase).replace(r"\ ", r"\s+") + r"(?!\w)"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None
