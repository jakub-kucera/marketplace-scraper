"""Feature builders for the price-model benchmark.

Two design matrices:

  * `raw_frame(d)`  -- adds the derived columns every model needs (log2 ram/ssd, log1p views...)
  * `prep(kind)`    -- a leak-free sklearn preprocessor. Imputation medians and one-hot
                       vocabularies are learned on the TRAIN fold only, never on the full frame.

`kind`:
  'lin'     numeric (median-imputed + missing indicator, standardised) + one-hot cats + bools
  'spline'  same, but `year` goes through a cubic B-spline basis instead of entering linearly
  'tree'    same columns, no scaling, no imputation -- for HGB, which handles NaN natively;
            categoricals ordinal-encoded and declared categorical.
"""
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import (OneHotEncoder, OrdinalEncoder, SplineTransformer,
                                   StandardScaler)

BOOL = ['warranty', 'new', 'defect', 'battery_new', 'vat_dph', 'cz_kbd', 'us_kbd',
        'touchbar', 'retina', 'top_word', 'scratches', 'urgent', 'box', 'swap']

YEAR_KNOTS = (2016, 2018, 2020, 2022, 2024)
HINGE = [f'yh_{k}' for k in YEAR_KNOTS]

NUM = ['year', 'screen', 'ram_log2', 'ssd_log2', 'battery_pct', 'cycles_log1p', 'views_log1p']
CAT = ['family', 'chip_key', 'region']


def raw_frame(d):
    """Derived columns. Pure function of `d`; no fitting, so it may run on the whole frame."""
    f = pd.DataFrame(index=d.index)
    f['year'] = d.year.astype(float)
    f['screen'] = d.screen.astype(float)
    f['ram_log2'] = np.log2(d.ram_gb.astype(float))
    f['ssd_log2'] = np.log2(d.ssd_gb.astype(float))
    f['battery_pct'] = d.battery_pct.astype(float)
    f['cycles_log1p'] = np.log1p(d.cycles.astype(float))
    f['views_log1p'] = np.log1p(d.view_count.astype(float))
    f['family'] = d.family.astype(str)
    f['chip_key'] = d.chip_key.astype(str)
    # town_g is 90% Praha; collapse to a 3-level region so one-hot does not spray 16 dummies
    f['region'] = np.where(d.town_g.astype(str).str.startswith('Praha'), 'praha',
                           np.where(d.town_g.astype(str) == 'other', 'other', 'region'))
    # chip-family indicators. The GBM's whole margin sits in rows where the chip is
    # unidentified or Intel (see the SSE decomposition), because it fits those a separate
    # sub-function. `InteractDesign` gives a linear model the same freedom.
    # piecewise-linear year: `year` plus hinges max(0, year-k). Spans the same shape space as
    # a cubic spline for this purpose and needs only max() at serve time, so it fits the
    # existing JSON manifest with one new feature kind instead of a B-spline evaluator.
    _yr = d.year.astype(float)
    for k in YEAR_KNOTS:
        f[f'yh_{k}'] = np.maximum(0.0, _yr - k)
    f['year_miss'] = (~np.isfinite(d.year.astype(float))).astype(float)
    f['is_intel'] = (d.chip_brand.astype(str) == 'intel').astype(float)
    f['is_chipunk'] = (d.chip_key.astype(str) == 'unknown').astype(float)
    f['is_air'] = (d.family.astype(str) == 'air').astype(float)

    # exact configuration as a single categorical: one-hot + ridge shrinkage turns the
    # config-median lookup into a linear model that still exports as plain coefficients
    _g = lambda c, fmt: d[c].map(lambda v: 'na' if not np.isfinite(v) else fmt % v).astype(str)
    f['cfg'] = (d.family.astype(str) + '|' + d.chip_key.astype(str) + '|'
                + _g('ram_gb', '%d') + '|' + _g('ssd_gb', '%d'))
    f['screen_s'] = d.screen.map(lambda v: 'na' if not np.isfinite(v) else f'{v:.1f}').astype(str)
    f['year_s'] = d.year.map(lambda v: 'na' if not np.isfinite(v) else str(int(v))).astype(str)
    for c in BOOL:
        f[c] = d[c].astype(float)
    return f


