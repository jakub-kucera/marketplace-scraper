import os; os.environ.setdefault("OMP_NUM_THREADS","4")
import pandas as pd, numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import GroupKFold
from sklearn.metrics import r2_score, mean_absolute_error

d = pd.read_pickle('xm/pool.pkl').reset_index(drop=True)
d['age']=2026-d.year; d['ram_log']=np.log(d.ram_gb.astype(float)); d['ssd_log']=np.log(d.ssd_gb.astype(float))
CATS=['family','chip_key']; NUM=['age','ram_log','ssd_log','screen']
BOOL=['warranty','new','defect','battery_new','vat_dph','touchbar','retina','top_word','scratches','box','battery_pct','cycles']
def design(df, with_mk):
    X=pd.DataFrame(index=df.index)
    for c in CATS: X[c]=df[c].astype('category')
    for c in NUM+BOOL: X[c]=df[c].astype(float)
    if with_mk: X['marketplace']=df.marketplace.astype('category')
    return X
def mk(): return HistGradientBoostingRegressor(max_iter=250, learning_rate=0.08, max_depth=5,
        min_samples_leaf=15, l2_regularization=1.0, categorical_features='from_dtype', random_state=0)
def clean(X):  # drop all-NaN / single-valued columns a tiny subset can produce
    keep=[c for c in X.columns if X[c].notna().any() and X[c].nunique(dropna=True)>1]
    return X[keep]
y=np.log(d.ask.values); d['grp']=d.marketplace+'|'+d.name.str.lower().str.strip()
b=d[d.marketplace=='bazos']; Xb_full=design(b,True); yb=y[b.index]

for m in ['sbazar','vinted']:
    s=d[d.marketplace==m]; ys=y[s.index]; g=s.grp.values
    Xs=clean(design(s,False))
    own=np.full(len(s),np.nan); aug=np.full(len(s),np.nan)
    for tr,te in GroupKFold(n_splits=5).split(s,ys,g):
        own[te]=mk().fit(Xs.iloc[tr],ys[tr]).predict(Xs.iloc[te])
        tr_df=pd.concat([s.iloc[tr],b]); ytr=np.concatenate([ys[tr],yb])
        Xtr=clean(design(tr_df,True)); cols=Xtr.columns
        aug[te]=mk().fit(Xtr,ytr).predict(design(s.iloc[te],True)[cols])
    print(f"[D] {m:<7} n={len(s):<4} own-only R2={r2_score(ys,own):.3f} MAE={mean_absolute_error(ys,own):.3f}"
          f"   |  +Bazos+mk-effect R2={r2_score(ys,aug):.3f} MAE={mean_absolute_error(ys,aug):.3f}")

sp=d[d.spec_ok].copy(); cell=sp.groupby('spec').marketplace.nunique(); sp=sp[sp.spec.isin(cell[cell>=2].index)]
sp['res']=np.log(sp.ask)-sp.groupby('spec').ask.transform(lambda x: np.log(x).mean())
t=sp.groupby('marketplace').res.agg(n='size',mean='mean',sem='sem')
t['effect']=np.expm1(t['mean']); t['lo']=np.expm1(t['mean']-1.96*t.sem); t['hi']=np.expm1(t['mean']+1.96*t.sem)
print("\n[E] within-spec-cell log-price effect (cells shared by >=2 marketplaces, ref = cell mean):")
print(t[['n','effect','lo','hi']].round(3).to_string())
print("\n   spec cells used:", sp.spec.nunique())
