"""Evaluation protocols for the price-model benchmark.

Everything here obeys three rules:
  1. no random train/test split -- grouped-by-seller or chronological only;
  2. hyperparameters are chosen inside the training fold (nested CV), never on the test fold;
  3. preprocessing (imputation medians, one-hot vocabularies) is fitted inside the pipeline,
     so it is refitted per fold.
"""
import itertools
import numpy as np
from sklearn.base import clone
from sklearn.metrics import r2_score
from sklearn.model_selection import GroupKFold

# ---------------------------------------------------------------- metrics


def metrics(y_log, pred_log, price):
    """R^2 on log price, median/mean absolute % error in CZK, residual sd on log."""
    ok = ~np.isnan(pred_log)
    y, p, pr = y_log[ok], pred_log[ok], price[ok]
    ape = np.abs(np.exp(p) - pr) / pr
    return dict(n=int(ok.sum()), cov=float(ok.mean()),
                r2=float(r2_score(y, p)),
                medape=float(np.median(ape) * 100),
                mape=float(np.mean(ape) * 100),
                rmse_log=float(np.sqrt(np.mean((y - p) ** 2))),
                sd_log=float(np.std(y - p)))


def fold_table(y_log, pred_log, price, fold_id):
    """Per-fold metrics -> (mean, std) across folds. Folds are the unit of noise."""
    out = []
    for f in np.unique(fold_id):
        m = fold_id == f
        if m.sum() < 20:
            continue
        out.append(metrics(y_log[m], pred_log[m], price[m]))
    agg = {}
    for k in ('r2', 'medape', 'rmse_log'):
        v = np.array([o[k] for o in out])
        agg[k + '_mean'] = float(v.mean())
        agg[k + '_std'] = float(v.std(ddof=1))
    agg['folds'] = len(out)
    return agg, out


# ---------------------------------------------------------------- nested grouped CV


def _grid(param_grid):
    if not param_grid:
        return [{}]
    keys = list(param_grid)
    return [dict(zip(keys, vals)) for vals in itertools.product(*[param_grid[k] for k in keys])]


def _inner_select(est, param_grid, X, y, g, n_inner):
    combos = _grid(param_grid)
    if len(combos) == 1:
        return combos[0], None
    inner = GroupKFold(n_splits=n_inner)
    best, best_s, curve = None, -np.inf, []
    for pars in combos:
        s = []
        for tr, te in inner.split(X, y, g):
            m = clone(est).set_params(**pars)
            m.fit(X.iloc[tr], y[tr])
            s.append(r2_score(y[te], m.predict(X.iloc[te])))
        ms = float(np.mean(s))
        curve.append((pars, ms))
        if ms > best_s:
            best, best_s = pars, ms
    return best, curve


def nested_group_cv(est, param_grid, X, y, price, groups, n_outer=5, n_inner=4, repeats=3):
    """Repeated nested GroupKFold by seller. Returns OOF predictions per repeat + fold ids."""
    n = len(y)
    preds = np.full((repeats, n), np.nan)
    folds = np.full((repeats, n), -1)
    chosen = []
    for r in range(repeats):
        outer = GroupKFold(n_splits=n_outer, shuffle=True, random_state=r)
        for k, (tr, te) in enumerate(outer.split(X, y, groups)):
            pars, _ = _inner_select(est, param_grid, X.iloc[tr], y[tr], groups[tr], n_inner)
            m = clone(est).set_params(**pars)
            m.fit(X.iloc[tr], y[tr])
            preds[r, te] = m.predict(X.iloc[te])
            folds[r, te] = k
            chosen.append(pars)
    return preds, folds, chosen


def plain_group_cv(est, param_grid, X, y, groups, n_outer=5, n_inner=4):
    """One non-shuffled GroupKFold -- the protocol the previously published numbers used."""
    n = len(y)
    pred = np.full(n, np.nan)
    for tr, te in GroupKFold(n_splits=n_outer).split(X, y, groups):
        pars, _ = _inner_select(est, param_grid, X.iloc[tr], y[tr], groups[tr], n_inner)
        m = clone(est).set_params(**pars)
        m.fit(X.iloc[tr], y[tr])
        pred[te] = m.predict(X.iloc[te])
    return pred


