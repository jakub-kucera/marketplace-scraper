"""The model ladder: every candidate as an sklearn estimator over the same X."""
import numpy as np
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import (ElasticNet, HuberRegressor, Lasso, LinearRegression,
                                  QuantileRegressor, Ridge)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import PolynomialFeatures
from sklearn.tree import DecisionTreeRegressor

import bm_features as F


# ---------------------------------------------------------------- non-ML baseline
class ConfigMedian(BaseEstimator, RegressorMixin):
    """Median log price of the closest matching configuration seen in training.

    Ladder, most specific first:
        L1  family + chip + RAM + SSD          ("exact config")
        L2  family + chip + screen
        L3  family + chip
        L4  global median
    A level is used only if it has >= `min_n` training comparables. With `fallback=False`
    the estimator returns NaN below L1 -- that is the honest coverage of a pure lookup.
    """

    def __init__(self, min_n=3, fallback=True, levels=(1, 2, 3)):
        self.min_n = min_n
        self.fallback = fallback
        self.levels = levels

    @staticmethod
    def _keys(X):
        s = lambda c: X[c].astype(str).fillna('na') if hasattr(X[c], 'fillna') else X[c].astype(str)
        fam, chip = s('family'), s('chip_key')
        ram = X.ram_log2.map(lambda v: 'na' if np.isnan(v) else f'{v:.1f}')
        ssd = X.ssd_log2.map(lambda v: 'na' if np.isnan(v) else f'{v:.1f}')
        scr = X.screen.map(lambda v: 'na' if np.isnan(v) else f'{v:.1f}')
        return {1: fam + '|' + chip + '|' + ram + '|' + ssd,
                2: fam + '|' + chip + '|' + scr,
                3: fam + '|' + chip}

    def fit(self, X, y):
        y = np.asarray(y, float)
        k = self._keys(X)
        self.tab_ = {}
        for lv in self.levels:
            import pandas as pd
            g = pd.DataFrame({'k': k[lv].values, 'y': y}).groupby('k').y
            med, cnt = g.median(), g.size()
            self.tab_[lv] = med[cnt >= self.min_n].to_dict()
        self.glob_ = float(np.median(y))
        return self

    def predict(self, X):
        k = self._keys(X)
        out = np.full(len(X), np.nan)
        for lv in self.levels:
            miss = np.isnan(out)
            if not miss.any():
                break
            vals = k[lv].map(self.tab_[lv]).values.astype(float)
            out[miss] = vals[miss]
            if not self.fallback:
                break
        if self.fallback:
            out[np.isnan(out)] = self.glob_
        return out


def _pipe(kind, est, **extra):
    steps = [('prep', F.prep(kind))]
    steps += list(extra.pop('mid', []))
    steps.append(('m', est))
    return Pipeline(steps)


