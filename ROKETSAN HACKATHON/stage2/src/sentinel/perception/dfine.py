"""Kaggle team's D-FINE-M checkpoint, run through transformers' DFineForObjectDetection.

The checkpoint comes from the original D-FINE/DEIM training code (keys like `decoder.decoder.layers.N`);
`convert_state_dict` renames those keys to the transformers layout and splits the fused attention
projections. Loading is strict: a key that does not map exactly is an error, never a silent re-init.
Inference uses the EMA weights, a plain cv2 linear resize to the training size and no mean/std
normalisation (the team's training/eval transform, confirmed by Ekip-1); one box per query (the best class), boxes in original image pixels.

Also exposes the Kaggle contract `predict(image_path) -> [(label, conf, x, y, w, h)]`.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from sentinel.config import DFineCfg
from sentinel.domain.models import Detection
from sentinel.perception.base import from_tuples
from sentinel.perception.fallback import _auto_device

# Original D-FINE → transformers key renames, applied in order (first match per rule, all rules).
_RULES: list[tuple[str, str]] = [
    # backbone (HGNetv2)
    (r"^backbone\.stem\.", "model.backbone.model.embedder."),
    (r"^backbone\.stages\.", "model.backbone.model.encoder.stages."),
    (r"^(model\.backbone\..*)\.conv\.", r"\1.convolution."),
    (r"^(model\.backbone\..*)\.bn\.", r"\1.normalization."),
    # hybrid encoder
    (r"^encoder\.input_proj\.(\d+)\.conv\.", r"model.encoder_input_proj.\1.0."),
    (r"^encoder\.input_proj\.(\d+)\.norm\.", r"model.encoder_input_proj.\1.1."),
    (r"^encoder\.((?:fpn|pan)_blocks\.\d+)\.cv1\.", r"model.encoder.\1.conv1."),
    (r"^encoder\.((?:fpn|pan)_blocks\.\d+)\.cv2\.0\.", r"model.encoder.\1.csp_rep1."),
    (r"^encoder\.((?:fpn|pan)_blocks\.\d+)\.cv2\.1\.", r"model.encoder.\1.conv2."),
    (r"^encoder\.((?:fpn|pan)_blocks\.\d+)\.cv3\.0\.", r"model.encoder.\1.csp_rep2."),
    (r"^encoder\.((?:fpn|pan)_blocks\.\d+)\.cv3\.1\.", r"model.encoder.\1.conv3."),
    (r"^encoder\.((?:fpn|pan)_blocks\.\d+)\.cv4\.", r"model.encoder.\1.conv4."),
    (r"^encoder\.downsample_convs\.(\d+)\.0\.cv1\.", r"model.encoder.downsample_convs.\1.conv1."),
    (r"^encoder\.downsample_convs\.(\d+)\.0\.cv2\.", r"model.encoder.downsample_convs.\1.conv2."),
    (r"^encoder\.", "model.encoder."),
    # decoder
    (r"^decoder\.decoder\.layers\.", "model.decoder.layers."),
    (r"^decoder\.decoder\.lqe_layers\.", "model.decoder.lqe_layers."),
    (r"^decoder\.decoder\.(up|reg_scale)$", r"model.decoder.\1"),
    (r"^decoder\.dec_score_head\.", "model.decoder.class_embed."),
    (r"^decoder\.dec_bbox_head\.", "model.decoder.bbox_embed."),
    (r"^decoder\.(pre_bbox_head|query_pos_head)\.", r"model.decoder.\1."),
    (r"^decoder\.enc_output\.proj\.", "model.enc_output.0."),
    (r"^decoder\.enc_output\.norm\.", "model.enc_output.1."),
    (r"^decoder\.(enc_score_head|enc_bbox_head|denoising_class_embed)\.", r"model.\1."),
    # transformer layers (encoder + decoder share the naming)
    (r"\.cross_attn\.", ".encoder_attn."),
    (r"\.linear1\.", ".fc1."),
    (r"\.linear2\.", ".fc2."),
    (r"^(model\.encoder\.encoder\..*)\.norm1\.", r"\1.self_attn_layer_norm."),
    (r"^(model\.encoder\.encoder\..*)\.norm2\.", r"\1.final_layer_norm."),
    (r"^(model\.decoder\.layers\..*)\.norm1\.", r"\1.self_attn_layer_norm."),
    (r"^(model\.decoder\.layers\..*)\.norm3\.", r"\1.final_layer_norm."),
]
# Buffers the original code stores but transformers recomputes (anchors for the eval size) or skips.
_DROP = re.compile(r"num_batches_tracked$|^decoder\.(anchors|valid_mask|up|reg_scale)$")


def convert_state_dict(sd: dict) -> dict:
    out = {}
    for key, value in sd.items():
        if _DROP.search(key):
            continue
        new = key
        for pat, rep in _RULES:
            new = re.sub(pat, rep, new)
        if new.endswith("self_attn.in_proj_weight") or new.endswith("self_attn.in_proj_bias"):
            kind = "weight" if new.endswith("weight") else "bias"
            base = new.rsplit(".", 1)[0]
            for name, part in zip(("q_proj", "k_proj", "v_proj"), value.chunk(3, dim=0), strict=True):
                out[f"{base}.{name}.{kind}"] = part
            continue
        out[new] = value
    # the detection head is exposed twice (model.decoder.* and top level); both point to the same weights
    for k in list(out):
        if k.startswith(("model.decoder.class_embed.", "model.decoder.bbox_embed.")):
            out[k.removeprefix("model.decoder.")] = out[k]
    return out


def build_model(cfg: DFineCfg, weights_path: Path):
    try:
        import torch
        from transformers import DFineConfig, DFineForObjectDetection, HGNetV2Config
    except ImportError as e:  # pragma: no cover - depends on optional extra
        raise RuntimeError("D-FINE için torch + transformers gerekli: `pip install -e '.[detector]'`") from e

    ckpt = torch.load(weights_path, map_location="cpu", weights_only=True)
    sd = ckpt["ema"]["module"] if "ema" in ckpt else ckpt.get("model", ckpt)
    n_cls = sd["decoder.enc_score_head.weight"].shape[0]
    if n_cls != len(cfg.class_names):
        raise ValueError(f"model {n_cls} sınıf veriyor, config.yaml class_names {len(cfg.class_names)} tane")

    # D-FINE-M: HGNetv2-B2 backbone, 4 decoder layers, depth 0.67 (the key shapes pin this down)
    backbone = HGNetV2Config(
        stem_channels=[3, 24, 32],
        stage_in_channels=[32, 96, 384, 768],
        stage_mid_channels=[32, 64, 128, 256],
        stage_out_channels=[96, 384, 768, 1536],
        stage_num_blocks=[1, 1, 3, 1],
        stage_downsample=[False, True, True, True],
        stage_light_block=[False, False, True, True],
        stage_kernel_size=[3, 3, 5, 5],
        stage_numb_of_layers=[4, 4, 4, 4],
        use_learnable_affine_block=True,
        hidden_sizes=[96, 384, 768, 1536],
        depths=[1, 1, 3, 1],
        out_features=["stage2", "stage3", "stage4"],
    )
    size = list(cfg.input_size)
    config = DFineConfig(
        backbone_config=backbone,
        encoder_in_channels=[384, 768, 1536],
        depth_mult=0.67,
        decoder_layers=4,
        decoder_n_points=[3, 6, 3],
        num_labels=n_cls,
        # eval_size is left unset: transformers 4.55 then skips the encoder's position embedding
        # (UnboundLocalError); computed on the fly it is identical for the same input size
        anchor_image_size=size,
    )
    model = DFineForObjectDetection(config)
    model.load_state_dict(convert_state_dict(sd), strict=True)
    return model.eval()


class DFineDetector:
    def __init__(self, cfg: DFineCfg, weights_path: Path):
        import torch

        self.cfg = cfg
        self.torch = torch
        self.model = build_model(cfg, weights_path)
        self.device = cfg.device or _auto_device()
        self.model.to(self.device)
        self.name = f"dfine:{Path(weights_path).stem}"

    def predict(self, image_path: Path) -> list[tuple]:
        import cv2
        import numpy as np
        from PIL import Image

        torch = self.torch
        img = Image.open(image_path).convert("RGB")
        w0, h0 = img.size
        h, w = self.cfg.input_size
        # exactly the training transform (Ekip-1): cv2 linear resize, no antialias (unlike PIL), no letterbox
        arr = cv2.resize(np.asarray(img), (w, h), interpolation=cv2.INTER_LINEAR)
        x = arr.astype(np.float32) / 255.0
        pixel_values = torch.from_numpy(x).permute(2, 0, 1)[None].to(self.device)
        with torch.no_grad():
            out = self.model(pixel_values=pixel_values)
        scores, cls = out.logits[0].sigmoid().max(dim=-1)  # one box per query: its best class
        boxes = out.pred_boxes[0]  # cx, cy, w, h normalised to the image
        keep = scores >= self.cfg.min_conf
        rows = []
        for (cx, cy, bw, bh), s, c in zip(
            boxes[keep].cpu().tolist(), scores[keep].cpu().tolist(), cls[keep].cpu().tolist(), strict=True
        ):
            rows.append(
                (self.cfg.class_names[c], s, (cx - bw / 2) * w0, (cy - bh / 2) * h0, bw * w0, bh * h0)
            )
        return sorted(rows, key=lambda r: -r[1])

    def detect(self, image_path: Path) -> list[Detection]:
        return from_tuples(self.predict(image_path))


@lru_cache(maxsize=1)
def _default() -> DFineDetector:
    from sentinel.config import load_settings

    s = load_settings()
    return DFineDetector(s.detector.dfine, s.path(s.detector.dfine.weights))


def predict(image_path) -> list[tuple]:
    """Kaggle contract (PROJECT_DESIGN §4.2): [(label, conf, x, y, w, h)], px, top-left."""
    return _default().predict(Path(image_path))
