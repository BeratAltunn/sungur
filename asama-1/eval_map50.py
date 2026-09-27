"""Score a competition submission CSV against a ground-truth CSV, locally.

Metric mirrors the competition statement: mAP@0.5 = unweighted mean over the four
classes of per-class AP, where a prediction is a TP if its class is right and IoU
with an unmatched GT box is >= 0.5. Predictions are ranked by confidence within
each class. AP uses the COCO 101-point interpolated rule (--ap voc11 / area for
the alternatives).

The rule "predictions belonging to vehicles smaller than 200 px^2 do not affect
your score" is ignore-region semantics, not a size filter on the predictions: the
GT CSV already holds only boxes >= 200 px^2, and --ignore supplies the sub-200
vehicles that were filtered out. Any prediction whose best match is one of those
is discarded (neither TP nor FP); everything else -- pedestrians, empty ground,
wrong vehicle class -- counts as a false positive per the rules.

--min-area additionally drops predictions by their own box area; it defaults to 0
because the rules do not actually ask for that.

  python eval_map50.py --gt dataset/test/annotations.csv --pred submission.csv \
      --ignore dataset/test/ignore_small.csv
"""
import csv, argparse, collections
import numpy as np

CLASSES = ["car", "van", "truck", "bus"]


def load_gt(path):
    d = collections.defaultdict(list)
    with open(path) as f:
        for r in csv.DictReader(f):
            x, y, w, h = int(r["x"]), int(r["y"]), int(r["w"]), int(r["h"])
            d[(r["image_id"], r["label"])].append([x, y, x + w, y + h])
    return d


def load_pred(path, min_area, min_conf=0.0):
    d = collections.defaultdict(list)
    ids = []
    dropped = 0
    with open(path) as f:
        for r in csv.DictReader(f):
            iid = r["image_id"]
            ids.append(iid)
            s = r["PredictionString"].strip()
            if not s or s == "none":
                continue
            p = s.split()
            for i in range(0, len(p) - 5, 6):
                lab = p[i]
                c = float(p[i + 1])
                x, y, w, h = (float(v) for v in p[i + 2:i + 6])
                if w * h < min_area or c < min_conf:
                    dropped += 1
                    continue
                d[(iid, lab)].append([c, x, y, x + w, y + h])
    return d, ids, dropped


