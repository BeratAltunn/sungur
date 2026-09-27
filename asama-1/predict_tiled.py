"""Tiled (SAHI-style) inference: crop overlapping tiles, run each at full model
resolution, map boxes back to source coordinates, merge with per-class NMS.

Rationale: 38% of GT boxes are under 1024 px^2 and the floor is 200 px^2. A whole
1360x765 frame resized to 1408x800 gives a vehicle ~1x magnification; a 2x2 tile
of it gives ~1.7x, so small vehicles land on more feature-map cells.

Details that matter:
  * overlap  - objects straddling a tile seam would be cut in half, so tiles
               overlap and any detection touching a tile border that is NOT also
               the image border is dropped (it is a truncated duplicate; the
               neighbouring tile sees the whole object).
  * merge    - the full-image pass is ALWAYS included, so large vehicles (a bus
               spanning more than one tile) are never lost.
  * NMS      - per class, on source coordinates.

Usage:
  python predict_tiled.py --weights ckpt.pth --images <dir> --sample sample.csv \
      --classes car,truck,van,bus --grid 2x2 --overlap 0.2 --out sub_tiled.csv
"""
import os, csv, glob, argparse, time
import numpy as np
import cv2
import torch
import torchvision
from PIL import Image

from engine.core import YAMLConfig


def build(cfg_path, ckpt_path, device, weights="ema", nq=None):
    cfg = YAMLConfig(cfg_path)
    if nq:
        cfg.yaml_cfg["PostProcessor"]["num_top_queries"] = nq
    ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    state = ckpt["ema"]["module"] if (weights == "ema" and "ema" in ckpt) else ckpt["model"]
    missing, unexpected = cfg.model.load_state_dict(state, strict=False)
    missing = [k for k in missing if "num_batches_tracked" not in k]
    print("  load_state_dict:", "exact match" if not (missing or unexpected)
          else f"{len(missing)} missing / {len(unexpected)} unexpected")
    return cfg.model.deploy().to(device).eval(), cfg.postprocessor.deploy().to(device).eval()


def tiles_for(ow, oh, rows, cols, ov):
    """list of (x0,y0,x1,y1) covering the image with fractional overlap ov"""
    if rows == 1 and cols == 1:
        return [(0, 0, ow, oh)]
    tw, th = ow / cols, oh / rows
    ex, ey = tw * ov / 2, th * ov / 2
    out = []
    for r in range(rows):
        for c in range(cols):
            x0 = max(0, int(c * tw - ex)); x1 = min(ow, int((c + 1) * tw + ex))
            y0 = max(0, int(r * th - ey)); y1 = min(oh, int((r + 1) * th + ey))
            out.append((x0, y0, x1, y1))
    return out


@torch.no_grad()
def infer_image(model, post, arr, W, H, device, tilespec, ov, amp, edge_px=3):
    """arr: HxWx3 RGB uint8. -> (boxes xyxy source coords, scores, labels)"""
    oh, ow = arr.shape[:2]
    allb, alls, alll = [], [], []
    views = [(0, 0, ow, oh)]                      # full image always included
    for rows, cols in tilespec:
        if (rows, cols) != (1, 1):
            views += tiles_for(ow, oh, rows, cols, ov)
    for (x0, y0, x1, y1) in views:
        crop = arr[y0:y1, x0:x1]
        ch, cw = crop.shape[:2]
        if ch < 8 or cw < 8:
            continue
        t = cv2.resize(crop, (W, H), interpolation=cv2.INTER_LINEAR)
        t = torch.from_numpy(t).permute(2, 0, 1).float().div_(255.).unsqueeze(0).to(device)
        sz = torch.tensor([[cw, ch]], dtype=torch.float32, device=device)
        with torch.autocast("cuda", dtype=torch.float16, enabled=amp and device.startswith("cuda")):
            lab, box, sco = post(model(t), sz)
        b = box[0].float().cpu().numpy()
        s = sco[0].float().cpu().numpy()
        l = lab[0].int().cpu().numpy()
        b[:, 0::2] = b[:, 0::2].clip(0, cw)
        b[:, 1::2] = b[:, 1::2].clip(0, ch)
        if (x0, y0, x1, y1) != (0, 0, ow, oh):
            # drop detections truncated by a tile seam (kept if the seam is the image edge)
            keep = np.ones(len(b), bool)
            if x0 > 0:   keep &= b[:, 0] > edge_px
            if y0 > 0:   keep &= b[:, 1] > edge_px
            if x1 < ow:  keep &= b[:, 2] < cw - edge_px
            if y1 < oh:  keep &= b[:, 3] < ch - edge_px
            b, s, l = b[keep], s[keep], l[keep]
        b[:, 0::2] += x0
        b[:, 1::2] += y0
        allb.append(b); alls.append(s); alll.append(l)
    if not allb:
        return np.zeros((0, 4)), np.zeros(0), np.zeros(0, int)
    return np.concatenate(allb), np.concatenate(alls), np.concatenate(alll)


