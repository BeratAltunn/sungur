from __future__ import annotations

import pytest

from sentinel.agent.llm import MockLLM
from sentinel.config import load_settings
from sentinel.data.repository import Repository
from sentinel.perception.oracle import OracleDetector
from sentinel.pipeline import Pipeline
from sentinel.service import SentinelService


@pytest.fixture(scope="session")
def settings(tmp_path_factory):
    s = load_settings()
    s.detector.kind = "oracle"
    s.llm.cache = False
    s.observability.runs_dir = tmp_path_factory.mktemp("runs")
    s.observability.labels_dir = tmp_path_factory.mktemp("labels")
    return s


@pytest.fixture(scope="session")
def repo(settings) -> Repository:
    return Repository(settings.data_path, settings.images_subdir)


@pytest.fixture(scope="session")
def pipeline(settings, repo) -> Pipeline:
    return Pipeline(settings, repo, OracleDetector(repo))


@pytest.fixture(scope="session")
def packet_860(pipeline):
    return pipeline.evaluate("img_000860")


@pytest.fixture
def service(settings) -> SentinelService:
    return SentinelService(settings, llm=MockLLM())
