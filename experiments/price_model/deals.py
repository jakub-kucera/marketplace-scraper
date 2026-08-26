import pandas as pd, numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.preprocessing import OrdinalEncoder
from sklearn.metrics import r2_score

d = pd.read_pickle('mb/ds.pkl').reset_index(drop=True)
d['created']=pd.to_datetime(d.created,utc=True)
CAT=['family','chip_key','chip_variant','town_g','chip_brand']
NUM=['year','age','screen','ram_gb','ssd_gb','ram_log','storage_log','seller_ads','dow','days','battery_pct','cycles','view_count']
BOOL=['warranty','new','defect','battery_new','vat_dph','cz_kbd','us_kbd','touchbar','retina','top_word','scratches','urgent','box','swap','is_dealer']
X=d[NUM].astype(float).copy()
for c in BOOL: X[c]=d[c].astype(float)
enc=OrdinalEncoder(handle_unknown='use_encoded_value',unknown_value=-1)
X=pd.concat([X,pd.DataFrame(enc.fit_transform(d[CAT].astype(str)),columns=CAT)],axis=1)
ci=[X.columns.get_loc(c) for c in CAT]; y=d.log_price.values

def mkq(q=None):
    kw=dict(max_iter=250,learning_rate=0.06,min_samples_leaf=15,l2_regularization=1.0,
            categorical_features=ci,random_state=0)
    if q is None: return HistGradientBoostingRegressor(**kw)
    return HistGradientBoostingRegressor(loss='quantile',quantile=q,**kw)

# --- PRODUCTION SIMULATION: expanding window, retrain weekly, score only unseen future ads ---
order=np.argsort(d.created.values); ds=d.iloc[order].reset_index(drop=True); Xs=X.iloc[order].reset_index(drop=True); ys=y[order]
n=len(ds); start=int(n*0.4)
pred=np.full(n,np.nan); lo=np.full(n,np.nan); hi=np.full(n,np.nan)
step=100
for s in range(start,n,step):
    e=min(s+step,n)
    m=mkq(); m.fit(Xs.iloc[:s],ys[:s]); pred[s:e]=m.predict(Xs.iloc[s:e])
    ml=mkq(0.1); ml.fit(Xs.iloc[:s],ys[:s]); lo[s:e]=ml.predict(Xs.iloc[s:e])
    mh=mkq(0.9); mh.fit(Xs.iloc[:s],ys[:s]); hi[s:e]=mh.predict(Xs.iloc[s:e])
ok=~np.isnan(pred)
ds['pred_log']=pred; ds['lo']=lo; ds['hi']=hi
ds['pred']=np.exp(pred); ds['resid']=ds.log_price-ds.pred_log
ds['disc_pct']=(1-ds.price/ds.pred)*100
print(f"=== PRODUCTION SIM (expanding window, retrain every {step} ads, scored n={ok.sum()}) ===")
print(f"R2={r2_score(ys[ok],pred[ok]):.3f}  MedAPE={np.median(np.abs(np.exp(pred[ok])-ds.price[ok])/ds.price[ok])*100:.1f}%")
cov=((ys[ok]>=lo[ok])&(ys[ok]<=hi[ok])).mean()*100
print(f"80% interval empirical coverage: {cov:.1f}%   (nominal 80%)")
print(f"median interval width: {np.median(np.exp(hi[ok])-np.exp(lo[ok])):.0f} Kc "
      f"({np.median((np.exp(hi[ok])-np.exp(lo[ok]))/ds.pred[ok])*100:.0f}% of predicted price)")
ds.to_pickle('mb/scored.pkl')

print("\n=== RESIDUAL DISTRIBUTION ===")
print(ds.resid[ok].describe().round(3))
for p in [1,5,10,25,50,75,90]:
    print(f"  p{p:02d} discount = {np.percentile(ds.disc_pct[ok],p):6.1f}%")

print("\n=== TOP 25 'UNDERPRICED' BY RESIDUAL (what an alert would fire on) ===")
t=ds[ok].nsmallest(25,'resid')
for _,r in t.iterrows():
    print(f"  {int(r.price):>6} vs pred {int(r.pred):>6} ({r.disc_pct:5.1f}% off) | {r['name'][:56]}")
    print(f"         {r.family} {r.chip_key} y={r.year} {r.screen}\" ram={r.ram_gb} ssd={r.ssd_gb} def={r.defect} new={r['new']} views={r.view_count}")
