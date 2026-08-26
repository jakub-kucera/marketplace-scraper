"""Spec-matched cross-marketplace price comparison + marketplace fixed effect."""
import pandas as pd, numpy as np
pd.set_option('display.width', 250)
d = pd.read_pickle('xm/pool.pkl')

# is the 3-month Bazos corpus comparable to the 3-day slice? (justifies using all of it)
b = d[d.marketplace=='bazos'].copy()
b['wk'] = b.created.dt.isocalendar().week.astype(int)
bw = b[(b.ask>=10000)&(b.ask<=100000)].groupby('wk').ask.agg(n='size', med='median')
print("--- Bazos median ask by ISO week, 10k-100k band (drift check) ---")
print(bw[bw.n>=25].to_string(), "\n")

s = d[d.spec_ok].copy()
cells = s.groupby('spec').marketplace.nunique()
shared = cells[cells>=2].index
m = s[s.spec.isin(shared)]
print(f"spec cells shared by >=2 marketplaces: {len(shared)}  (rows {len(m)})")

piv = m.pivot_table(index='spec', columns='marketplace', values='ask', aggfunc=['median','size'])
piv.columns = ['_'.join(c) for c in piv.columns]
for mk in ['bazos','sbazar','vinted']:
    for pre in ['median','size']:
        if f'{pre}_{mk}' not in piv.columns:
            piv[f'{pre}_{mk}'] = np.nan
piv = piv[[f'{p}_{mk}' for mk in ['bazos','sbazar','vinted'] for p in ['median','size']]]
piv['sbz_vs_baz'] = piv.median_sbazar/piv.median_bazos - 1
piv['vin_vs_baz'] = piv.median_vinted/piv.median_bazos - 1
print("\n--- per-config medians (CZK ask) ---")
print(piv.round(3).to_string())

for col, lab, need in [('sbz_vs_baz','Sbazar vs Bazos',['median_bazos','median_sbazar']),
                       ('vin_vs_baz','Vinted vs Bazos',['median_bazos','median_vinted'])]:
    sub = piv.dropna(subset=need)
    if len(sub)==0: continue
    lr = np.log1p(sub[col])
    n = len(sub); mu = lr.mean(); se = lr.std(ddof=1)/np.sqrt(n)
    print(f"\n{lab}: n_cells={n}  median delta={sub[col].median():+.1%}  "
          f"mean log delta={np.expm1(mu):+.1%}  95% CI [{np.expm1(mu-1.96*se):+.1%}, {np.expm1(mu+1.96*se):+.1%}]")
    # weighted by min cell size
    w = np.minimum(sub[need[0].replace('median','size')], sub[need[1].replace('median','size')])
    print(f"   size-weighted mean log delta = {np.expm1((lr*w).sum()/w.sum()):+.1%}  (total matched pairs {int(w.sum())})")
