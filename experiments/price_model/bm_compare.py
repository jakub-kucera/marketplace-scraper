"""Is the linear-vs-GBM gap real? Paired seller-cluster bootstrap + robustness checks.

  1. paired difference in R^2 / MedAPE between every finalist and the GBM, with a 95% CI
     from resampling SELLERS (the unit of independence -- 56% of ads are ten dealers');
  2. fold-mean vs pooled R^2, to reconcile with previously published figures;
  3. the same ladder re-scored on features rebuilt with the fixed extractor (mb/ds_fix.pkl:
     M5 chips visible, a lone 128GB read as a disk).
"""
import json
import time

import numpy as np
import pandas as pd

import bm_eval as E
import bm_features as F
import bm_models as M
import seller_base

import sys
FIX = '--fix' in sys.argv
SUF = '_fix' if FIX else ''
if FIX:
    _o = pd.read_pickle
    pd.read_pickle = lambda path, *a, **k: _o(
        'mb/ds_fix.pkl' if str(path).endswith('mb/ds.pkl') else path, *a, **k)

Z = np.load(f'mb/bench_oof{SUF}.npz', allow_pickle=True)
y, price, groups = Z['y'], Z['price'], Z['groups']
res = json.load(open(f'mb/bench_results{SUF}.json'))
out = {}

REF = 'hgb_incumbent'
CAND = ['config_median_strict', 'config_median_ladder', 'ols', 'ols_spline', 'ridge_spline',
        'ridge_config', 'ridge_seg', 'l1_rich', 'l1_seg', 'huber_rich', 'tree', 'rf', 'hgb',
        'hgb_l1']

print('=== PAIRED DIFFERENCE vs %s, seller-cluster bootstrap (2000 resamples) ===' % REF)
print(f"{'model':22s} {'dR2':>8} {'95% CI':>18} {'dMedAPE':>9} {'95% CI':>18}")
rows = []
for nm in CAND:
    if nm + '__seller' not in Z:
        continue
    r = E.cluster_bootstrap_delta(y, price, Z[nm + '__seller'], Z[REF + '__seller'],
                                  groups, B=2000, seed=1)
    r['model'] = nm
    rows.append(r)
    print(f"{nm:22s} {r['d_r2']:+8.4f} [{r['d_r2_ci'][0]:+.4f},{r['d_r2_ci'][1]:+.4f}] "
          f"{r['d_medape']:+9.2f} [{r['d_medape_ci'][0]:+.2f},{r['d_medape_ci'][1]:+.2f}]")
out['bootstrap_vs_gbm'] = rows

# ---- 2. fold-mean vs pooled R^2 (protocol reconciliation)
print('\n=== pooled-OOF R2 vs mean-of-folds R2 (why published figures can differ) ===')
d = seller_base.load()
from sklearn.model_selection import GroupKFold
fid = np.full(len(d), -1)
for k, (_, te) in enumerate(GroupKFold(n_splits=5).split(np.zeros(len(d)), y, groups)):
    fid[te] = k
rec = []
for nm in ('ridge', 'ridge_spline', 'ols_spline', 'l1_rich', 'hgb_incumbent'):
    p = Z[nm + '__plain']
    pooled = E.metrics(y, p, price)
    agg, _ = E.fold_table(y, p, price, fid)
    rec.append(dict(model=nm, pooled_r2=round(pooled['r2'], 3),
                    foldmean_r2=round(agg['r2_mean'], 3), fold_sd=round(agg['r2_std'], 3),
                    pooled_medape=round(pooled['medape'], 2)))
    print(f"  {nm:16s} pooled {pooled['r2']:.3f}   fold-mean {agg['r2_mean']:.3f} "
          f"+-{agg['r2_std']:.3f}   MedAPE {pooled['medape']:.2f}%")
out['reconciliation'] = rec

# ---- 3. robustness: rebuilt features
if FIX:
    json.dump(out, open(f'mb/bench_compare{SUF}.json', 'w'), indent=1, default=str)
    raise SystemExit(0)
print('\n=== ROBUSTNESS: same protocol on mb/ds_fix.pkl (fixed extractor) ===')
import pandas as _pd
_orig = _pd.read_pickle


def _patched(path, *a, **k):
    return _orig('mb/ds_fix.pkl' if str(path).endswith('mb/ds.pkl') else path, *a, **k)


_pd.read_pickle = _patched
d2 = seller_base.load()
_pd.read_pickle = _orig
X2 = F.raw_frame(d2)
y2, price2, g2 = d2.log_price.values, d2.price.values, d2.seller.values
order2 = np.arange(len(d2))
L = M.ladder()
fix = []
for nm in ('ridge_spline', 'ridge_seg', 'l1_seg', 'config_median_strict', 'hgb_incumbent'):
    est, grid, _ = L[nm]
    t = time.time()
    p, f, _ = E.nested_group_cv(est, grid, X2, y2, price2, g2, 5, 3, 3)
    s = E.summarise_repeats(y2, price2, p, f)
    tr, _ = E.time_split_eval(est, grid, X2, y2, price2, order2, 0.70, 4)
    fix.append(dict(model=nm, seller_r2=round(s['r2'], 3), seller_medape=round(s['medape'], 2),
                    time_r2=round(tr['r2'], 3), time_medape=round(tr['medape'], 2),
                    was_r2=res[nm]['seller_r2'], was_medape=res[nm]['seller_medape']))
    print(f"  {nm:20s} sellerR2 {s['r2']:.3f} (was {res[nm]['seller_r2']:.3f})  "
          f"medape {s['medape']:.2f}% (was {res[nm]['seller_medape']:.2f}%)  [{time.time()-t:.0f}s]",
          flush=True)
out['fixed_extractor'] = fix

json.dump(out, open(f'mb/bench_compare{SUF}.json', 'w'), indent=1, default=str)
print('\nwrote mb/bench_compare.json')
