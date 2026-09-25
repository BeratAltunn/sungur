"""Degradation paths added for the real detector / real LLM."""

import json

import numpy as np
import pytest
from PIL import Image

from sentinel.agent.llm import CachedLLM, LLMResponse
from sentinel.domain.models import Detection
from sentinel.perception.cache import CachedDetector
from sentinel.perception.factory import _name_and_params, build_detector
from sentinel.pipeline import _to_meta_space
from sentinel.tracking.matcher import TrackMatcher


class _Seq:
    """LLM stub returning the given contents in order."""

    model = "stub"

    def __init__(self, *contents):
        self.contents = list(contents)
        self.calls = 0

    def chat(self, messages, *, json_mode=False, tools=None):
        self.calls += 1
        return LLMResponse(content=self.contents.pop(0), model=self.model)


def test_empty_llm_answer_is_not_cached(tmp_path):
    inner = _Seq("", '{"ok": 1}')
    llm = CachedLLM(inner, tmp_path, "ns")
    msgs = [{"role": "user", "content": "x"}]
    assert llm.chat(msgs).content == ""
    assert llm.chat(msgs).content == '{"ok": 1}'  # empty one was not reused
    assert llm.chat(msgs).cached and inner.calls == 2


def test_cache_key_depends_on_namespace(tmp_path):
    msgs = [{"role": "user", "content": "x"}]
    assert CachedLLM(_Seq(), tmp_path, "a|1400").key(msgs, True, None) != CachedLLM(
        _Seq(), tmp_path, "a|3000"
    ).key(msgs, True, None)


def test_detector_falls_back_to_cache_when_model_missing(settings, repo, tmp_path):
    s = settings.model_copy(deep=True)
    s.detector.kind = "ultralytics"
    s.detector.ultralytics.weights = str(tmp_path / "yok.pt")
    s.detector.cache_dir = tmp_path / "cache"
    with pytest.raises(RuntimeError):  # no model, no cache
        build_detector(s, repo)

    # write a cache entry under the exact fingerprint the factory will use
    name, params = _name_and_params(s)
    cached = CachedDetector(None, s.path(s.detector.cache_dir), name, params)
    cached.dir.mkdir(parents=True)
    det = Detection(det_id="D1", label="truck", conf=0.9, x=1, y=2, w=3, h=4)
    (cached.dir / "img_000860.json").write_text(json.dumps([det.model_dump()]))
    d = build_detector(s, repo)
    assert d.cache_only and "yok.pt" in d.load_error
    assert d.detect(repo.image_path("img_000860"))[0].label == "truck"
    with pytest.raises(RuntimeError):
        d.detect(repo.image_path("img_004530"))


def test_adaptive_gate_matches_big_box_but_not_small():
    m = TrackMatcher(gate_m=10)
    det = np.array([[0.0, 0.0], [100.0, 0.0]])
    trk = np.array([[13.0, 0.0], [113.0, 0.0]])
    res = m.match(det, trk, gates=np.array([15.0, 3.0]))  # big truck box vs. small car box
    assert [(p.det_idx, p.track_idx) for p in res.pairs] == [(0, 0)]


def test_boxes_are_rescaled_to_metadata_resolution(tmp_path):
    img = tmp_path / "a.jpg"
    Image.new("RGB", (1800, 1012)).save(img)
    det = Detection(det_id="D1", label="car", conf=0.9, x=100, y=50, w=40, h=20)
    out, note = _to_meta_space([det], img, 900, 506)
    assert note == "1800x1012 → 900x506"
    assert (out[0].x, out[0].y, out[0].w, out[0].h) == (50, 25, 20, 10)
    same, none = _to_meta_space([det], img, 1800, 1012)
    assert none is None and same[0].x == 100
