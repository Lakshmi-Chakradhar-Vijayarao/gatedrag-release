"""Hybrid retrieval: BM25 + optional dense, reciprocal-rank fusion, optional cross-encoder rerank,
with access control applied BEFORE ranking (acl_mode='pre').

acl_mode='post' (filter after the top-k cut) and 'off' (no filter) exist only so the release gate
can be tested against them as planted regressions.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from gatedrag.core.config import PipelineConfig
from gatedrag.data.corpus import Chunk
from gatedrag.models.bm25 import InvertedBM25

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float
    rank: int


def rrf(rankings: Sequence[Sequence[int]], k: int = 60) -> dict[int, float]:
    """Reciprocal-rank fusion of several ranked lists of chunk indices."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for r, idx in enumerate(ranking):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + r + 1)
    return scores


class Retriever:
    def __init__(
        self,
        chunks: list[Chunk],
        embed: Callable[[list[str]], np.ndarray] | None = None,
        rerank: Callable[[str, list[str]], list[float]] | None = None,
    ):
        if not chunks:
            raise ValueError("empty corpus")
        self.chunks = chunks
        self._bm25 = InvertedBM25([tokenize(c.title + " " + c.text) for c in chunks])
        self._embed = embed
        self._rerank = rerank
        self._emb: np.ndarray | None = None
        if embed is not None:
            m = np.asarray(embed([c.title + "\n" + c.text for c in chunks]), dtype=float)
            self._emb = m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-12)

    def search(self, query: str, groups: set[str], cfg: PipelineConfig) -> list[Hit]:
        n = len(self.chunks)
        if cfg.acl_mode == "pre":
            pool = [i for i in range(n) if self.chunks[i].readable_by(groups)]
        else:
            pool = list(range(n))
        if not pool:
            return []
        pool_arr = np.asarray(pool)
        rankings = []
        if cfg.use_bm25:
            s = self._bm25.get_scores(tokenize(query))[pool_arr]
            rankings.append(list(pool_arr[np.argsort(-s, kind="stable")][: cfg.candidate_k]))
        if cfg.use_dense:
            if self._emb is None:
                raise RuntimeError("use_dense=True but the retriever was built without an embedder")
            assert self._embed is not None
            q = np.asarray(self._embed([query]), dtype=float)[0]
            q = q / max(np.linalg.norm(q), 1e-12)
            s = self._emb[pool_arr] @ q
            rankings.append(list(pool_arr[np.argsort(-s, kind="stable")][: cfg.candidate_k]))
        if not rankings:
            raise ValueError("enable at least one of use_bm25 / use_dense")
        fused = sorted(rrf(rankings).items(), key=lambda kv: (-kv[1], kv[0]))[: cfg.candidate_k]
        idxs, scores = [i for i, _ in fused], [s for _, s in fused]
        if cfg.use_rerank:
            if self._rerank is None:
                raise RuntimeError("use_rerank=True but no reranker was provided")
            rs = self._rerank(query, [self.chunks[i].text for i in idxs])
            order = sorted(range(len(idxs)), key=lambda j: -rs[j])
            idxs, scores = [idxs[j] for j in order], [float(rs[j]) for j in order]
        top = list(zip(idxs, scores, strict=True))[: cfg.top_k]
        if cfg.acl_mode == "post":
            top = [(i, s) for i, s in top if self.chunks[i].readable_by(groups)]
        return [Hit(self.chunks[i], float(s), r) for r, (i, s) in enumerate(top)]


def sentence_transformer_embedder(model_name: str = "sentence-transformers/multi-qa-MiniLM-L6-cos-v1",
                                  cache_dir: str | None = None):
    """Embedding function. With cache_dir, batches of >1 text (the corpus) are cached on disk keyed
    by a hash of model name + texts, so restarts don't re-embed the corpus."""
    import hashlib
    import os

    from sentence_transformers import SentenceTransformer  # optional dependency

    model = SentenceTransformer(model_name)

    def embed(texts):
        if cache_dir and len(texts) > 1:
            h = hashlib.sha256((model_name + "\x00" + "\x00".join(texts)).encode()).hexdigest()[:16]
            path = os.path.join(cache_dir, f"emb_{h}.npy")
            if os.path.exists(path):
                return np.load(path)
            os.makedirs(cache_dir, exist_ok=True)
            arr = model.encode(texts, batch_size=32, show_progress_bar=False)
            np.save(path, arr)
            return arr
        return model.encode(texts, batch_size=32, show_progress_bar=False)

    return embed


def cross_encoder_reranker(model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
    from sentence_transformers import CrossEncoder  # optional dependency

    model = CrossEncoder(model_name)
    return lambda q, texts: list(model.predict([(q, t) for t in texts]))