def summarise_repeats(y, price, preds, folds):
    """Pooled OOF metrics per repeat, and per-fold spread pooled over all repeats*folds."""
    pooled = [metrics(y, preds[r], price) for r in range(preds.shape[0])]
    per_fold = []
    for r in range(preds.shape[0]):
        _, rows = fold_table(y, preds[r], price, folds[r])
        per_fold += rows
    out = {}
    for k in ('r2', 'medape', 'rmse_log'):
        v = np.array([p[k] for p in pooled])
        out[k] = float(v.mean())
        out[k + '_rep_sd'] = float(v.std(ddof=1)) if len(v) > 1 else 0.0
        f = np.array([p[k] for p in per_fold])
        out[k + '_fold_sd'] = float(f.std(ddof=1))
    out['n_folds'] = len(per_fold)
    out['oof_mean'] = preds.mean(axis=0)
    return out


# ---------------------------------------------------------------- chronological


def time_split_eval(est, param_grid, X, y, price, order, train_frac=0.70, n_inner=4):
    """Train on the first `train_frac` of the window, test on the rest.

    Hyperparameters are picked by expanding-window CV *inside* the training slice, so the
    future is never used to tune. `order` must be the chronological ordering index.
    """
    n = len(y)
    cut = int(n * train_frac)
    tr, te = order[:cut], order[cut:]
    combos = _grid(param_grid)
    if len(combos) > 1:
        # expanding window over the training slice only
        bounds = np.linspace(0.4, 1.0, n_inner + 1)
        best, best_s = None, -np.inf
        for pars in combos:
            s = []
            for i in range(n_inner):
                a, b = int(cut * bounds[i]), int(cut * bounds[i + 1])
                if b - a < 40 or a < 60:
                    continue
                m = clone(est).set_params(**pars)
                m.fit(X.iloc[order[:a]], y[order[:a]])
                s.append(r2_score(y[order[a:b]], m.predict(X.iloc[order[a:b]])))
            if s and np.mean(s) > best_s:
                best, best_s = pars, float(np.mean(s))
        pars = best or combos[0]
    else:
        pars = combos[0]
    m = clone(est).set_params(**pars)
    m.fit(X.iloc[tr], y[tr])
    p = np.full(n, np.nan)
    p[te] = m.predict(X.iloc[te])
    res = metrics(y[te], p[te], price[te])
    res['params'] = pars
    return res, p


def replay(est, X, y, order, start_frac=0.30, step=150, params=None):
    """Expanding-window past->future replay: refit every `step` ads on everything before."""
    n = len(y)
    pred = np.full(n, np.nan)
    start = int(n * start_frac)
    for s in range(start, n, step):
        e = min(s + step, n)
        tr = order[:s]
        if len(tr) < 60:
            continue
        m = clone(est)
        if params:
            m.set_params(**params)
        m.fit(X.iloc[tr], y[tr])
        pred[order[s:e]] = m.predict(X.iloc[order[s:e]])
    return pred


# ---------------------------------------------------------------- inference


def cluster_bootstrap_delta(y, price, pa, pb, groups, B=2000, seed=0):
    """Paired difference (a - b) in R^2 and MedAPE, resampling SELLERS with replacement.

    The unit of independence is the seller, not the ad: 56% of ads come from ten dealers.
    """
    rng = np.random.default_rng(seed)
    ok = ~np.isnan(pa) & ~np.isnan(pb)
    y, price, pa, pb, groups = y[ok], price[ok], pa[ok], pb[ok], groups[ok]
    uniq, inv = np.unique(groups, return_inverse=True)
    idx_by_g = [np.where(inv == i)[0] for i in range(len(uniq))]
    dr2, dmed = [], []
    for _ in range(B):
        pick = rng.integers(0, len(uniq), len(uniq))
        idx = np.concatenate([idx_by_g[i] for i in pick])
        ya, pra = y[idx], price[idx]
        a, b = pa[idx], pb[idx]
        dr2.append(r2_score(ya, a) - r2_score(ya, b))
        dmed.append(np.median(np.abs(np.exp(a) - pra) / pra) * 100
                    - np.median(np.abs(np.exp(b) - pra) / pra) * 100)
    q = lambda v: (float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5)))
    return dict(d_r2=float(np.mean(dr2)), d_r2_ci=q(dr2),
                d_medape=float(np.mean(dmed)), d_medape_ci=q(dmed))
