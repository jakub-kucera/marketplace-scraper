"""Time-causal modelling harness: expanding window, retrain every `step` ads."""
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.preprocessing import OrdinalEncoder
from sklearn.metrics import r2_score

CAT  = ['family','chip_key','chip_variant','town_g','chip_brand']
NUM  = ['year','age','screen','ram_gb','ssd_gb','ram_log','storage_log','dow','battery_pct','cycles','view_count']
BOOL = ['warranty','new','defect','battery_new','vat_dph','cz_kbd','us_kbd','touchbar','retina',
        'top_word','scratches','urgent','box','swap']

def build_X(d, extra_num=()):
    X = d[NUM].astype(float).copy()
    for c in BOOL: X[c] = d[c].astype(float)
    for c in extra_num: X[c] = d[c].astype(float)
    enc = OrdinalEncoder(handle_unknown='use_encoded_value', unknown_value=-1)
    C = pd.DataFrame(enc.fit_transform(d[CAT].astype(str)), columns=CAT, index=d.index)
    X = pd.concat([X, C], axis=1)
    return X, [X.columns.get_loc(c) for c in CAT]

def mk(cat_idx, **kw):
    p = dict(max_iter=180, learning_rate=0.06, min_samples_leaf=15, l2_regularization=1.0,
             categorical_features=cat_idx, random_state=0)
    p.update(kw)
    return HistGradientBoostingRegressor(**p)

def replay(d, X, cat_idx, train_mask=None, start_frac=.4, step=100):
    """Expanding-window predictions. train_mask limits WHICH rows may be trained on."""
    y = d.log_price.values
    n = len(d); start = int(n*start_frac)
    pred = np.full(n, np.nan)
    tm = np.ones(n, bool) if train_mask is None else np.asarray(train_mask)
    for s in range(start, n, step):
        e = min(s+step, n)
        tr = np.where(tm[:s])[0]
        if len(tr) < 60: continue
        m = mk(cat_idx); m.fit(X.iloc[tr], y[tr])
        pred[s:e] = m.predict(X.iloc[s:e])
    return pred

def score(d, pred, mask=None, label=''):
    ok = ~np.isnan(pred)
    if mask is not None: ok &= np.asarray(mask)
    if ok.sum() < 20: return None
    y = d.log_price.values[ok]; p = pred[ok]; pr = d.price.values[ok]
    r = dict(label=label, n=int(ok.sum()), r2=r2_score(y,p),
             medape=float(np.median(np.abs(np.exp(p)-pr)/pr)*100),
             sd=float(np.std(y-p)))
    return r

def show(rows):
    print(f"{'':44s} {'n':>5} {'R2':>7} {'MedAPE':>8} {'resid sd':>9}")
    for r in rows:
        if r: print(f"{r['label']:44s} {r['n']:5d} {r['r2']:7.3f} {r['medape']:7.1f}% {r['sd']:9.3f}")
