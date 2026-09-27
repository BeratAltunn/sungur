"""Run a D-FINE checkpoint over a folder of images and write the Kaggle submission CSV.

Deliberately does NOT import inference.py / inference_tools.model -- both import
`tensorrt` at module level, which is not installed here.

Preprocessing mirrors the config's val_dataloader exactly:
    PIL open (RGB) -> np.array -> cv2.resize((W, H), INTER_LINEAR) -> /255, CHW
i.e. ResizeCV(bilinear) + ToTensor. No mean/std normalisation.

Two modes:
  --calibrate  run on train images with known GT and recover the class-index order
  (default)    run on test images and write submission.csv
"""
import os, csv, json, glob, argparse, collections, time
import numpy as np
import cv2
import torch
from PIL import Image

from engine.core import YAMLConfig


def build(cfg_path, ckpt_path, device, weights='ema', nq=None):
    cfg = YAMLConfig(cfg_path)
    if nq:
        cfg.yaml_cfg['PostProcessor']['num_top_queries'] = nq
        print(f'  num_top_queries -> {nq}')
    ckpt = torch.load(ckpt_path, map_location='cpu', weights_only=False)
    if weights == 'ema' and 'ema' in ckpt:
        state, used = ckpt['ema']['module'], 'ema'
    else:
        state, used = ckpt['model'], 'model'
    missing, unexpected = cfg.model.load_state_dict(state, strict=False)
    missing = [k for k in missing if 'num_batches_tracked' not in k]
    if missing or unexpected:
        print(f'  load_state_dict: {len(missing)} missing, {len(unexpected)} unexpected')
        for k in (missing + unexpected)[:10]:
            print('    ', k)
    else:
        print('  load_state_dict: exact match')
    model = cfg.model.deploy().to(device).eval()
    post = cfg.postprocessor.deploy().to(device).eval()   # deploy -> (labels, boxes, scores)
    print(f'  weights={used}  last_epoch={ckpt.get("last_epoch")}')
    return model, post


def preprocess(path, W, H, device):
    im = Image.open(path).convert('RGB')
    ow, oh = im.size
    arr = np.asarray(im)
    arr = cv2.resize(arr, (W, H), interpolation=cv2.INTER_LINEAR)
    t = torch.from_numpy(arr).permute(2, 0, 1).float().div_(255.).unsqueeze(0).to(device)
    return t, torch.tensor([[ow, oh]], dtype=torch.float32, device=device), (ow, oh)


@torch.no_grad()
def infer(model, post, paths, W, H, device, amp, conf, log_every=200):
    out = {}
    t0 = time.time()
    for i, p in enumerate(paths):
        img, orig, (ow, oh) = preprocess(p, W, H, device)
        with torch.autocast('cuda', dtype=torch.float16, enabled=amp and device.startswith('cuda')):
            labels, boxes, scores = post(model(img), orig)
        lab = labels[0].int().cpu().numpy()
        box = boxes[0].float().cpu().numpy()
        sco = scores[0].float().cpu().numpy()
        keep = sco >= conf
        lab, box, sco = lab[keep], box[keep], sco[keep]
        box[:, 0::2] = box[:, 0::2].clip(0, ow)
        box[:, 1::2] = box[:, 1::2].clip(0, oh)
        out[os.path.splitext(os.path.basename(p))[0]] = (lab, box, sco)
        if log_every and (i + 1) % log_every == 0:
            el = time.time() - t0
            rate = (i + 1) / el
            print(f'  {i+1}/{len(paths)}  {el:.0f}s  {rate:.1f} img/s  eta {(len(paths)-i-1)/rate:.0f}s', flush=True)
    return out


def load_gt(ann_csv):
    gt = collections.defaultdict(list)
    with open(ann_csv) as f:
        for r in csv.DictReader(f):
            x, y, w, h = int(r['x']), int(r['y']), int(r['w']), int(r['h'])
            gt[r['image_id']].append((x, y, x + w, y + h, r['label']))
    return gt


def iou_mat(a, b):
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    a, b = np.asarray(a, float), np.asarray(b, float)
    x1 = np.maximum(a[:, None, 0], b[None, :, 0]); y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2]); y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    aa = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    bb = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / (aa[:, None] + bb[None, :] - inter + 1e-9)


