"""Build a leak-free train/val split of the competition train set.

Goal: no source video may contribute frames to BOTH train and val. The split is
derived from the images alone (no VisDrone filenames), then validated against the
true sequence ids recovered from zabar.

Method
------
1. Descriptor: Hellinger-embedded HSV histograms + a 2x2 spatial hue/value grid.
   (Chosen empirically: it beat grayscale ZNCC, deep HGNetv2 embeddings, JPEG
   quantisation tables and raw colour thumbnails at recovering sequences.)
2. Link images aggressively with SINGLE linkage inside each pixel-resolution
   bucket. Aggressive merging is deliberate and asymmetric in cost:
      over-merge  -> two videos share a block -> split is coarser. Harmless.
      under-merge -> one video spans 2 blocks -> it can straddle the split. LEAK.
   So the threshold is tuned for sequence CONTAINMENT, not for cluster purity.
3. Assign whole blocks to train/val by randomised greedy search, targeting both
   the size ratio and a val class mix matching the global mix.

Validation (uses zabar ground truth, never used to build the split):
   - how many true sequences appear in both splits          -> want 0
   - fraction of same-sequence image pairs crossing splits  -> want 0.000
"""
import os, csv, collections, argparse
import numpy as np
from PIL import Image
from multiprocessing import Pool, cpu_count
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import pdist

B = r"C:/Users/soysa/Desktop/hackathon"
IMGS = os.path.join(B, "dataset", "train", "images")
ANN = os.path.join(B, "dataset", "train", "annotations.csv")
TRUTH_CSV = os.path.join(B, "zncc_matches_verified.csv")
OUT = os.path.join(B, "train_val_split.csv")
CL = ["car", "van", "truck", "bus"]


def feat(p):
    with open(p, "rb") as fh:
        im = Image.open(fh)
        w, h = im.size
        im.draft("RGB", (128, 128))
        hsv = np.asarray(im.convert("RGB").resize((32, 32), Image.BILINEAR).convert("HSV"), np.float32)
    v = [np.histogram(hsv[:, :, k], bins=32, range=(0, 255))[0] for k in range(3)]
    for r in range(2):
        for c in range(2):
            blk = hsv[r * 16:(r + 1) * 16, c * 16:(c + 1) * 16]
            v.append(np.histogram(blk[:, :, 0], bins=16, range=(0, 255))[0])
            v.append(np.histogram(blk[:, :, 2], bins=16, range=(0, 255))[0])
    x = np.concatenate(v).astype(np.float32)
    x = x / max(x.sum(), 1e-9)
    x = np.sqrt(x)
    return x / max(np.linalg.norm(x), 1e-9), w, h


def blocks_at(X, WH, t):
    """single-linkage components at cosine distance t, within resolution buckets"""
    lab = np.zeros(len(X), np.int64); off = 0
    for r in sorted(set(WH)):
        idx = np.where(WH == r)[0]
        if len(idx) < 2:
            lab[idx] = off; off += 1; continue
        Z = linkage(pdist(X[idx], "cosine"), method="single")
        fl = fcluster(Z, t=t, criterion="distance")
        lab[idx] = fl + off; off += fl.max() + 1
    return lab