def prep(kind='lin', spline_knots=6):
    if kind == 'tree':
        return ColumnTransformer(
            [('num', 'passthrough', NUM + BOOL),
             ('cat', OrdinalEncoder(handle_unknown='use_encoded_value', unknown_value=np.nan,
                                    encoded_missing_value=np.nan), CAT)],
            remainder='drop', verbose_feature_names_out=False)

    num_pipe = Pipeline([('imp', SimpleImputer(strategy='median', add_indicator=True)),
                         ('sc', StandardScaler())])
    onehot = OneHotEncoder(handle_unknown='ignore', drop='first', sparse_output=False)

    if kind == 'lin':
        return ColumnTransformer(
            [('num', num_pipe, NUM),
             ('cat', onehot, CAT),
             ('bool', 'passthrough', BOOL)],
            remainder='drop', verbose_feature_names_out=False)

    if kind == 'spline':
        year_pipe = Pipeline([
            ('imp', SimpleImputer(strategy='median')),
            ('sp', SplineTransformer(n_knots=spline_knots, degree=3, include_bias=False))])
        rest = [c for c in NUM if c != 'year']
        return ColumnTransformer(
            [('year', year_pipe, ['year']),
             ('ymiss', 'passthrough', ['year_miss']),
             ('num', num_pipe, rest),
             ('cat', onehot, CAT),
             ('bool', 'passthrough', BOOL)],
            remainder='drop', verbose_feature_names_out=False)

    if kind == 'yearcat':
        # year as a 15-level categorical ('na' is its own level) -- maximum flexibility in
        # the dominant feature, and missingness handled without an imputer
        rest = [c for c in NUM if c != 'year']
        return ColumnTransformer(
            [('yearcat', OneHotEncoder(handle_unknown='ignore', drop='first',
                                       sparse_output=False), ['year_s']),
             ('num', num_pipe, rest),
             ('cat', onehot, CAT),
             ('bool', 'passthrough', BOOL)],
            remainder='drop', verbose_feature_names_out=False)

    if kind == 'hinge':
        return ColumnTransformer(
            [('num', num_pipe, NUM + HINGE),
             ('ymiss', 'passthrough', ['year_miss']),
             ('cat', onehot, CAT),
             ('bool', 'passthrough', BOOL)],
            remainder='drop', verbose_feature_names_out=False)

    if kind == 'rich':
        # year as a cubic spline, screen as a categorical (13.3 / 13.6 / 14.2 are distinct
        # product generations, not points on a continuum), everything else as in 'lin'
        year_pipe = Pipeline([
            ('imp', SimpleImputer(strategy='median')),
            ('sp', SplineTransformer(n_knots=spline_knots, degree=3, include_bias=False))])
        rest = [c for c in NUM if c not in ('year', 'screen')]
        return ColumnTransformer(
            [('year', year_pipe, ['year']),
             ('ymiss', 'passthrough', ['year_miss']),
             ('scr', OneHotEncoder(handle_unknown='ignore', drop='first',
                                   sparse_output=False), ['screen_s']),
             ('num', num_pipe, rest),
             ('cat', onehot, CAT),
             ('bool', 'passthrough', BOOL)],
            remainder='drop', verbose_feature_names_out=False)

    if kind == 'config':
        year_pipe = Pipeline([
            ('imp', SimpleImputer(strategy='median')),
            ('sp', SplineTransformer(n_knots=spline_knots, degree=3, include_bias=False))])
        rest = [c for c in NUM if c not in ('year', 'screen')]
        return ColumnTransformer(
            [('year', year_pipe, ['year']),
             ('ymiss', 'passthrough', ['year_miss']),
             ('cfg', OneHotEncoder(handle_unknown='infrequent_if_exist', min_frequency=3,
                                   sparse_output=False), ['cfg']),
             ('scr', OneHotEncoder(handle_unknown='ignore', drop='first',
                                   sparse_output=False), ['screen_s']),
             ('num', num_pipe, rest),
             ('cat', onehot, CAT),
             ('bool', 'passthrough', BOOL)],
            remainder='drop', verbose_feature_names_out=False)

    raise ValueError(kind)


def tree_cat_idx():
    """Column positions of the categoricals in the 'tree' design, for HGB."""
    return list(range(len(NUM + BOOL), len(NUM + BOOL) + len(CAT)))


def feature_names(fitted_ct):
    try:
        return list(fitted_ct.get_feature_names_out())
    except Exception:
        return None


class InteractDesign(BaseEstimator, TransformerMixin):
    """`prep(kind)` plus a full copy of it multiplied by each indicator in `by`.

    That is a separate slope vector per chip family, still expressed as one coefficient
    vector -- so it exports to a JSON manifest exactly like a plain linear model.
    """

    def __init__(self, kind='rich', by=('is_intel', 'is_chipunk')):
        self.kind = kind
        self.by = by

    def fit(self, X, y=None):
        self.ct_ = prep(self.kind).fit(X, y)
        return self

    def transform(self, X):
        A = self.ct_.transform(X)
        blocks = [A] + [A * np.asarray(X[b], float).reshape(-1, 1) for b in self.by]
        return np.hstack(blocks)

    def get_feature_names_out(self, input_features=None):
        base = list(self.ct_.get_feature_names_out())
        return np.array(base + [f'{b}:{n}' for b in self.by for n in base], dtype=object)