def per_class_nms(b, s, l, iou, topk, device):
    if len(b) == 0:
        return b, s, l
    tb = torch.from_numpy(b).float().to(device)
    ts = torch.from_numpy(s).float().to(device)
    tl = torch.from_numpy(l).long().to(device)
    keep = torchvision.ops.batched_nms(tb, ts, tl, iou).cpu().numpy()
    keep = keep[np.argsort(-s[keep])][:topk]
    return b[keep], s[keep], l[keep]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cfg", default="configs/deim_dfine/infer_ep12.yml")
    ap.add_argument("--weights", required=True)
    ap.add_argument("--images", required=True)
    ap.add_argument("--sample", default=None)
    ap.add_argument("--classes", required=True)
    ap.add_argument("--out", default="submission_tiled.csv")
    ap.add_argument("--size", default="800x1408")
    ap.add_argument("--grid", default="2x2", help="e.g. 2x2, or 2x2+3x3 for both")
    ap.add_argument("--overlap", type=float, default=0.2)
    ap.add_argument("--nms", type=float, default=0.6)
    ap.add_argument("--conf", type=float, default=0.01)
    ap.add_argument("--topk", type=int, default=600)
    ap.add_argument("--nq", type=int, default=None)
    ap.add_argument("--amp", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--device", default="cuda:0" if torch.cuda.is_available() else "cpu")
    a = ap.parse_args()

    H, W = (int(v) for v in a.size.lower().split("x"))
    tilespec = [tuple(int(x) for x in g.split("x")) for g in a.grid.split("+")]
    print(f"building @ {W}x{H} on {a.device}; grid={tilespec} overlap={a.overlap} "
          f"nms={a.nms} topk={a.topk}")
    model, post = build(a.cfg, a.weights, a.device, "ema", a.nq)

    paths = sorted(glob.glob(os.path.join(a.images, "*.jpg")))
    if a.limit:
        paths = paths[:a.limit]
    npass = 1 + sum(r * c for r, c in tilespec if (r, c) != (1, 1))
    print(f"{len(paths)} images, {npass} forward passes each")

    idx2name = {i: n for i, n in enumerate(a.classes.split(","))}
    res = {}
    t0 = time.time()
    for i, p in enumerate(paths):
        arr = np.asarray(Image.open(p).convert("RGB"))
        b, s, l = infer_image(model, post, arr, W, H, a.device, tilespec, a.overlap, a.amp)
        m = s >= a.conf
        b, s, l = b[m], s[m], l[m]
        b, s, l = per_class_nms(b, s, l, a.nms, a.topk, a.device)
        res[os.path.splitext(os.path.basename(p))[0]] = (b, s, l)
        if (i + 1) % 100 == 0:
            el = time.time() - t0; r = (i + 1) / el
            print(f"  {i+1}/{len(paths)}  {el:.0f}s  {r:.2f} img/s  eta {(len(paths)-i-1)/r:.0f}s", flush=True)

    ids = ([r["image_id"] for r in csv.DictReader(open(a.sample))] if a.sample
           else sorted(res))
    nb = 0
    with open(a.out, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["image_id", "PredictionString"])
        for iid in ids:
            if iid not in res:
                w.writerow([iid, "none"]); continue
            b, s, l = res[iid]
            parts = []
            for k in np.argsort(-s):
                x1, y1, x2, y2 = b[k]
                bw, bh = x2 - x1, y2 - y1
                if bw <= 0 or bh <= 0:
                    continue
                parts += [idx2name[int(l[k])], f"{s[k]:.4f}",
                          f"{x1:.1f}", f"{y1:.1f}", f"{bw:.1f}", f"{bh:.1f}"]
            nb += len(parts) // 6
            w.writerow([iid, " ".join(parts) if parts else "none"])
    print(f"\nwrote {a.out}: {len(ids)} rows, {nb} boxes ({nb/max(1,len(ids)):.1f}/img)")


if __name__ == "__main__":
    main()
