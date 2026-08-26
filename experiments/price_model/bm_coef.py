"""Coefficient interpretation for the linear model + interval calibration.

Part A -- coefficients of the linear model, converted from log points to a % price effect
          (exp(b)-1), with a seller-cluster bootstrap CI so the reported effects carry
          honest uncertainty. Fitted on the full corpus for reporting only; every accuracy
          number in the report comes from the out-of-fold protocols, not from this fit.

Part B -- prediction intervals. Naive Gaussian (mean +- z*sigma from training residuals) vs
          split conformal (absolute-residual quantile on a held-out calibration slice, and a
          locally-scaled variant). Coverage is measured on the same two honest protocols.
"""
import json
import sys

import numpy as np
import pandas as pd
from sklearn.base import clone
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
FINAL = ([a for a in sys.argv[1:] if not a.startswith('--')] or [None])[0] or 'ridge_spline'
out = {}

# ------------------------------------------------------------------ A. coefficients
est, grid, _ = L[FINAL]
best, _ = E._inner_select(est, grid, X, y, groups, 4) if grid else ({}, None)
m = clone(est).set_params(**best)
m.fit(X, y)
prep = m.named_steps['prep']
prep = getattr(prep, 'ct_', prep) if not hasattr(prep, 'named_transformers_') else prep
names = list(m.named_steps['prep'].get_feature_names_out())
coef = m.named_steps['m'].coef_.ravel()
assert len(names) == len(coef), (len(names), len(coef))

# cluster bootstrap over sellers
rng = np.random.default_rng(0)
uniq, inv = np.unique(groups, return_inverse=True)
idx_by_g = [np.where(inv == i)[0] for i in range(len(uniq))]
B = 400
# a bootstrap resample can miss a rare chip_key entirely, so the one-hot width moves.
# Align every replicate BY FEATURE NAME rather than by position.
pos = {n: i for i, n in enumerate(names)}
boot = np.full((B, len(coef)), np.nan)
for b in range(B):
    pick = rng.integers(0, len(uniq), len(uniq))
    idx = np.concatenate([idx_by_g[i] for i in pick])
    mb = clone(est).set_params(**best)
    mb.fit(X.iloc[idx], y[idx])
    for nm_, cf in zip(mb.named_steps['prep'].get_feature_names_out(),
                       mb.named_steps['m'].coef_.ravel()):
        if nm_ in pos:
            boot[b, pos[nm_]] = cf

tab = pd.DataFrame({'feature': names, 'coef': coef,
                    'lo': np.nanpercentile(boot, 2.5, axis=0),
                    'hi': np.nanpercentile(boot, 97.5, axis=0),
                    'boot_n': (~np.isnan(boot)).sum(axis=0)})
tab['pct'] = (np.exp(tab.coef) - 1) * 100
tab['pct_lo'] = (np.exp(tab.lo) - 1) * 100
tab['pct_hi'] = (np.exp(tab.hi) - 1) * 100
tab['abs'] = tab.coef.abs()
print(f'=== {FINAL} coefficients (params {best}) ===')
print(tab.sort_values('abs', ascending=False).head(45)
      .to_string(index=False, float_format=lambda v: f'{v:8.3f}'))
out['coef_params'] = best
out['coefs'] = tab.to_dict('records')

# --- derived, human-readable effects. The numeric features are standardised inside the
#     pipeline, so a one-unit change in the ORIGINAL unit is coef / scale.
sc = prep.named_transformers_['num'].named_steps['sc'] if 'num' in prep.named_transformers_ else None
num_cols = [c for c in F.NUM if c != 'year'] if FINAL.endswith(('spline', 'yearcat')) else F.NUM
scales = dict(zip(num_cols, sc.scale_[:len(num_cols)])) if sc is not None else {}
cmap = dict(zip(names, coef))


def per_unit(feat, col):
    """log-point effect of +1 in the raw unit of `col`."""
    key = [k for k in names if k.endswith(feat)]
    if not key or col not in scales:
        return None
    return cmap[key[0]] / scales[col]


eff = {}
b_ram = per_unit('ram_log2', 'ram_log2')
b_ssd = per_unit('ssd_log2', 'ssd_log2')
if b_ram is not None:
    eff['doubling RAM (8->16, 16->32GB)'] = (np.exp(b_ram) - 1) * 100
if b_ssd is not None:
    eff['doubling SSD (256->512GB)'] = (np.exp(b_ssd) - 1) * 100
b_year = per_unit('year', 'year')
if b_year is not None:
    eff['one model year newer'] = (np.exp(b_year) - 1) * 100
out['effects'] = eff
print('\n=== per-unit effects (%) ===')
for k, v in eff.items():
    print(f'  {k:32s} {v:+6.1f}%')

