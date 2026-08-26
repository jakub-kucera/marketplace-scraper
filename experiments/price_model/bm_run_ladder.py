"""Run the whole ladder under both honest protocols and cache everything.

  protocol A  repeated nested GroupKFold by SELLER   (5 folds x 3 repeats, inner 3-fold)
  protocol B  chronological 70/30 past->future split (inner expanding-window tuning)

Writes: mb/bench_oof.npz, mb/bench_results.json
"""
import json
import sys
import time

import numpy as np
import pandas as pd

import bm_eval as E
import bm_features as F
import bm_models as M
import seller_base

# `python bm_run_ladder.py --fix [names...]` re-scores everything on mb/ds_fix.pkl, the same
# corpus with the two extractor bugs fixed (M5 chips visible, a lone 128GB read as a disk).
FIX = '--fix' in sys.argv
SUF = '_fix' if FIX else ''
if FIX:
    _orig = pd.read_pickle
    pd.read_pickle = lambda path, *a, **k: _orig(
        'mb/ds_fix.pkl' if str(path).endswith('mb/ds.pkl') else path, *a, **k)

t0 = time.time()
d = seller_base.load()
X = F.raw_frame(d)
y = d.log_price.values
price = d.price.values
groups = d.seller.values
order = np.arange(len(d))          # d is already sorted by `created`

only = [a for a in sys.argv[1:] if not a.startswith('--')] or None
L = M.ladder()
if only:
    L = {k: v for k, v in L.items() if k in only}

oof, res = {}, {}
for name, (est, grid, note) in L.items():
    t = time.time()
    preds, folds, chosen = E.nested_group_cv(est, grid, X, y, price, groups,
                                             n_outer=5, n_inner=3, repeats=3)
    s = E.summarise_repeats(y, price, preds, folds)
    pplain = E.plain_group_cv(est, grid, X, y, groups, n_outer=5, n_inner=3)
    mplain = E.metrics(y, pplain, price)
    tr, ptime = E.time_split_eval(est, grid, X, y, price, order, train_frac=0.70, n_inner=4)
    cov = float(np.mean(~np.isnan(preds[0])))
    row = dict(note=note,
               seller_r2=s['r2'], seller_r2_fold_sd=s['r2_fold_sd'], seller_r2_rep_sd=s['r2_rep_sd'],
               seller_medape=s['medape'], seller_medape_fold_sd=s['medape_fold_sd'],
               seller_rmse=s['rmse_log'], coverage=cov,
               plain_r2=mplain['r2'], plain_medape=mplain['medape'],
               time_r2=tr['r2'], time_medape=tr['medape'], time_n=tr['n'],
               time_params=str(tr.get('params')),
               chosen=str(pd.Series([str(c) for c in chosen]).value_counts().head(3).to_dict()),
               secs=round(time.time() - t, 1))
    res[name] = row
    oof[name + '__seller'] = s['oof_mean']
    oof[name + '__seller_r0'] = preds[0]
    oof[name + '__time'] = ptime
    oof[name + '__plain'] = pplain
    print(f"{name:22s} sellerR2 {row['seller_r2']:.3f}+-{row['seller_r2_fold_sd']:.3f} "
          f"medape {row['seller_medape']:5.2f}%  | plainR2 {row['plain_r2']:.3f} "
          f"medape {row['plain_medape']:5.2f}% | timeR2 {row['time_r2']:.3f} "
          f"medape {row['time_medape']:5.1f}%  cov {cov:.2f}  [{row['secs']}s]", flush=True)

np.savez(f'mb/bench_oof{SUF}.npz', **oof, y=y, price=price,
         groups=groups.astype(str), created=d.created.astype('int64').values)
json.dump(res, open(f'mb/bench_results{SUF}.json', 'w'), indent=1)
print('total', round(time.time() - t0, 1), 's')