def ladder():
    """name -> (estimator, param_grid, note). Grids are searched by *inner* CV only."""
    hgb_kw = dict(categorical_features=F.tree_cat_idx(), random_state=0)
    L = {}
    L['median_global'] = (DummyRegressor(strategy='median'), {}, 'constant')
    L['mean_global'] = (DummyRegressor(strategy='mean'), {}, 'constant')
    L['config_median_strict'] = (ConfigMedian(min_n=3, fallback=False, levels=(1,)), {},
                                 'exact-config lookup, no fallback (partial coverage)')
    L['config_median_ladder'] = (ConfigMedian(min_n=3, fallback=True), {},
                                 'config lookup with a fallback ladder (full coverage)')
    L['ols'] = (_pipe('lin', LinearRegression()), {}, 'OLS, year linear')
    L['ols_spline'] = (_pipe('spline', LinearRegression()), {}, 'OLS, year as cubic spline')
    L['ridge'] = (_pipe('lin', Ridge()),
                  {'m__alpha': [0.1, 0.3, 1, 3, 10, 30, 100]}, 'ridge, year linear')
    L['ridge_spline'] = (_pipe('spline', Ridge()),
                         {'m__alpha': [0.1, 0.3, 1, 3, 10, 30, 100]}, 'ridge, year spline')
    L['ridge_hinge'] = (_pipe('hinge', Ridge()),
                        {'m__alpha': [0.1, 0.3, 1, 3, 10, 30]},
                        'ridge, year piecewise-linear (hinges at 2016/18/20/22/24)')
    L['ridge_yearcat'] = (_pipe('yearcat', Ridge()),
                          {'m__alpha': [0.1, 0.3, 1, 3, 10, 30]},
                          'ridge, year as a 15-level categorical')
    L['lasso'] = (_pipe('lin', Lasso(max_iter=20000)),
                  {'m__alpha': [3e-4, 1e-3, 3e-3, 1e-2, 3e-2, 1e-1]}, 'lasso')
    L['enet'] = (_pipe('lin', ElasticNet(max_iter=20000)),
                 {'m__alpha': [1e-3, 3e-3, 1e-2, 3e-2, 1e-1],
                  'm__l1_ratio': [0.1, 0.5, 0.9]}, 'elastic net')
    L['ridge_inter'] = (Pipeline([('prep', F.prep('spline')),
                                  ('poly', PolynomialFeatures(2, interaction_only=True,
                                                              include_bias=False)),
                                  ('m', Ridge())]),
                        {'m__alpha': [1, 3, 10, 30, 100, 300, 1000]},
                        'ridge on all pairwise interactions of the spline design')
    # --- same linear form, different loss. MedAPE is a MEDIAN of |exp(p)-price|/price, and
    # for small residuals that is |p - y| on the log scale: fitting the conditional MEDIAN
    # (L1) rather than the conditional MEAN (L2) optimises the metric we actually report.
    L['ridge_rich'] = (_pipe('rich', Ridge()),
                       {'m__alpha': [0.3, 1, 3, 10, 30, 100]},
                       'ridge, year spline + screen categorical')
    L['ridge_config'] = (_pipe('config', Ridge()),
                         {'m__alpha': [1, 3, 10, 30, 100, 300]},
                         'ridge on spec main effects + one-hot EXACT CONFIG dummies')
    L['ridge_seg'] = (Pipeline([('prep', F.InteractDesign('rich')), ('m', Ridge())]),
                      {'m__alpha': [3, 10, 30, 100, 300, 1000]},
                      'ridge with a separate slope vector per chip family (Apple/Intel/unknown)')
    L['l1_seg'] = (Pipeline([('prep', F.InteractDesign('rich')),
                             ('m', QuantileRegressor(quantile=0.5, solver='highs'))]),
                   {'m__alpha': [1e-3, 3e-3, 1e-2, 3e-2]},
                   'median regression with a separate slope vector per chip family')
    L['huber_rich'] = (_pipe('rich', HuberRegressor(max_iter=2000)),
                       {'m__alpha': [1e-4, 1e-3, 1e-2, 1e-1],
                        'm__epsilon': [1.1, 1.35, 2.0]},
                       'Huber (robust) on the rich design')
    L['l1_rich'] = (_pipe('rich', QuantileRegressor(quantile=0.5, solver='highs')),
                    {'m__alpha': [1e-4, 1e-3, 1e-2, 3e-2]},
                    'L1 / median regression on the rich design')
    L['l1_lin'] = (_pipe('lin', QuantileRegressor(quantile=0.5, solver='highs')),
                   {'m__alpha': [1e-4, 1e-3, 1e-2, 3e-2]},
                   'L1 / median regression, year linear')
    L['hgb_l1'] = (_pipe('tree', HistGradientBoostingRegressor(
        loss='absolute_error', **hgb_kw)),
        {'m__learning_rate': [0.06, 0.1]},
        'HistGradientBoosting fitted to the conditional median')
    L['tree'] = (_pipe('lin', DecisionTreeRegressor(random_state=0)),
                 {'m__max_depth': [3, 4, 5, 6, 8, None],
                  'm__min_samples_leaf': [5, 10, 20]}, 'single CART')
    L['rf'] = (_pipe('lin', RandomForestRegressor(n_estimators=400, n_jobs=-1, random_state=0)),
               {'m__max_features': [0.3, 0.6, 1.0],
                'm__min_samples_leaf': [1, 3]}, 'random forest')
    L['hgb'] = (_pipe('tree', HistGradientBoostingRegressor(**hgb_kw)),
                {'m__learning_rate': [0.06, 0.1],
                 'm__max_leaf_nodes': [15, 31]}, 'HistGradientBoosting, tuned')
    L['hgb_incumbent'] = (_pipe('tree', HistGradientBoostingRegressor(
        max_iter=180, learning_rate=0.06, min_samples_leaf=15, l2_regularization=1.0, **hgb_kw)),
        {}, 'HistGradientBoosting with the incumbent hand-set params')
    return L
