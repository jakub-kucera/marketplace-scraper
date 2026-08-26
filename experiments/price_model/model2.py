import pandas as pd, numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import GroupKFold
from sklearn.metrics import r2_score, mean_absolute_error
from sklearn.inspection import permutation_importance
from sklearn.preprocessing import OrdinalEncoder

d = pd.read_pickle('mb/ds.pkl')
CAT = ['family','chip_key','chip_variant','town_g','chip_brand']
NUM = ['year','age','screen','ram_gb','ssd_gb','ram_log','storage_log','seller_ads','dow','days',
       'battery_pct','cycles','view_count']
BOOL= ['warranty','new','defect','battery_new','vat_dph','cz_kbd','us_kbd','touchbar','retina',
       'top_word','scratches','urgent','box','swap','is_dealer']
def make_X(df):
    X = df[NUM].astype(float).copy()
    for c in BOOL: X[c] = df[c].astype(float)
    enc = OrdinalEncoder(handle_unknown='use_encoded_value', unknown_value=-1)
    C = pd.DataFrame(enc.fit_transform(df[CAT].astype(str)), columns=CAT, index=df.index)
    return pd.concat([X, C], axis=1)
X = make_X(d); y = d.log_price.values; price = d.price.values
ci = [X.columns.get_loc(c) for c in CAT]
groups = d.email_publisher_id.fillna(-1).astype(str)

def mk(): return HistGradientBoostingRegressor(max_iter=250, learning_rate=0.06, min_samples_leaf=15,
        l2_regularization=1.0, categorical_features=ci, random_state=0)

def report(name, pred):
    ok=~np.isnan(pred)
    print(f"{name:46s} n={ok.sum():4d} R2={r2_score(y[ok],pred[ok]):6.3f} MedAPE={np.median(np.abs(np.exp(pred[ok])-price[ok])/price[ok])*100:5.1f}%")

# ---- A. feature ablations (seller-grouped) ----
print("=== ABLATIONS (5-fold grouped by seller) ===")
def oof(cols_drop=()):
    Xi = X.drop(columns=list(cols_drop))
    cidx=[Xi.columns.get_loc(c) for c in CAT if c in Xi.columns]
    o=np.full(len(d),np.nan)
    for tr,te in GroupKFold(5).split(Xi,y,groups):
        m=HistGradientBoostingRegressor(max_iter=250,learning_rate=0.06,min_samples_leaf=15,
            l2_regularization=1.0,categorical_features=cidx,random_state=0)
        m.fit(Xi.iloc[tr],y[tr]); o[te]=m.predict(Xi.iloc[te])
    return o
full = oof(); report("full model", full)
report("  - view_count", oof(['view_count']))
report("  - all condition/text flags", oof(BOOL))
report("  - seller_ads & is_dealer", oof(['seller_ads','is_dealer']))
report("  - town", oof(['town_g']))
report("  ONLY specs (chip,year,screen,ram,ssd,family)",
       oof([c for c in X.columns if c not in ['chip_key','chip_variant','chip_brand','family','year','age','screen','ram_gb','ssd_gb','ram_log','storage_log']]))
np.save('mb/oof_full.npy', full)

# ---- B. simple median baseline (what P23 proposes) ----
print("\n=== P23-STYLE MEDIAN BASELINE vs ML (seller-grouped) ===")
d['cfg_full'] = d.family.astype(str)+'|'+d.chip_key+'|'+d.screen.astype(str)+'|'+d.ram_gb.astype(str)+'|'+d.ssd_gb.astype(str)
d['cfg_mid']  = d.family.astype(str)+'|'+d.chip_key+'|'+d.screen.astype(str)
d['cfg_lo']   = d.family.astype(str)+'|'+d.chip_key
for key, MIN in [('cfg_full',3),('cfg_mid',3),('cfg_lo',3)]:
    pred=np.full(len(d),np.nan)
    for tr,te in GroupKFold(5).split(X,y,groups):
        med = d.iloc[tr].groupby(key).log_price.agg(['median','size'])
        med = med[med['size']>=MIN]['median']
        pred[te] = d.iloc[te][key].map(med).values
    cov = (~np.isnan(pred)).mean()*100
    report(f"median by {key} (min {MIN}, cov {cov:.0f}%)", pred)

# ---- C. permutation importance on a held-out seller split ----
print("\n=== PERMUTATION IMPORTANCE (held-out sellers) ===")
tr,te = next(iter(GroupKFold(5).split(X,y,groups)))
m = mk(); m.fit(X.iloc[tr], y[tr])
pi = permutation_importance(m, X.iloc[te], y[te], n_repeats=8, random_state=0, scoring='r2')
imp = pd.Series(pi.importances_mean, index=X.columns).sort_values(ascending=False)
for k,v in imp.head(18).items(): print(f"   {k:16s} {v:7.4f}")
