import pandas as pd, numpy as np
ds=pd.read_pickle('mb/scored.pkl'); s=ds[ds.pred_log.notna()].copy().reset_index(drop=True)

print("=== INTERVAL CALIBRATION ===")
cov=((s.log_price>=s.lo)&(s.log_price<=s.hi)).mean()*100
print(f"raw quantile 10-90 model:      {cov:5.1f}% coverage (nominal 80%)  -> TOO NARROW")

# split-conformal: first half calibrates the absolute residual quantile, applied to second half
half=len(s)//2
cal=s.iloc[:half]; test=s.iloc[half:]
for alpha,nom in [(0.20,80),(0.10,90),(0.05,95)]:
    q=np.quantile(np.abs(cal.resid), 1-alpha)
    c=((test.log_price>=test.pred_log-q)&(test.log_price<=test.pred_log+q)).mean()*100
    w=np.median(np.exp(test.pred_log+q)-np.exp(test.pred_log-q))
    print(f"split-conformal +-{q:.3f} log:   {c:5.1f}% coverage (nominal {nom}%)  median width {w:6.0f} Kc "
          f"({np.median((np.exp(test.pred_log+q)-np.exp(test.pred_log-q))/test.pred)*100:3.0f}% of price)")

# conformal is symmetric; a one-sided lower bound is what a deal alert actually needs
print("\n=== ONE-SIDED 'IS IT BELOW MARKET' TEST (what an alert needs) ===")
for alpha in [0.10,0.05,0.02,0.01]:
    q=np.quantile(cal.resid, alpha)             # lower alpha-quantile of residual
    fired=(test.resid<q); rate=fired.mean()*100
    print(f"  alpha={alpha:.2f}: threshold resid<{q:+.3f} (= price < {(1-np.exp(q))*100:.0f}% below predicted) "
          f"-> fires on {fired.sum():3d}/{len(test)} ads ({rate:4.1f}%), ~{fired.sum()/((test.created.max()-test.created.min()).days or 1)*7:.1f}/week")

print("\n=== ACCURACY BY SEGMENT (where can you trust the model?) ===")
s['seg']=np.where(s.chip_brand=='apple','Apple silicon',np.where(s.chip_brand=='intel','Intel','unknown chip'))
for seg,gg in s.groupby('seg'):
    print(f"  {seg:14s} n={len(gg):4d}  MedAPE={np.median(np.abs(gg.pred-gg.price)/gg.price)*100:5.1f}%  resid sd={gg.resid.std():.3f}")
s['spec_complete']=(s.year.notna())&(s.chip_key!='unknown')&(s.ram_gb.notna())&(s.ssd_gb.notna())
for c,gg in s.groupby('spec_complete'):
    print(f"  spec_complete={str(c):5s} n={len(gg):4d}  MedAPE={np.median(np.abs(gg.pred-gg.price)/gg.price)*100:5.1f}%  resid sd={gg.resid.std():.3f}")
print("\n  => gating alerts on complete specs is the single cheapest precision win")