def iou_1_to_n(b, G):
    x1 = np.maximum(b[0], G[:, 0]); y1 = np.maximum(b[1], G[:, 1])
    x2 = np.minimum(b[2], G[:, 2]); y2 = np.minimum(b[3], G[:, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    a = (b[2] - b[0]) * (b[3] - b[1])
    g = (G[:, 2] - G[:, 0]) * (G[:, 3] - G[:, 1])
    return inter / (a + g - inter + 1e-12)


def ap_from_pr(rec, prec, mode):
    if mode == "area":
        mrec = np.concatenate(([0.], rec, [1.]))
        mpre = np.concatenate(([0.], prec, [0.]))
        for i in range(len(mpre) - 2, -1, -1):
            mpre[i] = max(mpre[i], mpre[i + 1])
        idx = np.where(mrec[1:] != mrec[:-1])[0]
        return float(((mrec[idx + 1] - mrec[idx]) * mpre[idx + 1]).sum())
    pts = np.linspace(0, 1, 101) if mode == "coco101" else np.linspace(0, 1, 11)
    mpre = prec.copy()
    for i in range(len(mpre) - 2, -1, -1):
        mpre[i] = max(mpre[i], mpre[i + 1])
    out = []
    for t in pts:
        m = rec >= t
        out.append(mpre[m].max() if m.any() else 0.0)
    return float(np.mean(out))


def evaluate(gt, pred, iou_thr, ap_mode, ign=None):
    ign = ign or {}
    res = {}
    nignored = 0
    for cls in CLASSES:
        npos = sum(len(v) for (i, c), v in gt.items() if c == cls)
        dets = []
        for (iid, c), v in pred.items():
            if c != cls:
                continue
            for row in v:
                dets.append((row[0], iid, row[1:]))
        if npos == 0:
            res[cls] = dict(ap=float("nan"), npos=0, ndet=len(dets), tp=0, fp=len(dets))
            continue
        dets.sort(key=lambda d: -d[0])
        used = {k: np.zeros(len(v), bool) for k, v in gt.items() if k[1] == cls}
        tp = np.zeros(len(dets)); fp = np.zeros(len(dets)); keepmask = np.ones(len(dets), bool)
        for i, (sc, iid, box) in enumerate(dets):
            key = (iid, cls)
            b = np.asarray(box, float)
            G = gt.get(key)
            hit = -1
            if G:
                G = np.asarray(G, float)
                ious = iou_1_to_n(b, G)
                for j in np.argsort(-ious):
                    if ious[j] < iou_thr:
                        break
                    if not used[key][j]:
                        hit = j; break
            if hit >= 0:
                used[key][hit] = True; tp[i] = 1
                continue
            # unmatched: if it lands on a sub-200px^2 vehicle, it is ignored, not an FP
            I = ign.get(iid)
            if I is not None and len(I) and iou_1_to_n(b, np.asarray(I, float)).max() >= iou_thr:
                keepmask[i] = False; nignored += 1
                continue
            fp[i] = 1
        tp, fp = tp[keepmask], fp[keepmask]
        res_ndet = int(keepmask.sum())
        ctp, cfp = np.cumsum(tp), np.cumsum(fp)
        rec = ctp / npos
        prec = ctp / np.maximum(ctp + cfp, 1e-12)
        res[cls] = dict(ap=ap_from_pr(rec, prec, ap_mode), npos=npos, ndet=res_ndet,
                        tp=int(tp.sum()), fp=int(fp.sum()),
                        recall=float(rec[-1]) if len(rec) else 0.0,
                        precision=float(prec[-1]) if len(prec) else 0.0)
    return res, nignored


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gt", required=True)
    ap.add_argument("--pred", required=True)
    ap.add_argument("--iou", type=float, default=0.5)
    ap.add_argument("--min-area", type=float, default=0.0)
    ap.add_argument("--min-conf", type=float, default=0.0)
    ap.add_argument("--ignore", default=None,
                    help="CSV of sub-200px^2 vehicle boxes -> ignore regions")
    ap.add_argument("--ap", default="coco101", choices=["coco101", "voc11", "area"])
    ap.add_argument("--classes", default=None,
                    help="remap predicted label names, e.g. van,car,bus,truck applied positionally to car,van,truck,bus")
    a = ap.parse_args()

    gt = load_gt(a.gt)
    pred, ids, dropped = load_pred(a.pred, a.min_area, a.min_conf)
    if a.classes:
        ren = dict(zip(a.classes.split(","), CLASSES))
        np_ = collections.defaultdict(list)
        for (i, c), v in pred.items():
            np_[(i, ren.get(c, c))] += v
        pred = np_

    ign = {}
    if a.ignore:
        for (i, c), v in load_gt(a.ignore).items():
            ign.setdefault(i, []).extend(v)

    ngt = sum(len(v) for v in gt.values())
    ndet = sum(len(v) for v in pred.values())
    print(f"gt   : {ngt} boxes over {len(set(i for i, _ in gt))} images")
    print(f"pred : {ndet} boxes over {len(set(ids))} rows"
          + (f"  ({dropped} dropped under {a.min_area:.0f}px^2)" if dropped else ""))
    if ign:
        print(f"ignore regions: {sum(len(v) for v in ign.values())} sub-200px^2 vehicles")
    print(f"IoU {a.iou}, AP rule {a.ap}\n")

    res, nignored = evaluate(gt, pred, a.iou, a.ap, ign)
    print(f"{'class':>8} {'AP@0.5':>8} {'gt':>7} {'preds':>8} {'TP':>7} {'FP':>8} {'recall':>8} {'prec':>7}")
    for c in CLASSES:
        r = res[c]
        print(f"{c:>8} {r['ap']:>8.4f} {r['npos']:>7} {r['ndet']:>8} {r['tp']:>7} {r['fp']:>8} "
              f"{r.get('recall',0):>8.3f} {r.get('precision',0):>7.3f}")
    m = float(np.nanmean([res[c]["ap"] for c in CLASSES]))
    if nignored:
        print(f"\n{nignored} predictions ignored (matched a sub-200px^2 vehicle)")
    print(f"\nmAP@0.5 = {m:.4f}")


if __name__ == "__main__":
    main()
