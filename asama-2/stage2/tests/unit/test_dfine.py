"""Kaggle team's D-FINE checkpoint → transformers: key mapping, strict load, demo truck."""

from __future__ import annotations

import pytest

from sentinel.perception.factory import _name_and_params

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")

from sentinel.perception.dfine import DFineDetector, convert_state_dict  # noqa: E402


def test_convert_state_dict_renames_and_splits_attention():
    sd = {
        "backbone.stem.stem1.conv.weight": torch.zeros(1),
        "backbone.stages.2.blocks.0.layers.0.conv2.bn.running_var": torch.zeros(1),
        "backbone.stages.2.blocks.0.layers.0.conv2.bn.num_batches_tracked": torch.zeros(()),
        "encoder.fpn_blocks.0.cv2.1.conv.weight": torch.zeros(1),
        "encoder.downsample_convs.1.0.cv2.norm.bias": torch.zeros(1),
        "encoder.encoder.0.layers.0.norm2.weight": torch.zeros(1),
        "decoder.decoder.layers.3.self_attn.in_proj_weight": torch.arange(6.0).reshape(6, 1),
        "decoder.decoder.layers.3.cross_attn.num_points_scale": torch.zeros(1),
        "decoder.decoder.layers.3.norm3.bias": torch.zeros(1),
        "decoder.dec_score_head.0.weight": torch.zeros(1),
        "decoder.enc_output.norm.weight": torch.zeros(1),
        "decoder.anchors": torch.zeros(1),
    }
    out = convert_state_dict(sd)
    assert set(out) == {
        "model.backbone.model.embedder.stem1.convolution.weight",
        "model.backbone.model.encoder.stages.2.blocks.0.layers.0.conv2.normalization.running_var",
        "model.encoder.fpn_blocks.0.conv2.conv.weight",
        "model.encoder.downsample_convs.1.conv2.norm.bias",
        "model.encoder.encoder.0.layers.0.final_layer_norm.weight",
        "model.decoder.layers.3.self_attn.q_proj.weight",
        "model.decoder.layers.3.self_attn.k_proj.weight",
        "model.decoder.layers.3.self_attn.v_proj.weight",
        "model.decoder.layers.3.encoder_attn.num_points_scale",
        "model.decoder.layers.3.final_layer_norm.bias",
        "model.decoder.class_embed.0.weight",
        "class_embed.0.weight",  # the top-level head shares these weights
        "model.enc_output.1.weight",
    }
    # fused q/k/v are split in that order
    assert out["model.decoder.layers.3.self_attn.k_proj.weight"].flatten().tolist() == [2.0, 3.0]


def test_cache_key_changes_with_class_order(settings):
    # a wrong class order must never reuse boxes cached under the right one (and vice versa)
    a = settings.model_copy(deep=True)
    a.detector.kind = "dfine"
    b = a.model_copy(deep=True)
    b.detector.dfine.class_names = list(reversed(a.detector.dfine.class_names))
    assert _name_and_params(a) != _name_and_params(b)


def test_checkpoint_loads_strictly_and_sees_the_demo_truck(settings, repo):
    weights = settings.path(settings.detector.dfine.weights)
    image = repo.image_path("img_000860")
    if not weights.exists() or not image.exists():
        pytest.skip("D-FINE ağırlıkları ya da resmî görüntüler yok")
    if repo.meta["img_000860"].width_px != 960:
        pytest.skip("resmî veri paketi gerekli (dev görüntüleri 900x506)")
    det = DFineDetector(settings.detector.dfine, weights)  # strict load: any unmapped key raises
    anchors = det.model.model.anchors.cpu()
    ref = torch.load(weights, map_location="cpu", weights_only=True)["ema"]["module"]["decoder.anchors"]
    finite = torch.isfinite(ref) & torch.isfinite(anchors)
    assert torch.allclose(anchors[finite], ref[finite], atol=1e-4)  # same input size as training

    rows = det.predict(image)
    # organiser's worked example: the truck (T0122) at pixel (756, 301)
    trucks = [
        r for r in rows if r[0] == "truck" and r[2] <= 756 <= r[2] + r[4] and r[3] <= 301 <= r[3] + r[5]
    ]
    assert trucks
