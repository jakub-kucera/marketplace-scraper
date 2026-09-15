"""Shared price-model feasibility harness.

One protocol for every category studied in docs/research/*_PRICE_MODEL.md, so the numbers
are comparable across corpora rather than each script inventing its own split.

Why the defaults are what they are (all measured, see MACBOOK_PRICE_MODEL.md §3 and
PRICE_MODEL_BENCHMARK.md §2.1):

- **Never a random split.** Marketplace corpora are full of relisted inventory and dealers
  posting the same machine repeatedly; a random k-fold puts the same physical listing on
  both sides and reports a number that means nothing (R2 0.925 leaky vs 0.873 honest).
  `grouped_cv` groups by seller and is the only protocol here that should be quoted for
  model comparison.
- **Pooled out-of-fold scoring**, not mean-of-folds: per-fold R2 divides by each fold's own
  variance, and seller folds are wildly heterogeneous. Pooling is ~0.011 higher and stable.
- **MedAPE in CZK, R2 on the log scale.** They disagree on purpose; R2 is driven by a tail
  the median never sees.
"""
from __future__ import annotations

import logging
import re
import unicodedata

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import r2_score
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import OrdinalEncoder

CSV = "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/data/ads.csv"


# ---------------------------------------------------------------- text utils
def strip_diacritics(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm(s) -> str:
    """Lowercase, de-accent, unify quote glyphs. Commas/slashes/pipes are PRESERVED --
    they are token barriers (PC_PRICE_MODEL.md §4.3: flattening `rx 6700 xt, 32gb` turns
    system RAM into VRAM and corrupts two features at once)."""
    s = (s or "")
    if not isinstance(s, str):
        s = ""
    s = s.lower()
    s = strip_diacritics(s)
    s = s.replace("”", '"').replace("“", '"').replace("’", "'").replace("´", "'")
    s = re.sub(r"''", '"', s)
    s = re.sub(r"\s+", " ", s)
    return s


def blob(row, full: bool = True) -> str:
    """name || short_description || full_description, normalised, `||` kept as a barrier."""
    parts = [row.get("name") or "", row.get("short_description") or ""]
    if full:
        parts.append(row.get("full_description") or "")
    parts = [p if isinstance(p, str) else "" for p in parts]
    return norm(" || ".join(parts))


# ---------------------------------------------------------------- corpus
def load(query_id, csv: str = CSV) -> pd.DataFrame:
    """One query's ads, oldest first. **No filtering of any kind is applied.**

    In particular this does NOT subset on `AdDelivery.status`, and must not start to. The
    corpus is every ad the scraper discovered for the query; what the filter later did with
    it is an outcome, not a sampling frame. Restricting to SENT would keep 17% of the ski
    corpus, 30% of the iPhone corpus and 8% of query 15 -- and it biases the price
    distribution in whichever direction that query's rules happen to cut (SENT vs the rest:
    ski 5 250 vs 7 500, iPhone 12 999 vs 8 900, desktops 15 000 vs 30 995).

    Rows with a null `price` are kept too, so the caller decides. Callers that model log
    price must drop them explicitly -- 12 Sbazar `Dohodou` rows and 1 Bazos MTB row in the
    2026-09-12 pull.
    """
    df = pd.read_csv(csv)
    qs = [query_id] if isinstance(query_id, int) else list(query_id)
    df = df[df.query_id.isin(qs)].copy()
    df["created"] = pd.to_datetime(df.created, utc=True, format="mixed")
    df = df.sort_values("created").reset_index(drop=True)
    for c in ("name", "short_description", "full_description", "location", "publisher_name"):
        df[c] = df[c].fillna("")
    df["seller"] = seller_key(df)
    df["has_full"] = df.full_description.str.len() > 0
    return df


def seller_key(df: pd.DataFrame) -> pd.Series:
    """email id, else phone id, else `publisher_name`, else `location`, else a per-row unique.

    The first two are the MACBOOK_PRICE_MODEL.md §9 identity. The next two are fallbacks a
    Bazos corpus never needs and the other three marketplaces cannot do without: **Vinted,
    Sbazar and the Bazos hidden API write no publisher ids at all**, so on those corpora the
    per-row fallback is 100% of rows and `GroupKFold` silently becomes a plain `KFold` --
    exactly the random split the protocol forbids, worth +0.019 to +0.462 R2 of false
    optimism across the eight Bazos corpora where a real key exists (mean +0.113).

    Sbazar populates `publisher_name` (a shop slug) on every row; the API query populates
    `location`, which is a measured conservative substitute -- across eight corpora with real
    ids, 97-100% of sellers occupy one locality and R2(location) - R2(seller) is mean -0.008,
    max +0.019. Vinted has neither and genuinely cannot be validated.
    See docs/research/CATEGORY_PRICE_MODELS.md §9.
    """
    e = df.email_publisher_id
    p = df.phone_publisher_id
    name = df.get("publisher_name", pd.Series("", index=df.index)).fillna("").astype(str)
    loc = df.get("location", pd.Series("", index=df.index)).fillna("").astype(str)
    out = np.where(e.notna(), "e" + e.fillna(0).astype("int64").astype(str),
          np.where(p.notna(), "p" + p.fillna(0).astype("int64").astype(str),
          np.where(name.str.len() > 0, "n" + name,
          np.where(loc.str.len() > 0, "l" + loc,
                   "x" + df.id.astype(str)))))
    return pd.Series(out, index=df.index)


# ---------------------------------------------------------------- design
def design(df, num=(), boo=(), cat=()):
    """Numeric + boolean + ordinal-encoded categorical matrix, for the tree path.

    Categoricals are ordinal-encoded and their column indices returned so
    HistGradientBoosting treats them natively; `Ridge` must NOT be given this matrix --
    use `design_ohe` for anything linear."""
    X = pd.DataFrame(index=df.index)
    for c in num:
        X[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    for c in boo:
        X[c] = df[c].astype(float)
    ci = []
    if cat:
        enc = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)
        E = pd.DataFrame(enc.fit_transform(df[list(cat)].astype(str)), columns=list(cat), index=df.index)
        X = pd.concat([X, E], axis=1)
        ci = [X.columns.get_loc(c) for c in cat]
    return X, ci


def design_ohe(df, num=(), boo=(), cat=(), min_level=5):
    """Median-imputed numerics + a `__na` indicator each, booleans, and one-hot categoricals
    with rare levels pooled into `__rare`. Pooling matters: a dummy seen 3 times is noise a
    linear model cannot shrink away on a corpus this size."""
    X = pd.DataFrame(index=df.index)
    for c in num:
        v = pd.to_numeric(df[c], errors="coerce").astype(float)
        X[f"{c}__na"] = v.isna().astype(float)
        X[c] = v.fillna(v.median() if v.notna().any() else 0.0)
    for c in boo:
        X[c] = df[c].astype(float)
    for c in cat:
        s = df[c].astype(str).fillna("na")
        keep = s.value_counts()
        keep = set(keep[keep >= min_level].index)
        s = s.where(s.isin(keep), "__rare")
        for lvl in sorted(s.unique()):
            X[f"{c}={lvl}"] = (s == lvl).astype(float)
    return X


# ---------------------------------------------------------------- metrics
def metrics(y_log, pred_log, price):
    """R2 on the log scale, MedAPE in CZK, residual sd. `price` is the CZK actual."""
    ok = ~np.isnan(pred_log)
    y, p, a = np.asarray(y_log)[ok], np.asarray(pred_log)[ok], np.asarray(price, float)[ok]
    if ok.sum() < 5:
        return dict(n=int(ok.sum()), r2=float("nan"), medape=float("nan"), sigma=float("nan"))
    ape = np.abs(np.exp(p) - a) / a
    return dict(n=int(ok.sum()), r2=float(r2_score(y, p)),
                medape=float(np.median(ape) * 100), sigma=float(np.std(y - p)))


def grouped_cv(df, X, ci, model="hgb", n_splits=5, repeats=3, groups=None, seed=0, alpha=1.0):
    """Pooled out-of-fold predictions under GroupKFold on the seller, averaged over
    `repeats` shuffled fold assignments. Returns (oof_log, n_groups).

    `repeats>1` is a variance reduction over the fold assignment, not more data -- it
    lifts every model's R2 by ~0.004 equally, so comparisons still hold."""
    y = df["log_price"].values
    g = np.asarray(groups if groups is not None else df["seller"].values)
    n_groups = len(set(g))
    # A key that is unique per row makes GroupKFold a plain KFold, and it does so silently --
    # the caller still gets a number, just an inflated one. Warn rather than refuse: a
    # degenerate key is sometimes the only key there is (Vinted), and the right response is to
    # label the number, not to have no number.
    if n_groups > 0.9 * len(g):
        logging.getLogger(__name__).warning(
            "grouped_cv: %d groups for %d rows (%.0f%% singletons) -- this is a random split "
            "in disguise, NOT a seller-grouped one. Do not quote the result as seller-grouped.",
            n_groups, len(g), 100 * n_groups / len(g),
        )
    n_splits = min(n_splits, n_groups)
    if n_splits < 2:
        return np.full(len(df), np.nan), n_groups
    acc = np.zeros((repeats, len(df))); acc[:] = np.nan
    for r in range(repeats):
        rng = np.random.RandomState(seed + r)
        uniq = np.array(sorted(set(g)))
        perm = rng.permutation(len(uniq))
        remap = {u: i for u, i in zip(uniq, perm)}
        gs = np.array([remap[v] for v in g])
        for tr, te in GroupKFold(n_splits).split(X, y, gs):
            m = _fit(model, X.iloc[tr], y[tr], ci, alpha)
            acc[r, te] = m.predict(X.iloc[te])
    return np.nanmean(acc, axis=0), n_groups


def time_split(df, X, ci, model="hgb", frac=0.7, alpha=1.0):
    """Past -> future. What production actually faces: the dealers' history IS known."""
    y = df["log_price"].values
    k = int(len(df) * frac)
    m = _fit(model, X.iloc[:k], y[:k], ci, alpha)
    out = np.full(len(df), np.nan)
    out[k:] = m.predict(X.iloc[k:])
    return out


def _fit(kind, Xtr, ytr, ci, alpha):
    if kind == "hgb":
        m = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.06, min_samples_leaf=10,
                                          l2_regularization=1.0, categorical_features=ci or None,
                                          random_state=0)
    elif kind == "ridge":
        m = Ridge(alpha=alpha)
    else:
        raise ValueError(kind)
    m.fit(Xtr, ytr)
    return m


