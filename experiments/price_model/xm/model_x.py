"""Does pooling the three marketplaces help or hurt a MacBook price model?

Target is log(seller ask). Vinted is de-fee'd first (ask = (total-18)/1.05).
Model: HistGradientBoostingRegressor (handles NaN natively, so ads with missing specs stay in).
"""
import os
os.environ.setdefault("OMP_NUM_THREADS","4")
import pandas as pd, numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import GroupKFold
from sklearn.metrics import r2_score, mean_absolute_error

d = pd.read_pickle('xm/pool.pkl').reset_index(drop=True)
d['age'] = 2026 - d.year
d['ram_log'] = np.log(d.ram_gb.astype(float))
d['ssd_log'] = np.log(d.ssd_gb.astype(float))
CATS = ['family', 'chip_key']
NUM  = ['age', 'ram_log', 'ssd_log', 'screen']
BOOL = ['warranty','new','defect','battery_new','vat_dph','touchbar','retina','top_word',
        'scratches','box','battery_pct','cycles']

def design(df, with_mk):
    X = pd.DataFrame(index=df.index)
    for c in CATS: X[c] = df[c].astype('category')
    for c in NUM:  X[c] = df[c].astype(float)
    for c in BOOL: X[c] = df[c].astype(float)
    if with_mk: X['marketplace'] = df.marketplace.astype('category')
    return X

def mk_model():
    return HistGradientBoostingRegressor(max_iter=250, learning_rate=0.08, max_depth=5,
                                         min_samples_leaf=15, l2_regularization=1.0,
                                         categorical_features='from_dtype', random_state=0)

y = np.log(d.ask.values)
# group = same seller-ish + same title -> stops a relisted ad being in train and test
d['grp'] = d.marketplace + '|' + d.name.str.lower().str.strip()

def cv_scores(df, X, yv, n=5):
    g = df.grp.values
    n = min(n, len(np.unique(g)))
    oof = np.full(len(df), np.nan)
    for tr, te in GroupKFold(n_splits=n).split(X, yv, g):
        m = mk_model().fit(X.iloc[tr], yv[tr]); oof[te] = m.predict(X.iloc[te])
    return oof

print("n per marketplace:", d.groupby('marketplace').size().to_dict(), "\n")

# ---------- 1. Bazos-only baseline (grouped CV) ----------
b = d[d.marketplace=='bazos']
Xb = design(b, False); yb = y[b.index]
oof_b = cv_scores(b, Xb, yb)
print(f"[A] Bazos-only, grouped 5-fold CV on Bazos : R2={r2_score(yb,oof_b):.3f}  "
      f"MAE(log)={mean_absolute_error(yb,oof_b):.3f}  median |%err|={np.median(np.abs(np.expm1(oof_b-yb))):.1%}")

# ---------- 2. Bazos-trained -> other marketplaces (zero-shot transfer) ----------
mb = mk_model().fit(Xb, yb)
for m in ['sbazar','vinted']:
    s = d[d.marketplace==m]; Xs = design(s, False); ys = y[s.index]
    p = mb.predict(Xs)
    bias = np.median(p - ys)
    print(f"[B] Bazos-trained -> {m:<7} n={len(s):<4} R2={r2_score(ys,p):.3f}  "
          f"MAE(log)={mean_absolute_error(ys,p):.3f}  median bias={np.expm1(bias):+.1%}  "
          f"(model predicts HIGHER than actual when positive)")

# ---------- 3. pooled, with and without a marketplace fixed effect ----------
for with_mk in (False, True):
    X = design(d, with_mk)
    oof = cv_scores(d, X, y, n=5)
    line = []
    for m in ['bazos','sbazar','vinted']:
        idx = d.index[d.marketplace==m]
        line.append(f"{m}: R2={r2_score(y[idx],oof[idx]):.3f} MAE={mean_absolute_error(y[idx],oof[idx]):.3f} n={len(idx)}")
    print(f"[C] pooled {'WITH' if with_mk else 'NO  '} marketplace feature | " + " | ".join(line))

# ---------- 4. does adding Bazos help a Sbazar / Vinted model? ----------
for m in ['sbazar','vinted']:
    s = d[d.marketplace==m]
    g = s.grp.values
    ys = y[s.index]
    own = cv_scores(s, design(s, False), ys, n=5)
    # pooled: same folds on the target marketplace, but train also on all Bazos rows
    aug = np.full(len(s), np.nan)
    for tr, te in GroupKFold(n_splits=5).split(s, ys, g):
        tr_df = pd.concat([s.iloc[tr], b])
        Xtr = design(tr_df, True); ytr = np.concatenate([ys[tr], yb])
        mm = mk_model().fit(Xtr, ytr)
        aug[te] = mm.predict(design(s.iloc[te], True))
    print(f"[D] {m:<7} own-only  R2={r2_score(ys,own):.3f} MAE={mean_absolute_error(ys,own):.3f}   "
          f"+Bazos(with mk feature)  R2={r2_score(ys,aug):.3f} MAE={mean_absolute_error(ys,aug):.3f}")

# ---------- 5. explicit marketplace effect, spec-controlled linear ----------
import itertools
sp = d[d.spec_ok].copy()
cell = sp.groupby('spec').marketplace.nunique()
sp = sp[sp.spec.isin(cell[cell>=2].index)]
# within-cell demeaned log ask -> the marketplace effect net of configuration
sp['res'] = np.log(sp.ask) - sp.groupby('spec').ask.transform(lambda x: np.log(x).mean())
print("\n[E] within-spec-cell log-price effect (cells shared by >=2 marketplaces):")
print(sp.groupby('marketplace').res.agg(n='size', mean='mean', sem='sem')
        .assign(pct=lambda t: np.expm1(t['mean']),
                lo=lambda t: np.expm1(t['mean']-1.96*t.sem),
                hi=lambda t: np.expm1(t['mean']+1.96*t.sem))[['n','pct','lo','hi']]
        .apply(lambda c: c.round(3)).to_string())
