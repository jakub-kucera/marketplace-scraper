"""Operational consequence of the linear-vs-GBM gap: how the alert funnel changes.

The model is a "fair price" reference for an underpricing alert, so the number that matters
downstream is not R^2 but how many listings each model puts below a -X% threshold, and how
far the two disagree about WHICH listings those are.
"""
import json
import numpy as np
import pandas as pd

Z = np.load('mb/bench_oof_fix.npz', allow_pickle=True)
y, price, groups = Z['y'], Z['price'], Z['groups']
import sys
WHICH = sys.argv[1] if len(sys.argv) > 1 else 'ridge_spline'
A = np.load(f'mb/oof_{WHICH}.npy') if WHICH not in Z else Z[WHICH + '__seller']
B = Z['hgb_incumbent__seller']
out = {}

print('residual sd on log:  linear %.4f   hgb %.4f   (target sd %.4f)'
      % (np.std(y - A), np.std(y - B), np.std(y)))
rows = []
for thr in (0.15, 0.20, 0.25, 0.30, 0.40):
    fa, fb = (y - A) < np.log(1 - thr), (y - B) < np.log(1 - thr)
    both = (fa & fb).sum()
    rows.append(dict(thr=thr, ridge=int(fa.sum()), hgb=int(fb.sum()), both=int(both),
                     ridge_only=int((fa & ~fb).sum()), hgb_only=int((~fa & fb).sum()),
                     jaccard=round(both / max(1, (fa | fb).sum()), 3),
                     ridge_per_week=round(fa.sum() / 14.1, 1), hgb_per_week=round(fb.sum() / 14.1, 1)))
    print(f"  >={thr:.0%} below predicted: linear {fa.sum():4d} ({rows[-1]['ridge_per_week']}/wk)  "
          f"hgb {fb.sum():4d} ({rows[-1]['hgb_per_week']}/wk)  agree on {both:4d}  "
          f"Jaccard {rows[-1]['jaccard']}")
out['alert_funnel'] = rows

# agreement between the two models' point predictions
d = np.exp(A) - np.exp(B)
print('\npoint-prediction agreement: median |ridge-hgb| = %.0f Kc (%.1f%% of median price), '
      'corr(log) %.3f' % (np.median(np.abs(d)), np.median(np.abs(d)) / np.median(price) * 100,
                          np.corrcoef(A, B)[0, 1]))
out['pred_agreement'] = dict(median_abs_diff_czk=float(np.median(np.abs(d))),
                             corr=float(np.corrcoef(A, B)[0, 1]))

# error in CZK at the median ad
for nm, p in ((WHICH, A), ('hgb_incumbent', B)):
    ape = np.abs(np.exp(p) - price) / price
    q = np.percentile(ape, [50, 75, 90]) * 100
    print(f'  {nm:14s} APE p50 {q[0]:.1f}%  p75 {q[1]:.1f}%  p90 {q[2]:.1f}%  '
          f'-> on the 10 990 Kc median ad, typical miss {q[0]/100*10990:,.0f} Kc')
    out[nm] = dict(ape_p50=q[0], ape_p75=q[1], ape_p90=q[2])

json.dump(out, open('mb/bench_ops.json', 'w'), indent=1)