def cluster_bootstrap_delta(df, oof_a, oof_b, n=800, seed=0):
    """Paired seller-cluster bootstrap of (a - b). Sellers are the unit of independence."""
    rng = np.random.RandomState(seed)
    y = df["log_price"].values; price = df["price"].values.astype(float)
    g = df["seller"].values
    idx_by = {}
    for i, s in enumerate(g):
        idx_by.setdefault(s, []).append(i)
    sellers = list(idx_by)
    ok = ~(np.isnan(oof_a) | np.isnan(oof_b))
    dr, dm = [], []
    for _ in range(n):
        pick = rng.choice(len(sellers), len(sellers), replace=True)
        rows = np.concatenate([idx_by[sellers[j]] for j in pick])
        rows = rows[ok[rows]]
        if len(rows) < 30:
            continue
        ma = metrics(y[rows], oof_a[rows], price[rows])
        mb = metrics(y[rows], oof_b[rows], price[rows])
        dr.append(ma["r2"] - mb["r2"]); dm.append(ma["medape"] - mb["medape"])
    q = lambda v: (float(np.mean(v)), float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5)))
    return dict(dr2=q(dr), dmedape=q(dm), reps=len(dr))


def alert_funnel(df, oof, thresholds=(0.15, 0.20, 0.25, 0.30, 0.40), gate=None):
    """How many listings land below prediction by each margin, per week.

    `gate` is a boolean Series of rows the model would agree to score at all. Reporting
    gated and ungated volume side by side is the point -- an ungated funnel on a corpus
    where half the specs do not parse is mostly counting extraction failures."""
    days = max(1.0, (df.created.max() - df.created.min()).total_seconds() / 86400)
    weeks = days / 7.0
    resid = np.log(df.price.values.astype(float)) - oof
    out = []
    for t in thresholds:
        hit = resid <= np.log(1 - t)
        row = {"threshold": t, "n": int(np.nansum(hit)), "per_week": float(np.nansum(hit) / weeks)}
        if gate is not None:
            gh = hit & np.asarray(gate, bool)
            row["n_gated"] = int(np.nansum(gh)); row["per_week_gated"] = float(np.nansum(gh) / weeks)
        out.append(row)
    return pd.DataFrame(out), weeks


