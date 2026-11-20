from gatedrag.evaluation.judge import judge_pool, parse
from gatedrag.evaluation.runner import run_pool
from gatedrag.models.generation import GenResult


class StubJudge:
    name = "stub-judge"

    def __init__(self, verdict):
        self.verdict, self.prompts = verdict, []

    def generate(self, messages, temperature, max_tokens, seed=None):
        self.prompts.append(messages[0]["content"])
        return GenResult(self.verdict, 1, 1, 0.0)


def test_parse():
    assert parse(" correct.") == 1 and parse("INCORRECT") == 0 and parse("maybe") is None


def test_judge_scores_only_shipped_answerable_answers(make_pipeline, base_cfg, golden):
    pool = run_pool(make_pipeline(base_cfg.with_(temperature=0.7)), golden, k=2)
    judge = StubJudge("INCORRECT")
    out = judge_pool(pool, golden, judge, concurrency=2)
    by_id = {g.id: g for g in golden}
    for scores, recs in zip(out["runs"], out["records"], strict=True):
        for item_id, sc, rec in zip(out["meta"]["item_ids"], scores, recs, strict=True):
            if by_id[item_id].answerable and rec["decision"] != "ABSTAIN":
                assert sc["correct_judge"] == 0.0
            else:
                assert sc["correct_judge"] == sc["correct"]
    assert out["meta"]["judge"]["judged"] == len(judge.prompts) > 0
    assert "Reference" in judge.prompts[0]


def test_unparsed_verdict_falls_back_and_is_counted(make_pipeline, base_cfg, golden):
    pool = run_pool(make_pipeline(base_cfg), golden, k=1)
    out = judge_pool(pool, golden, StubJudge("hmm"), concurrency=1)
    assert out["meta"]["judge"]["unparsed"] == out["meta"]["judge"]["judged"]


def test_openai_generator_reads_token_logprobs():
    import httpx

    from gatedrag.models.generation import OpenAICompatibleGenerator

    def handler(request):
        body = {"choices": [{"message": {"content": "4222"},
                             "logprobs": {"content": [{"token": "42", "logprob": -0.1}, {"token": "22", "logprob": -0.3}]}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2}}
        return httpx.Response(200, json=body)

    gen = OpenAICompatibleGenerator("http://test", "m")
    gen._client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))
    out = gen.generate([{"role": "user", "content": "port?"}], temperature=0.0, max_tokens=4)
    assert out.text == "4222" and abs(out.mean_logprob - (-0.2)) < 1e-9


def test_citation_only_answers_are_wrong_without_a_judge_call():
    from gatedrag.evaluation.judge import apply_content_rule, has_content

    assert not has_content("[1]")
    assert not has_content(" [2] [1]. ")
    assert has_content("[1] 7422")
    assert has_content("Port 4222 [1]")
    pool = {"meta": {}, "runs": [[{"answerable": 1.0, "abstained": 0.0, "correct": 0.0, "correct_judge": 1.0},
                                  {"answerable": 1.0, "abstained": 0.0, "correct": 1.0, "correct_judge": 1.0}]],
            "records": [[{"answer": "[1]"}, {"answer": "[1] 7422"}]]}
    assert apply_content_rule(pool) == 1
    assert [s["correct_judge"] for s in pool["runs"][0]] == [0.0, 1.0]
