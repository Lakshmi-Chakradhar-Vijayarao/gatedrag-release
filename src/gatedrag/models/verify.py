"""Claim-level support check of an answer against the passages it was given.

The lexical verifier scores each claim (sentence) by the fraction of its content words found in
the best-matching retrieved passage. It is deliberately simple and NOT self-referential: it never
looks at the reference answer or the evaluation labels. `always_accept` exists only as a planted
regression for the release gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from gatedrag.models.retrieval import Hit, tokenize

_ABSTAIN_RE = re.compile(r"\b(i don'?t know|not (?:contained |found )?in the (?:passages|context)|cannot answer)\b", re.I)
_CITE_RE = re.compile(r"\[(\d+)\]")
_SENT_RE = re.compile(r"(?<=[.!?])\s+")
_STOP = frozenset("a an the is are was were be of to in on for and or it its this that with by as at".split())


@dataclass(frozen=True)
class Verification:
    support: float                 # mean claim support in [0, 1]
    n_claims: int
    unsupported_claims: tuple[str, ...]
    abstained: bool
    cited: tuple[int, ...]         # 1-based passage numbers cited


def is_abstention(text: str) -> bool:
    return bool(_ABSTAIN_RE.search(text)) or not text.strip()


def claims(text: str) -> list[str]:
    clean = _CITE_RE.sub("", text)
    return [s.strip() for s in _SENT_RE.split(clean) if len(set(tokenize(s)) - _STOP) >= 2]


def verify(answer: str, hits: list[Hit], mode: str = "lexical", min_claim_support: float = 0.6) -> Verification:
    cited = tuple(sorted({int(m) for m in _CITE_RE.findall(answer) if 0 < int(m) <= len(hits)}))
    if is_abstention(answer):
        return Verification(1.0, 0, (), True, cited)
    cl = claims(answer)
    if mode == "always_accept":
        return Verification(1.0, len(cl), (), False, cited)
    if not cl:
        return Verification(0.0, 0, (), False, cited)
    passages = [set(tokenize(h.chunk.text)) for h in hits]
    scores, unsupported = [], []
    for c in cl:
        words = set(tokenize(c)) - _STOP
        best = max((len(words & p) / len(words) for p in passages), default=0.0)
        scores.append(best)
        if best < min_claim_support:
            unsupported.append(c)
    return Verification(sum(scores) / len(scores), len(cl), tuple(unsupported), False, cited)