# --- year curve: predicted log-price shift vs the 2020 baseline, all else at its median
if True:
    proto = X.iloc[[0]].copy()
    for c in X.columns:
        if X[c].dtype.kind in 'fi':
            proto[c] = X[c].median()
        else:
            proto[c] = X[c].mode().iloc[0]
    yrs = sorted(d.year.dropna().unique())
    preds = []
    for yv in yrs:
        r = proto.copy()
        r['year'] = yv
        r['year_s'] = str(int(yv))
        preds.append(float(m.predict(r)[0]))
    ref = preds[yrs.index(2020.0)] if 2020.0 in yrs else preds[len(preds) // 2]
    curve = {int(a): round(float(np.exp(b - ref) - 1) * 100, 1) for a, b in zip(yrs, preds)}
    out['year_curve_pct_vs_2020'] = curve
    print('\n=== fitted year curve, % vs a 2020 machine, everything else held at the median ===')
    print('  ' + '  '.join(f'{k}:{v:+.0f}%' for k, v in curve.items()))

# ------------------------------------------------------------------ B. intervals
print('\n=== PREDICTION INTERVALS ===')


def conformal_eval(est, grid, nominal=0.80, protocol='seller'):
    """Fit / calibrate / test with no overlap in SELLERS (or in time)."""
    lo_c, hi_c, lo_n, hi_n, tgt, tprice = [], [], [], [], [], []
    if protocol == 'seller':
        outer = GroupKFold(n_splits=5, shuffle=True, random_state=0)
        it = outer.split(X, y, groups)
    else:
        cut1, cut2 = int(n * 0.55), int(n * 0.70)
        it = [(np.arange(cut2), np.arange(cut2, n))]
    for tr, te in it:
        if protocol == 'seller':
            g = groups[tr]
            ug = np.unique(g)
            rr = np.random.default_rng(7)
            cal_g = set(rr.choice(ug, max(2, int(len(ug) * 0.30)), replace=False))
            cal = tr[np.isin(g, list(cal_g))]
            fit = tr[~np.isin(g, list(cal_g))]
        else:
            fit, cal = tr[:cut1], tr[cut1:]
        pars = {}
        if grid:
            pars, _ = E._inner_select(est, grid, X.iloc[fit], y[fit],
                                      groups[fit], 3)
        mm = clone(est).set_params(**pars)
        mm.fit(X.iloc[fit], y[fit])
        rc = np.abs(y[cal] - mm.predict(X.iloc[cal]))
        k = int(np.ceil((len(rc) + 1) * nominal))
        q = np.sort(rc)[min(k, len(rc)) - 1]
        sig = np.std(y[fit] - mm.predict(X.iloc[fit]), ddof=1)
        from scipy.stats import norm
        z = float(norm.ppf(0.5 + nominal / 2))            # two-sided normal quantile
        p = mm.predict(X.iloc[te])
        lo_c.append(p - q); hi_c.append(p + q)
        lo_n.append(p - z * sig); hi_n.append(p + z * sig)
        tgt.append(y[te]); tprice.append(price[te])
    lo_c, hi_c = np.concatenate(lo_c), np.concatenate(hi_c)
    lo_n, hi_n = np.concatenate(lo_n), np.concatenate(hi_n)
    tgt, tprice = np.concatenate(tgt), np.concatenate(tprice)
    cov_c = float(((tgt >= lo_c) & (tgt <= hi_c)).mean())
    cov_n = float(((tgt >= lo_n) & (tgt <= hi_n)).mean())
    w_c = float(np.median(np.exp(hi_c) - np.exp(lo_c)))
    w_n = float(np.median(np.exp(hi_n) - np.exp(lo_n)))
    return dict(nominal=nominal, conformal_cov=cov_c, naive_cov=cov_n,
                conformal_width_czk=w_c, naive_width_czk=w_n, n=len(tgt))


rows = []
for nm in (FINAL, 'hgb_incumbent'):
    e, g_, _ = L[nm]
    for proto in ('seller', 'time'):
        for nom in (0.80, 0.90):
            r = conformal_eval(e, g_, nominal=nom, protocol=proto)
            r.update(model=nm, protocol=proto)
            rows.append(r)
            print(f"  {nm:14s} {proto:6s} nominal {nom:.0%}  conformal {r['conformal_cov']:.1%} "
                  f"(median width {r['conformal_width_czk']:,.0f} Kc)   "
                  f"naive-gauss {r['naive_cov']:.1%} (width {r['naive_width_czk']:,.0f} Kc)",
                  flush=True)
out['intervals'] = rows

json.dump(out, open(f'mb/bench_coef_{FINAL}{SUF}.json', 'w'), indent=1, default=str)
print(f'\nwrote mb/bench_coef_{FINAL}.json')
