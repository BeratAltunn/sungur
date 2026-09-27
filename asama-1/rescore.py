"""Re-score a multi-class submission using each box's FULL class distribution.

Why a plain per-class multiplier is useless: AP for class c depends only on the
ORDER of the detections labelled c. Multiplying every class-c score by a constant
preserves that order, so mAP is bit-identical. (Same reason nq 300->1200 bought
+0.001: it added hypotheses at the bottom of each list.)

To move AP you must REORDER within a class, which requires a function of the
other classes' scores too. These variants all do that:

  norm      s_c / sum_k s_k                 -- how exclusively this box is class c
  margin    s_c * (s_c - max_{k!=c} s_k)    -- penalise boxes that another class claims
  prior     (s_c / prior_c^tau) normalised  -- long-tail logit adjustment
  softmax   exp(s_c/T) / sum_k exp(s_k/T)   -- temperature-sharpened distribution
  geo       sqrt(s_c * norm_c)              -- blend raw confidence with exclusivity

`geo` and `blend` matter because pure `norm` throws away absolute confidence: a
box with (van .05, car .04) is 55% exclusively van but is probably nothing.
"""
import csv, argparse, collections
import numpy as np

CL = ["car", "van", "truck", "bus"]
CI = {c: i for i, c in enumerate(CL)}


def load(path):
    """-> {image_id: (boxes Nx4 xywh, scores Nx4)}"""
    out = {}
    order = []
    with open(path) as f:
        for r in csv.DictReader(f):
            iid = r["image_id"]; order.append(iid)
            s = r["PredictionString"].strip()
            if not s or s == "none":
                out[iid] = (np.zeros((0, 4)), np.zeros((0, 4))); continue
            p = s.split()
            d = {}
            for i in range(0, len(p) - 5, 6):
                key = (round(float(p[i + 2]), 1), round(float(p[i + 3]), 1),
                       round(float(p[i + 4]), 1), round(float(p[i + 5]), 1))
                if key not in d:
                    d[key] = np.zeros(4)
                d[key][CI[p[i]]] = max(d[key][CI[p[i]]], float(p[i + 1]))
            boxes = np.array(list(d.keys()), float)
            sc = np.stack(list(d.values()))
            out[iid] = (boxes, sc)
    return out, order


def rescore(S, mode, prior, tau, T, alpha):
    tot = S.sum(1, keepdims=True) + 1e-9
    if mode == "raw":
        return S
    if mode == "norm":
        return S / tot
    if mode == "margin":
        srt = np.sort(S, 1)[:, ::-1]
        best_other = np.where(S >= srt[:, [0]], srt[:, [1]], srt[:, [0]])
        return S * np.clip(S - best_other, 0, None)
    if mode == "prior":
        adj = S / (prior[None, :] ** tau)
        return adj / (adj.sum(1, keepdims=True) + 1e-9)
    if mode == "softmax":
        e = np.exp(S / T)
        return e / e.sum(1, keepdims=True)
    if mode == "geo":
        return np.sqrt(S * (S / tot))
    if mode == "blend":
        return (S ** (1 - alpha)) * ((S / tot) ** alpha)
    raise ValueError(mode)


def write(path, preds, order):
    with open(path, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["image_id", "PredictionString"])
        for iid in order:
            b, s = preds[iid]
            if len(b) == 0:
                w.writerow([iid, "none"]); continue
            parts = []
            flat = [(s[i, c], c, i) for i in range(len(b)) for c in range(4) if s[i, c] > 1e-6]
            flat.sort(key=lambda x: -x[0])
            for sc, c, i in flat:
                parts += [CL[c], f"{sc:.6f}", f"{b[i,0]:.1f}", f"{b[i,1]:.1f}",
                          f"{b[i,2]:.1f}", f"{b[i,3]:.1f}"]
            w.writerow([iid, " ".join(parts) if parts else "none"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", default="norm")
    ap.add_argument("--tau", type=float, default=0.5)
    ap.add_argument("--T", type=float, default=0.3)
    ap.add_argument("--alpha", type=float, default=0.5)
    a = ap.parse_args()

    preds, order = load(a.pred)
    # class prior from the predictions themselves (argmax counts)
    cnt = np.zeros(4)
    for b, s in preds.values():
        if len(s):
            for c in s.argmax(1): cnt[c] += 1
    prior = cnt / cnt.sum()

    out = {}
    for iid, (b, s) in preds.items():
        out[iid] = (b, rescore(s, a.mode, prior, a.tau, a.T, a.alpha) if len(s) else s)
    write(a.out, out, order)
    print(f"{a.mode}: wrote {a.out}  (prior {np.round(prior,3)})")
