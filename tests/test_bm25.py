import numpy as np
import pytest
from rank_bm25 import BM25Okapi

from gatedrag.models.bm25 import InvertedBM25
from gatedrag.models.retrieval import tokenize


@pytest.mark.parametrize("query", ["maximum message size", "how long are messages retained retained",
                                   "tokens expire rotate", "zzz unknown words", "orbit"])
def test_scores_identical_to_rank_bm25(chunks, query):
    corpus = [tokenize(c.title + " " + c.text) for c in chunks]
    q = tokenize(query)
    np.testing.assert_allclose(InvertedBM25(corpus).get_scores(q), BM25Okapi(corpus).get_scores(q), rtol=1e-12, atol=1e-12)


def test_negative_idf_floor_matches():
    corpus = [["common", "a"], ["common", "b"], ["common", "c"], ["rare"]]
    np.testing.assert_allclose(InvertedBM25(corpus).get_scores(["common", "rare"]),
                               BM25Okapi(corpus).get_scores(["common", "rare"]), rtol=1e-12)