def coverage(df, fields):
    """Extraction coverage per field, split by whether the row has a full_description --
    the single most decision-relevant table in a feasibility study."""
    rows = []
    for f in fields:
        v = df[f].notna()
        r = {"field": f, "all": 100 * v.mean()}
        if df.has_full.any() and (~df.has_full).any():
            r["short_only"] = 100 * v[~df.has_full].mean()
            r["with_full"] = 100 * v[df.has_full].mean()
            r["gain_pp"] = r["with_full"] - r["short_only"]
        rows.append(r)
    return pd.DataFrame(rows)


def market_structure(df):
    """Seller concentration -- decides whether the MacBook seller-aware machinery transfers
    at all. Half the sellers appearing once makes a per-seller baseline unbuildable
    (PC_PRICE_MODEL.md §3)."""
    vc = df.seller.value_counts()
    return dict(
        ads=len(df), sellers=int(vc.size),
        median_ads_per_seller=float(vc.median()),
        top10_share=float(vc.head(10).sum() / len(df) * 100),
        oneoff_seller_share=float((vc == 1).sum() / vc.size * 100),
        ads_from_oneoffs=float(vc[vc == 1].sum() / len(df) * 100),
        identified_seller_share=float((~df.seller.str.startswith("x")).mean() * 100),
        days=float((df.created.max() - df.created.min()).total_seconds() / 86400),
        ads_per_day=float(len(df) / max(1.0, (df.created.max() - df.created.min()).total_seconds() / 86400)),
    )
