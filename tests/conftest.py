from pathlib import Path

import pytest

from gatedrag.core.config import load_config
from gatedrag.data.corpus import load_corpus
from gatedrag.evaluation.golden import load_golden
from gatedrag.models.generation import ExtractiveFakeGenerator
from gatedrag.models.pipeline import Pipeline
from gatedrag.models.retrieval import Retriever

ROOT = Path(__file__).parent.parent
FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def chunks():
    return load_corpus(FIX / "corpus")


@pytest.fixture(scope="session")
def retriever(chunks):
    return Retriever(chunks)


@pytest.fixture(scope="session")
def golden():
    return load_golden(FIX / "golden_synthetic.jsonl")


@pytest.fixture
def base_cfg():
    return load_config(ROOT / "configs" / "release.toml")


@pytest.fixture
def make_pipeline(retriever):
    def _make(cfg, audit=None):
        return Pipeline(retriever, ExtractiveFakeGenerator(), cfg, audit)
    return _make