def calibrate(preds, gt, names):
    """Match GT to confident preds by IoU, then assign class indices to names."""
    conf = np.zeros((len(names), 4), dtype=np.int64)   # gt name x pred index
    ni = {n: i for i, n in enumerate(names)}
    for iid, (lab, box, sco) in preds.items():
        g = gt.get(iid, [])
        if not g:
            continue
        keep = sco >= 0.4
        pb, pl = box[keep], lab[keep]
        if len(pb) == 0:
            continue
        M = iou_mat([b[:4] for b in g], pb)
        for gi, row in enumerate(M):
            pi = int(row.argmax())
            if row[pi] >= 0.6:
                conf[ni[g[gi][4]], int(pl[pi])] += 1
    # greedy Hungarian over a 4x4 -- brute force all 24 permutations
    import itertools
    best, bestp = -1, None
    for perm in itertools.permutations(range(4)):
        s = sum(conf[i, perm[i]] for i in range(4))
        if s > best:
            best, bestp = s, perm
    mapping = {bestp[i]: names[i] for i in range(4)}
    agree = best / max(1, conf.sum())
    return conf, mapping, agree


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cfg', default='configs/deim_dfine/infer_ep12.yml')
    ap.add_argument('--weights', required=True)
    ap.add_argument('--which', default='ema', choices=['ema', 'model'])
    ap.add_argument('--images', required=True)
    ap.add_argument('--out', default='submission.csv')
    ap.add_argument('--sample', default=None, help='sample_submission.csv -- fixes row order/ids')
    ap.add_argument('--conf', type=float, default=0.01)
    ap.add_argument('--size', default='800x1408', help='HxW')
    ap.add_argument('--amp', action='store_true')
    ap.add_argument('--device', default='cuda:0' if torch.cuda.is_available() else 'cpu')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--calibrate', default=None, help='path to train annotations.csv')
    ap.add_argument('--classes', default=None, help='comma-separated index order, e.g. car,van,truck,bus')
    ap.add_argument('--json_out', default=None)
    ap.add_argument('--nq', type=int, default=None, help='override PostProcessor.num_top_queries')
    a = ap.parse_args()

    H, W = (int(v) for v in a.size.lower().split('x'))
    print(f'building model @ {W}x{H} on {a.device}')
    model, post = build(a.cfg, a.weights, a.device, a.which, a.nq)

    paths = sorted(glob.glob(os.path.join(a.images, '*.jpg')))
    if a.limit:
        paths = paths[:a.limit]
    print(f'{len(paths)} images')

    preds = infer(model, post, paths, W, H, a.device, a.amp, a.conf)

    if a.calibrate:
        gt = load_gt(a.calibrate)
        names = ['car', 'van', 'truck', 'bus']
        conf, mapping, agree = calibrate(preds, gt, names)
        print('\nconfusion (rows = GT name, cols = predicted index 0..3):')
        print('          ' + ''.join(f'{i:>8}' for i in range(4)))
        for i, n in enumerate(names):
            print(f'{n:>10}' + ''.join(f'{v:>8}' for v in conf[i]))
        print(f'\nrecovered mapping: {{' + ', '.join(f'{k}: {mapping[k]}' for k in sorted(mapping)) + '}')
        print(f'agreement on matched boxes: {agree:.1%}')
        print('--classes ' + ','.join(mapping[i] for i in range(4)))
        return

    if not a.classes:
        raise SystemExit('--classes required (run --calibrate first)')
    idx2name = {i: n for i, n in enumerate(a.classes.split(','))}

    if a.sample:
        with open(a.sample) as f:
            ids = [r['image_id'] for r in csv.DictReader(f)]
    else:
        ids = sorted(preds)

    nbox = 0
    missing = 0
    with open(a.out, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['image_id', 'PredictionString'])
        for iid in ids:
            if iid not in preds:
                w.writerow([iid, 'none']); missing += 1; continue
            lab, box, sco = preds[iid]
            order = np.argsort(-sco)
            parts = []
            for k in order:
                x1, y1, x2, y2 = box[k]
                bw, bh = x2 - x1, y2 - y1
                if bw <= 0 or bh <= 0:
                    continue
                parts += [idx2name[int(lab[k])], f'{sco[k]:.4f}',
                          f'{x1:.0f}', f'{y1:.0f}', f'{bw:.0f}', f'{bh:.0f}']
            nbox += len(parts) // 6
            w.writerow([iid, ' '.join(parts) if parts else 'none'])
    print(f'\nwrote {a.out}: {len(ids)} rows, {nbox} boxes ({nbox/max(1,len(ids)):.1f}/img)')
    if missing:
        print(f'WARNING: {missing} ids in sample_submission had no image/prediction -> "none"')

    if a.json_out:
        with open(a.json_out, 'w') as f:
            json.dump({k: {'labels': v[0].tolist(), 'boxes': v[1].tolist(), 'scores': v[2].tolist()}
                       for k, v in preds.items()}, f)
        print(f'wrote {a.json_out}')


if __name__ == '__main__':
    main()
