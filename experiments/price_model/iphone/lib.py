"""Protocol A/B with nested alpha and ALL preprocessing inside the fold."""
import sys
sys.path.insert(0, "/Users/jakubkucera-sch/Documents/scraper/experiments/price_model/common")
import numpy as np, pandas as pd
from sklearn.linear_model import Ridge
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import GroupKFold
from sklearn.metrics import r2_score
import ph

ALPHAS = (0.03, 0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0)


class OheFit:
    """Median impute + __na, booleans, one-hot with vocab learned on TRAIN only, z-scale."""
    def __init__(self, num=(), boo=(), cat=(), min_level=5, scale=True):
        self.num, self.boo, self.cat = list(num), list(boo), list(cat)
        self.min_level, self.scale = min_level, scale

    def fit(self, df):
        self.med_ = {}
        for c in self.num:
            v = pd.to_numeric(df[c], errors="coerce").astype(float)
            self.med_[c] = float(v.median()) if v.notna().any() else 0.0
        self.lv_ = {}
        for c in self.cat:
            s = df[c].astype(str).fillna("na")
            vc = s.value_counts()
            self.lv_[c] = sorted(vc[vc >= self.min_level].index)
        X = self._raw(df)
        self.cols_ = list(X.columns)
        self.mu_ = np.array(X.mean().values, dtype=float) if self.scale else np.zeros(X.shape[1])
        sd = np.array(X.std().values, dtype=float) if self.scale else np.ones(X.shape[1])
        sd[sd == 0] = 1.0
        self.sd_ = sd
        return self

    def _raw(self, df):
        X = pd.DataFrame(index=df.index)
        for c in self.num:
            v = pd.to_numeric(df[c], errors="coerce").astype(float)
            X[f"{c}__na"] = v.isna().astype(float)
            X[c] = v.fillna(self.med_[c])
        for c in self.boo:
            X[c] = df[c].astype(float)
        for c in self.cat:
            s = df[c].astype(str).fillna("na")
            keep = set(self.lv_[c])
            s = s.where(s.isin(keep), "__rare")
            for lvl in self.lv_[c] + ["__rare"]:
                X[f"{c}={lvl}"] = (s == lvl).astype(float)
        return X

    def transform(self, df):
        X = self._raw(df)
        for c in self.cols_:
            if c not in X.columns:
                X[c] = 0.0
        X = X[self.cols_]
        return (X.values - self.mu_) / self.sd_


def _pick_alpha(dtr, spec, groups, seed=0):
    y = dtr["log_price"].values
    g = np.asarray(groups)
    ng = len(set(g))
    if ng < 3:
        return 1.0
    best, ba = np.inf, 1.0
    gk = GroupKFold(min(3, ng))
    scores = {a: [] for a in ALPHAS}
    for tr, te in gk.split(dtr, y, g):
        f = OheFit(**spec).fit(dtr.iloc[tr])
        Xtr, Xte = f.transform(dtr.iloc[tr]), f.transform(dtr.iloc[te])
        for a in ALPHAS:
            m = Ridge(alpha=a).fit(Xtr, y[tr])
            scores[a].append(np.mean((m.predict(Xte) - y[te]) ** 2))
    for a in ALPHAS:
        s = np.mean(scores[a])
        if s < best:
            best, ba = s, a
    return ba


def cv_ridge(d, spec, n_splits=5, repeats=3, seed=0, groups=None, return_alphas=False):
    y = d["log_price"].values
    g = np.asarray(groups if groups is not None else d["seller"].values)
    ng = len(set(g))
    acc = np.full((repeats, len(d)), np.nan)
    alphas = []
    for r in range(repeats):
        rng = np.random.RandomState(seed + r)
        uniq = np.array(sorted(set(g)))
        remap = {u: i for u, i in zip(uniq, rng.permutation(len(uniq)))}
        gs = np.array([remap[v] for v in g])
        for tr, te in GroupKFold(min(n_splits, ng)).split(d, y, gs):
            a = _pick_alpha(d.iloc[tr], spec, gs[tr])
            alphas.append(a)
            f = OheFit(**spec).fit(d.iloc[tr])
            m = Ridge(alpha=a).fit(f.transform(d.iloc[tr]), y[tr])
            acc[r, te] = m.predict(f.transform(d.iloc[te]))
    out = np.nanmean(acc, axis=0)
    return (out, alphas) if return_alphas else out


def cv_hgb(d, num=(), boo=(), cat=(), n_splits=5, repeats=3, seed=0, groups=None):
    y = d["log_price"].values
    g = np.asarray(groups if groups is not None else d["seller"].values)
    ng = len(set(g))
    acc = np.full((repeats, len(d)), np.nan)
    for r in range(repeats):
        rng = np.random.RandomState(seed + r)
        uniq = np.array(sorted(set(g)))
        remap = {u: i for u, i in zip(uniq, rng.permutation(len(uniq)))}
        gs = np.array([remap[v] for v in g])
        X, ci = ph.design(d, num=num, boo=boo, cat=cat)
        for tr, te in GroupKFold(min(n_splits, ng)).split(d, y, gs):
            m = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.06,
                                              min_samples_leaf=10, l2_regularization=1.0,
                                              categorical_features=ci or None, random_state=0)
            m.fit(X.iloc[tr], y[tr])
            acc[r, te] = m.predict(X.iloc[te])
    return np.nanmean(acc, axis=0)


def cv_config_median(d, keys, kmin=3, n_splits=5, repeats=3, seed=0, groups=None):
    """Median log price of the exact config, learned on the training fold only.
    NaN where the training fold holds < kmin comparables -- that is the coverage cost."""
    y = d["log_price"].values
    g = np.asarray(groups if groups is not None else d["seller"].values)
    ng = len(set(g))
    key = d[list(keys)].apply(lambda c: c.astype(object).where(c.notna(), "na").astype(str)).agg("|".join, axis=1).values
    acc = np.full((repeats, len(d)), np.nan)
    for r in range(repeats):
        rng = np.random.RandomState(seed + r)
        uniq = np.array(sorted(set(g)))
        remap = {u: i for u, i in zip(uniq, rng.permutation(len(uniq)))}
        gs = np.array([remap[v] for v in g])
        for tr, te in GroupKFold(min(n_splits, ng)).split(d, y, gs):
            tab = pd.DataFrame({"k": key[tr], "y": y[tr]}).groupby("k")["y"].agg(["median", "size"])
            tab = tab[tab["size"] >= kmin]["median"]
            acc[r, te] = pd.Series(key[te]).map(tab).values
    return np.nanmean(acc, axis=0)


def M(d, oof, mask=None):
    m = np.ones(len(d), bool) if mask is None else np.asarray(mask, bool)
    return ph.metrics(d.log_price.values[m], np.asarray(oof)[m], d.price.values.astype(float)[m])


def boot(d, a, b, n=2000, seed=0):
    return ph.cluster_bootstrap_delta(d, a, b, n=n, seed=seed)
