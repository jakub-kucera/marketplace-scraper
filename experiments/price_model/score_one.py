import numpy as np, pandas as pd, mbfeat, harness as H, seller_base
from sklearn.ensemble import HistGradientBoostingRegressor

d = seller_base.load()
AD = dict(
 name='MacBook Pro 14" M3 Max 36GB/1TB jako nový',
 desc=('MacBook Pro 14" M3 Max 36GB/1TB Stav jako nový. Pouze 8x nabijeno. Zaruka do 7. 7. 2027. '
       'Zarizeni pochazi z Nemecka a ma nemecke rozlozeni klavesnice (German layout). '
       'Prodavam pouze osobne v Praze 4. Garantuji legalni puvod i to, ze nema zadne skryte vady. '
       'Nakupujete u overeneho prodejce s kamennym zazemim. Mam pripravenou take kupni smlouvu.'),
 price=45000, location='Praha 4, 142 00', view_count=12, created=pd.Timestamp('2026-08-25', tz='UTC'))

f = mbfeat.extract(AD['name'], AD['desc'])
print("=== EXTRACTED ===")
for k,v in f.items():
    if v not in (False,None): print(f"  {k:14s} {v}")

# build a one-row frame matching the training columns
row = {c: np.nan for c in d.columns}
row.update(f)
row.update(dict(price=AD['price'], log_price=np.log(AD['price']), location=AD['location'],
                view_count=AD['view_count'], created=AD['created'], name=AD['name'],
                short_description=AD['desc'], seller='e2618'))
row['chip_key'] = 'apple%d_%s' % (f['chip_gen'], f['chip_variant'])
row['age'] = 2026 - f['year'] if f['year'] else np.nan
row['ram_log'] = np.log(f['ram_gb']); row['storage_log'] = np.log(f['ssd_gb'])
row['dow'] = AD['created'].dayofweek
row['town_g'] = 'Praha 4' if 'Praha 4' in set(d.town_g) else 'other'
row['family'] = f['family']; row['chip_brand'] = f['chip_brand']; row['chip_variant'] = f['chip_variant']
new = pd.DataFrame([row])

both = pd.concat([d, new], ignore_index=True)
X, ci = H.build_X(both)
Xtr, Xte = X.iloc[:len(d)], X.iloc[len(d):]
m = HistGradientBoostingRegressor(max_iter=250, learning_rate=0.06, min_samples_leaf=15,
        l2_regularization=1.0, categorical_features=ci, random_state=0)
m.fit(Xtr, d.log_price.values)
mkt = float(np.exp(m.predict(Xte)[0]))

print(f"\n=== MODEL ===")
print(f"  asking price          {AD['price']:>8,} Kc".replace(',',' '))
print(f"  model market price    {mkt:>8,.0f} Kc".replace(',',' '))
print(f"  vs market             {(AD['price']/mkt-1)*100:>+8.1f}%")

# exact-config comparables
cmp_ = d[(d.chip_key=='apple3_max')&(d.screen==14.0)&(d.ram_gb==36)&(d.ssd_gb==1000)]
print(f"\n=== EXACT-CONFIG COMPARABLES (14\" M3 Max 36/1TB), n={len(cmp_)} ===")
for _,r in cmp_.iterrows(): print(f"    {int(r.price):>6} Kc  {r['name'][:56]}")
if len(cmp_):
    med=cmp_.price.median()
    print(f"  median {med:,.0f} Kc  -> this ad is {(AD['price']/med-1)*100:+.1f}%".replace(',',' '))

# seller effect
sel = d[d.seller=='e2618']
Xs = X.iloc[:len(d)][d.seller.values=='e2618']
res_s = d[d.seller=='e2618'].log_price.values - m.predict(Xs)
KAPPA=12.0; n=len(sel)
raw=res_s.mean(); shrunk=res_s.sum()/(n+KAPPA)
print(f"\n=== SELLER e2618 (7 prior ads) ===")
print(f"  raw mean residual     {(np.exp(raw)-1)*100:+.1f}%   (n={n})")
print(f"  shrinkage weight      {n/(n+KAPPA):.2f}")
print(f"  shrunk seller effect  {(np.exp(shrunk)-1)*100:+.1f}%")
print(f"  expected for THIS seller {mkt*np.exp(shrunk):,.0f} Kc".replace(',',' '))
sigma_prior = 0.172   # prior_ads 3-9 bucket, from part3c
z = (np.log(AD['price']) - (np.log(mkt)+shrunk))/sigma_prior
print(f"  z vs own baseline     {z:+.2f}  (alert fires at <= -2.0)")
print(f"\n  per-ad residuals of their prior listings (all M5 -> chip unknown):")
for (_,r),e in zip(sel.iterrows(), res_s):
    print(f"    {int(r.price):>6} vs {np.exp(np.log(r.price)-e):>8,.0f} pred  ({(np.exp(e)-1)*100:+6.1f}%)  {r['name'][:44]}".replace(',',' '))
