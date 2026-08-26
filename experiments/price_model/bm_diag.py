"""Diagnostics for the two finalists: segments, learning curve, residuals, coefficients,
and interval calibration (naive vs split-conformal).

Run after bm_run_ladder.py -- it reads mb/bench_oof.npz for the OOF predictions.
"""
import json
import sys

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import r2_score
from sklearn.model_selection import GroupKFold

import bm_eval as E
import bm_features as F
import bm_models as M
import seller_base

FIX = '--fix' in sys.argv
SUF = '_fix' if FIX else ''
if FIX:
    _orig = pd.read_pickle
    pd.read_pickle = lambda path, *a, **k: _orig(
        'mb/ds_fix.pkl' if str(path).endswith('mb/ds.pkl') else path, *a, **k)

d = seller_base.load()
X = F.raw_frame(d)
y = d.log_price.values
price = d.price.values
groups = d.seller.values
n = len(d)
L = M.ladder()
Z = np.load(f'mb/bench_oof{SUF}.npz', allow_pickle=True)
out = {}

FINAL = ([a for a in sys.argv[1:] if not a.startswith('--')] or [None])[0] or 'ridge_spline'
INC = 'hgb_incumbent'

# ------------------------------------------------------------------ 1. segments
comp = d[['year', 'chip_gen', 'ram_gb', 'ssd_gb']].notna().all(axis=1).values
seg = {
    'all': np.ones(n, bool),
    'all four specs parsed': comp,
    'any spec missing': ~comp,
    'year missing': d.year.isna().values,
    'chip unidentified': (d.chip_key == 'unknown').values,
    'Apple silicon': (d.chip_brand == 'apple').values,
    'Intel': (d.chip_brand == 'intel').values,
    'family=air': (d.family == 'air').values,
    'family=pro': (d.family == 'pro').values,
    'price < 10k': price < 10000,
    'price 10-20k': (price >= 10000) & (price < 20000),
    'price >= 20k': price >= 20000,
    'seller has >=10 ads': (d.seller_total >= 10).values,
    'one-off seller': (d.seller_total <= 2).values,
}
rows = []
for label, m in seg.items():
    r = {'segment': label, 'n': int(m.sum())}
    for nm in (FINAL, INC, 'config_median_strict', 'ols'):
        p = Z[nm + '__seller']
        mm = m & ~np.isnan(p)
        if mm.sum() < 15:
            r[nm] = None
            continue
        met = E.metrics(y[mm], p[mm], price[mm])
        # R^2 is only meaningful where the segment still spans a real price range; inside a
        # price band the denominator is the band's own tiny variance, so it goes negative
        # for every model and says nothing.
        r[nm + '_r2'] = round(met['r2'], 3) if np.std(y[mm]) > 0.25 else None
        r[nm + '_medape'] = round(met['medape'], 1)
    rows.append(r)
out['segments'] = rows
print('=== SEGMENTS (seller-grouped OOF, averaged over 3 repeats) ===')
print(pd.DataFrame(rows).to_string(index=False))

