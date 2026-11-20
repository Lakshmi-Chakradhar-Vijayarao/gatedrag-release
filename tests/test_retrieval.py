from gatedrag.core.config import PipelineConfig
from gatedrag.data.corpus import chunk_text
from gatedrag.models.retrieval import rrf


def test_corpus_reads_acl_and_sections(chunks):
    billing = [c for c in chunks if c.doc_id == "orbit/billing"]
    assert billing and all(c.acl == ("finance",) for c in billing)
    assert {c.title for c in chunks if c.doc_id == "orbit/limits"} == {"Message limits", "Retention", "Visibility timeout"}


def test_chunking_respects_size():
    text = "\n\n".join(["word " * 100] * 10)
    parts = chunk_text(text, max_chars=600, overlap=50)
    assert len(parts) > 1 and all(len(p) <= 900 for p in parts)


def test_bm25_finds_the_right_document(retriever):
    hits = retriever.search("maximum message size", {"public"}, PipelineConfig())
    assert hits[0].chunk.doc_id == "orbit/limits"


def test_acl_pre_filter_never_returns_forbidden_docs(retriever):
    hits = retriever.search("how are enterprise contracts billed", {"public"}, PipelineConfig(acl_mode="pre"))
    assert all(h.chunk.doc_id != "orbit/billing" for h in hits)


def test_acl_off_leaks_and_finance_group_can_read(retriever):
    q = "how are enterprise contracts billed"
    assert retriever.search(q, {"public"}, PipelineConfig(acl_mode="off"))[0].chunk.doc_id == "orbit/billing"
    assert retriever.search(q, {"finance"}, PipelineConfig())[0].chunk.doc_id == "orbit/billing"


def test_acl_post_filter_drops_results_after_the_cut(retriever):
    q = "how are enterprise contracts billed"
    post = retriever.search(q, {"public"}, PipelineConfig(acl_mode="post", top_k=2))
    assert len(post) < 2 and all(h.chunk.doc_id != "orbit/billing" for h in post)


def test_rrf_rewards_agreement():
    s = rrf([[1, 2, 3], [2, 1, 3]])
    assert s[1] == s[2] > s[3]
