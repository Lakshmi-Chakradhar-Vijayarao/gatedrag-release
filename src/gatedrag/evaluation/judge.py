"""LLM-judge check on `correct` (evaluator-side; reported next to the lexical score, never instead).

The lexical scorer (metrics.reference_recall) is deterministic and pre-registered as the primary
metric. A 60-answer human audit showed it misses paraphrases, so a judge from a DIFFERENT model
family than the system under test grades each shipped answer against the reference:

    correct_judge = 1  if an answerable item's shipped answer states the reference's key facts
                       (paraphrase allowed, no contradicting fact), as judged by the model
    correct_judge     = the lexical rule's value on unanswerable items (abstaining is correct)

Both scores are validated against a fresh blind human batch before either is trusted.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from gatedrag.evaluation.golden import GoldenItem

PROMPT = """You are grading an answer to a question about software documentation.

Question: {question}
Reference (the key facts a correct answer must state): {reference}
Candidate answer: {answer}

The candidate is CORRECT if it states the reference's key facts, in any wording. It is INCORRECT if it
misses a key fact, states a wrong value, or contradicts the reference. Extra correct detail is fine.
Reply with exactly one word: CORRECT or INCORRECT."""


_CITATION = re.compile(r"\[\d+\]")


def has_content(answer: str) -> bool:
    """False for an answer that is only citation markers and punctuation, e.g. "[1]" or "[2] [1].".
    Such an answer states no fact, so it cannot be correct. Decided without the judge, which was found
    (19 Nov 2026, abstain-or-gate dev pool) to grade 54 of 72 citation-only answers CORRECT."""
    return re.search(r"[A-Za-z0-9]", _CITATION.sub("", answer)) is not None


def parse(text: str) -> int | None:
    t = text.strip().upper()
    if t.startswith("INCORRECT"):
        return 0
    if t.startswith("CORRECT"):
        return 1
    return None


def judge_pool(pool: dict, golden: list[GoldenItem], generator, concurrency: int = 8) -> dict:
    if "records" not in pool:
        raise ValueError("pool has no answer records")
    by_id = {g.id: g for g in golden}
    ids = pool["meta"]["item_ids"]
    jobs = []
    contentless = 0
    for k, (scores, recs) in enumerate(zip(pool["runs"], pool["records"], strict=True)):
        for i, (item_id, sc, rec) in enumerate(zip(ids, scores, recs, strict=True)):
            g = by_id.get(item_id)
            if g is not None and g.answerable and rec["decision"] != "ABSTAIN":
                if has_content(rec["answer"]):
                    jobs.append((k, i, g, rec["answer"]))
                else:
                    sc["correct_judge"] = 0.0                # states nothing: wrong, no judge call
                    contentless += 1
            else:
                sc["correct_judge"] = sc["correct"]          # abstentions and unanswerable items: same rule

    def ask(job):
        k, i, g, answer = job
        msg = PROMPT.format(question=g.question, reference=g.reference, answer=answer)
        out = generator.generate([{"role": "user", "content": msg}], temperature=0.0, max_tokens=4, seed=0)
        return k, i, parse(out.text)

    unparsed = 0
    with ThreadPoolExecutor(concurrency) as ex:
        for k, i, verdict in ex.map(ask, jobs):
            if verdict is None:
                unparsed += 1
                verdict = pool["runs"][k][i]["correct"]      # fall back to the lexical score; counted below
            pool["runs"][k][i]["correct_judge"] = float(verdict)
    pool["meta"]["judge"] = {"model": generator.name, "judged": len(jobs), "unparsed": unparsed,
                             "contentless_scored_wrong": contentless, "prompt_version": 2}
    return pool


def apply_content_rule(pool: dict) -> int:
    """Re-apply `has_content` to a pool judged before the rule existed (prompt_version 1); returns how
    many judge verdicts it overturned. Deterministic: no model call."""
    flipped = 0
    for scores, recs in zip(pool["runs"], pool["records"], strict=True):
        for sc, rec in zip(scores, recs, strict=True):
            if sc.get("answerable") == 1.0 and sc.get("abstained") == 0.0 and not has_content(rec["answer"]):
                if sc.get("correct_judge") == 1.0:
                    flipped += 1
                sc["correct_judge"] = 0.0
    pool["meta"].setdefault("judge", {})["content_rule_applied"] = flipped
    return flipped