# ------------------------------------------------------------------ 2. learning curve
print('\n=== LEARNING CURVE (grouped by seller; training SELLERS subsampled) ===')
lc = []
outer = GroupKFold(n_splits=5, shuffle=True, random_state=0)
splits = list(outer.split(X, y, groups))
# The incumbent GBM carries hand-set hyperparameters (no grid), so only the linear model's
# alpha is re-tuned at each learning-curve point -- cheap, and it keeps the small-n end of
# the curve honest rather than penalising it with an alpha picked on the full corpus.
for frac in (0.15, 0.3, 0.5, 0.7, 0.85, 1.0):
    for nm in (FINAL, INC):
        est, grid, _ = L[nm]
        r2s, mds = [], []
        for rep in range(3):
            pr = np.full(n, np.nan)
            for k, (tr, te) in enumerate(splits):
                gtr = np.unique(groups[tr])
                rr = np.random.default_rng(1000 * rep + k)
                keep = set(rr.choice(gtr, max(3, int(len(gtr) * frac)), replace=False))
                sub = tr[np.isin(groups[tr], list(keep))]
                if len(sub) < 60:
                    continue
                m = clone(est)
                if grid:
                    best, _ = E._inner_select(est, grid, X.iloc[sub], y[sub], groups[sub], 3)
                    m.set_params(**best)
                m.fit(X.iloc[sub], y[sub])
                pr[te] = m.predict(X.iloc[te])
            ok = ~np.isnan(pr)
            r2s.append(r2_score(y[ok], pr[ok]))
            mds.append(float(np.median(np.abs(np.exp(pr[ok]) - price[ok]) / price[ok]) * 100))
        lc.append(dict(frac=frac, model=nm, n_train=int(len(splits[0][0]) * frac),
                       r2=float(np.mean(r2s)), r2_sd=float(np.std(r2s, ddof=1)),
                       medape=float(np.mean(mds))))
        print(f"  frac {frac:4.2f} {nm:14s} n~{lc[-1]['n_train']:5d} "
              f"R2 {lc[-1]['r2']:.3f}+-{lc[-1]['r2_sd']:.3f} medape {lc[-1]['medape']:.1f}%",
              flush=True)
out['learning_curve'] = lc

# ------------------------------------------------------------------ 3. residual diagnostics
print('\n=== RESIDUAL DIAGNOSTICS (seller-grouped OOF) ===')
diag = {}
for nm in (FINAL, INC):
    p = Z[nm + '__seller']
    ok = ~np.isnan(p)
    r = y[ok] - p[ok]
    fit = p[ok]
    dd = d[ok]
    # heteroscedasticity: Breusch-Pagan style -- regress squared resid on fitted
    from sklearn.linear_model import LinearRegression
    bp = LinearRegression().fit(fit.reshape(-1, 1), r ** 2)
    bp_r2 = r2_score(r ** 2, bp.predict(fit.reshape(-1, 1)))
    lm = len(r) * bp_r2                              # LM statistic ~ chi2(1)
    from scipy import stats
    bins = pd.qcut(fit, 6, duplicates='drop')
    by_fit = pd.DataFrame({'r': r, 'b': bins}).groupby('b', observed=True).r.agg(['mean', 'std', 'size'])
    yr = dd.year.values
    by_year = pd.DataFrame({'r': r, 'y': yr}).dropna().groupby('y').r.agg(['mean', 'std', 'size'])
    seller_mean = pd.Series(r).groupby(pd.Series(dd.seller.values)).transform('mean').values
    between = np.var(seller_mean) / np.var(r)
    diag[nm] = dict(
        bp_lm=float(lm), bp_p=float(1 - stats.chi2.cdf(lm, 1)),
        skew=float(stats.skew(r)), kurt=float(stats.kurtosis(r)),
        shapiro_p=float(stats.shapiro(r[:4000]).pvalue),
        between_seller_var_frac=float(between),
        sd_by_fitted={str(k): round(float(v), 3) for k, v in by_fit['std'].items()},
        mean_by_fitted={str(k): round(float(v), 3) for k, v in by_fit['mean'].items()},
        mean_by_year={str(int(k)): round(float(v), 3) for k, v in by_year['mean'].items()},
        sd_by_year={str(int(k)): round(float(v), 3) for k, v in by_year['std'].items()},
    )
    print(f"\n-- {nm}: Breusch-Pagan LM {lm:.1f} (p={diag[nm]['bp_p']:.2g}), "
          f"skew {diag[nm]['skew']:.2f}, excess kurt {diag[nm]['kurt']:.2f}, "
          f"between-seller var {between*100:.0f}%")
    print('   resid sd by fitted sextile :', list(diag[nm]['sd_by_fitted'].values()))
    print('   resid mean by fitted sextile:', list(diag[nm]['mean_by_fitted'].values()))
    print('   resid mean by model year   :', diag[nm]['mean_by_year'])
out['residuals'] = diag

json.dump(out, open(f'mb/bench_diag{SUF}.json', 'w'), indent=1, default=str)
print('\nwrote mb/bench_diag.json')