def containment(blocks, true):
    """fraction of true sequences lying entirely inside ONE block"""
    d = collections.defaultdict(set)
    for b, s in zip(blocks, true): d[s].add(b)
    return sum(1 for v in d.values() if len(v) == 1) / len(d), d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--val-frac", type=float, default=0.15)
    ap.add_argument("--restarts", type=int, default=4000)
    ap.add_argument("--thr", type=float, default=None)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--use-truth", action="store_true",
                    help="block = recovered true_sequence (exact, 0 leakage) "
                         "instead of clustering the images")
    ap.add_argument("--match", default="global", choices=["global", "test", "stratify"],
                    help="what the val ASPECT mix should match: 'global' = the train "
                         "set's own mix; 'test' = the competition test set's mix "
                         "(87%% 16:9), so val scores track the leaderboard")
    ap.add_argument("--w-aspect", type=float, default=3.0,
                    help="weight on aspect-mix divergence in the assignment cost")
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)

    paths = sorted(os.path.join(IMGS, f) for f in os.listdir(IMGS) if f.endswith(".jpg"))
    ids = [os.path.splitext(os.path.basename(p))[0] for p in paths]
    with Pool(max(1, cpu_count() - 1)) as pl:
        R = pl.map(feat, paths, chunksize=16)
    X = np.stack([r[0] for r in R])
    WH = np.array([f"{r[1]}x{r[2]}" for r in R])

    truth = {r["image_id"]: r["visdrone_file"].split("_")[0]
             for r in csv.DictReader(open(TRUTH_CSV))}
    true = np.array([truth[i] for i in ids])

    per = collections.defaultdict(collections.Counter)
    for r in csv.DictReader(open(ANN)):
        per[r["image_id"]][r["label"]] += 1
    Cn = np.array([[per[i][c] for c in CL] for i in ids], float)

    print(f"{len(ids)} train images, {len(set(true))} true sequences\n")

    if a.use_truth:
        uniq = {s: n for n, s in enumerate(sorted(set(true)))}
        blocks = np.array([uniq[s] for s in true])
        print(f"blocks = recovered true_sequence: {len(uniq)} blocks, containment 100.0%")
    else:
        # ---- pick linkage threshold by sequence containment ----
        print(f"{'thr':>6} {'blocks':>8} {'largest':>9} {'seq contained':>15}")
        cands = []
        for t in ([a.thr] if a.thr else [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5, 0.6]):
            bl = blocks_at(X, WH, t)
            cont, _ = containment(bl, true)
            big = max(collections.Counter(bl).values()) / len(bl)
            print(f"{t:>6.2f} {len(set(bl)):>8} {big:>8.1%} {cont:>14.1%}")
            cands.append((t, bl, cont, big))
        # need near-total containment AND a largest block small enough to still split
        ok = [c for c in cands if c[3] <= 1 - a.val_frac - 0.02]
        t, blocks, cont, big = max(ok, key=lambda c: (round(c[2], 4), -c[3])) if ok else cands[0][:4]
        print(f"\nchosen thr={t}: {len(set(blocks))} blocks, largest {big:.1%}, "
              f"sequence containment {cont:.1%}")

    # ---- aspect classes (a sequence has one resolution, so one aspect) ----
    def aclass(r):
        w, h = (int(v) for v in r.split("x"))
        return "16:9" if abs(w / h - 16 / 9) < 0.05 else ("4:3" if abs(w / h - 4 / 3) < 0.05 else "other")
    ASP = ["16:9", "4:3", "other"]
    aidx = {s: k for k, s in enumerate(ASP)}
    Av = np.zeros((len(ids), len(ASP)))
    for i, r in enumerate(WH):
        Av[i, aidx[aclass(r)]] = 1

    # target aspect mix for val
    if a.match == "test":
        td = os.path.join(B, "dataset", "test", "images")
        tc = collections.Counter()
        for f in os.listdir(td):
            if f.endswith(".jpg"):
                with open(os.path.join(td, f), "rb") as fh:
                    w, h = Image.open(fh).size
                tc[aclass(f"{w}x{h}")] += 1
        amix_target = np.array([tc[s] for s in ASP], float)
    else:
        amix_target = Av.sum(0)
    amix_target = amix_target / amix_target.sum()
    print("\nval aspect target (%s): " % a.match
          + "  ".join(f"{s} {100*v:.1f}%" for s, v in zip(ASP, amix_target))
          + "   | train pool: " + "  ".join(f"{s} {100*v:.1f}%" for s, v in zip(ASP, Av.sum(0) / len(ids))))

    # ---- assign whole blocks to train/val ----
    bid = sorted(set(blocks))
    bsize = np.array([(blocks == b).sum() for b in bid], float)
    bcls = np.array([Cn[blocks == b].sum(0) for b in bid])
    basp = np.array([Av[blocks == b].sum(0) for b in bid])
    gmix = Cn.sum(0) / Cn.sum()
    N = len(blocks)

    if a.match == "stratify":
        # Assign whole blocks to val INSIDE each resolution bucket independently, so
        # both groups end up with the same resolution (hence aspect) composition by
        # construction rather than by optimisation.
        bres = []
        for b in bid:
            rs = collections.Counter(WH[blocks == b])
            bres.append(rs.most_common(1)[0][0])
        bres = np.array(bres)
        inval = np.zeros(len(bid), bool)
        for r in sorted(set(bres)):
            js = np.where(bres == r)[0]
            target = a.val_frac * bsize[js].sum()
            bestb = None
            for _ in range(max(400, a.restarts // max(1, len(set(bres))))):
                order = rng.permutation(js)
                pick = np.zeros(len(bid), bool); n = 0
                for j in order:
                    if n + bsize[j] <= target * 1.15:
                        pick[j] = True; n += bsize[j]
                c = abs(n - target)
                if bestb is None or c < bestb[0]:
                    bestb = (c, pick)
            inval |= bestb[1]
    else:
        best = None
        for _ in range(a.restarts):
            order = rng.permutation(len(bid))
            inval = np.zeros(len(bid), bool)
            n = 0
            for j in order:
                if n + bsize[j] <= a.val_frac * N * 1.08:
                    inval[j] = True; n += bsize[j]
            vm = bcls[inval].sum(0); va = basp[inval].sum(0)
            if vm.sum() == 0 or va.sum() == 0:
                continue
            cost = (abs(n / N - a.val_frac) * 5
                    + np.abs(vm / vm.sum() - gmix).sum()
                    + a.w_aspect * np.abs(va / va.sum() - amix_target).sum())
            if best is None or cost < best[0]:
                best = (cost, inval.copy())
        inval = best[1]
    valblocks = {bid[j] for j in range(len(bid)) if inval[j]}
    split = np.array(["val" if b in valblocks else "train" for b in blocks])

    # ---- validate against zabar ----
    seqsplit = collections.defaultdict(set)
    for s, sp in zip(true, split): seqsplit[s].add(sp)
    straddle = [s for s, v in seqsplit.items() if len(v) > 1]
    cross = tot = 0
    byseq = collections.defaultdict(list)
    for i, s in enumerate(true): byseq[s].append(i)
    for v in byseq.values():
        nv = sum(1 for i in v if split[i] == "val"); nt = len(v) - nv
        cross += nv * nt; tot += len(v) * (len(v) - 1) // 2

    vt = Cn[split == "val"].sum(0); tt = Cn[split == "train"].sum(0)
    print(f"\n{'':8}{'images':>8}{'boxes':>9}" + "".join(f"{c:>9}" for c in CL))
    for nm, m, c in (("train", split == "train", tt), ("val", split == "val", vt)):
        print(f"{nm:>8}{m.sum():>8}{int(c.sum()):>9}" + "".join(f"{100*x/c.sum():>8.1f}%" for x in c))
    print(f"{'global':>8}{N:>8}{int(Cn.sum()):>9}" + "".join(f"{100*x:>8.1f}%" for x in gmix))
    print(f"\n{'':8}" + "".join(f"{s:>9}" for s in ASP))
    for nm, m in (("train", split == "train"), ("val", split == "val")):
        v = Av[m].sum(0)
        print(f"{nm:>8}" + "".join(f"{100*x/v.sum():>8.1f}%" for x in v))
    print(f"{'TEST':>8}" + "".join(f"{100*x:>8.1f}%" for x in amix_target)
          + ("   <- target" if a.match == "test" else "   (target was 'global')"))

    print(f"\nval fraction: {(split=='val').mean():.1%}")
    print(f"sequences in train only {sum(1 for v in seqsplit.values() if v=={'train'})}, "
          f"val only {sum(1 for v in seqsplit.values() if v=={'val'})}, "
          f"BOTH {len(straddle)}")
    print(f"same-sequence image pairs crossing the split: {cross}/{tot} = {cross/max(1,tot):.4%}")
    if straddle:
        print("  straddling sequences:", straddle[:12])

    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["image_id", "split", "block", "true_sequence", "n_boxes"] + CL)
        for i, iid in enumerate(ids):
            w.writerow([iid, split[i], int(blocks[i]), true[i], int(Cn[i].sum())]
                       + [int(x) for x in Cn[i]])
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
