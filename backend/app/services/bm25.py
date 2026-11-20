"""BM25 sparse vectors for Qdrant keyword search.

Qdrant applies the IDF part itself (sparse vector `modifier=IDF`), so documents only carry the
term-frequency part of BM25 and queries carry 1.0 per term. Terms are hashed to stable 32-bit
indices. No model and no API key are involved, so keyword search works for every user.

Tokens keep identifiers intact (INV-2024-118, GST numbers, phone numbers, emails) and also index
their parts, so both "INV-2024-118" and "2024" match. English words are lightly stemmed so
"supplier"/"suppliers"/"supplies" meet; other words (Hindi/Hinglish, names) are kept as written.
"""
from __future__ import annotations

import re
import unicodedata
import zlib
from collections import Counter

from qdrant_client import models

try:  # small pure-Python Snowball stemmer; without it terms are matched as written
    import snowballstemmer

    _stem = snowballstemmer.stemmer("english").stemWord
except Exception:  # pragma: no cover
    def _stem(word: str) -> str:
        return word

K1 = 1.2
B = 0.75
AVG_DOC_LEN = 12.0  # memories are short single sentences

STOPWORDS = frozenset("""
a an and are as at be been but by can could did do does for from had has have he her his how i if in into is
it its me my no not of on or our ours she so that the their them then there these they this those to too us
was we were what when where which who whom why will with would you your yours about any all also am just
please tell show give get let hi hello thanks thank ok okay yes
""".split())

_TOKEN = re.compile(r"[\w][\w@.\-/+]*[\w]|[\w]", re.UNICODE)
_PART = re.compile(r"[^\W_]+", re.UNICODE)


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").lower()


def _term(word: str) -> str:
    if word.isascii() and word.isalpha() and len(word) > 3:
        return _stem(word)
    return word


def tokenize(text: str) -> list[str]:
    """Search terms: whole identifiers plus their parts, stopwords removed, English words stemmed."""
    terms: list[str] = []
    for token in _TOKEN.findall(_normalize(text)):
        parts = _PART.findall(token)
        if len(parts) > 1:
            terms.append(token)  # keep "inv-2024-118" whole for exact matches
        for part in parts:
            if part in STOPWORDS or (len(part) < 2 and not part.isdigit()):
                continue
            terms.append(_term(part))
    return terms


def _index(term: str) -> int:
    return zlib.crc32(term.encode("utf-8"))


def document_vector(text: str) -> models.SparseVector:
    """BM25 term-frequency weights for a stored memory."""
    counts = Counter(tokenize(text))
    if not counts:
        return models.SparseVector(indices=[], values=[])
    length = sum(counts.values())
    weights: dict[int, float] = {}
    for term, tf in counts.items():
        idx = _index(term)
        weight = tf * (K1 + 1) / (tf + K1 * (1 - B + B * length / AVG_DOC_LEN))
        weights[idx] = max(weights.get(idx, 0.0), weight)
    return models.SparseVector(indices=list(weights), values=list(weights.values()))


def query_vector(text: str) -> models.SparseVector:
    """One unit weight per distinct query term (Qdrant multiplies in the IDF)."""
    indices = sorted({_index(term) for term in tokenize(text)})
    return models.SparseVector(indices=indices, values=[1.0] * len(indices))
