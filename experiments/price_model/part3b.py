"""Idea 3, completed: shrink the seller's NOISE as well as their LEVEL.

A flat -25% rule is ~1sd for a private seller and ~2.9sd for a dealer, so it is not a
comparable standard of evidence. The fix is a z-score against a per-seller sigma that is
itself shrunk toward the population value, so a 2-ad seller inherits population noise.
"""
import numpy as np, pandas as pd, seller_base, harness as H
from sklearn.metrics import r2_score

d = seller_base.load()
base = np.load('mb/base_causal.npy')
y = d.log_price.values
scored = ~np.isnan(base)
d['market_log'] = base
res_all = y - base

# variance components (same estimator as part3)
r = pd.Series(res_all, index=d.index)[scored]; sell = d.seller[scored]
grp = r.groupby(sell); n_s = grp.size()
within = grp.apply(lambda x: x.var(ddof=1) if len(x) > 1 else np.nan)
s2w = np.nansum((n_s[within.notna()]-1)*within.dropna())/max((n_s[within.notna()]-1).sum(),1)
means = grp.mean(); multi = n_s[n_s>=2].index
s2b = max(means[multi].var(ddof=1) - s2w*np.mean(1/n_s[multi]), 1e-6)
KAPPA_MOMENT = s2w/s2b
KAPPA = 12.0   # tuned empirically (ksweep.py); the moment estimator gives 0.53, ~20x too little shrinkage
SIGMA_POP = np.sqrt(s2w)
NU = 8.0          # pseudo-count for variance shrinkage: sigma_s trusts population until ~8 ads

# time-causal running level AND noise, both shrunk
n_pri = np.zeros(len(d)); lvl = np.zeros(len(d)); sig = np.full(len(d), SIGMA_POP)
acc = {}
for i in range(len(d)):
    s = d.seller.iat[i]
    c, tot, sq = acc.get(s, (0, 0.0, 0.0))
    n_pri[i] = c
    lvl[i] = tot/(c+KAPPA) if c else 0.0
    if c >= 2:
        m = tot/c
        var_s = max(sq/c - m*m, 0.0)*c/(c-1)
        sig[i] = np.sqrt((c*var_s + NU*s2w)/(c+NU))     # shrink variance toward population
    if scored[i]:
        e = res_all[i]; acc[s] = (c+1, tot+e, sq+e*e)

d['prior_seen']=n_pri; d['seller_level']=lvl; d['seller_sigma']=sig
d['expected_log']=d.market_log+d.seller_level
d['resid_mkt']=y-d.market_log                      # cheap vs MARKET
d['resid_own']=y-d.expected_log                    # cheap vs THIS SELLER
d['z']=d.resid_own/d.seller_sigma                  # evidence, comparable across sellers
d['disc_mkt']=(1-np.exp(-d.resid_mkt))*100
d.to_pickle('mb/p3b.pkl')

print(f"kappa={KAPPA:.1f} (moment est. was {KAPPA_MOMENT:.2f})  sigma_pop={SIGMA_POP:.3f}  nu={NU}")
print("\n=== HOW MUCH OF A SELLER'S APPARENT LEVEL IS BELIEVED? ===")
print("  prior ads:  " + "  ".join(f"{n:>4}" for n in [0,1,2,3,5,10,25,50,200]))
print("  weight   :  " + "  ".join(f"{n/(n+KAPPA):4.2f}" for n in [0,1,2,3,5,10,25,50,200]))

print("\n=== ALERT THRESHOLD IS NOW SELLER-AWARE ===")
sc = d[scored].copy()
print(f"{'tier':17s} {'median sigma_s':>15} {'z<=-2 means':>14} {'ads':>6} {'alerts':>7}")
for t in ['private (1-2)','small (3-9)','medium (10-49)','large (50+)']:
    g=sc[sc.tier==t]; ms=g.seller_sigma.median()
    print(f"{t:17s} {ms:15.3f} {(1-np.exp(-2*ms))*100:13.0f}% {len(g):6d} {(g.z<=-2).sum():7d}")

days=(sc.created.max()-sc.created.min()).days
print(f"\n=== COMPARING THE TWO ALERT RULES (over {days} days) ===")
import re, mbfeat
DMG=re.compile(r'nefunk|praskl|prakl|rozbit|rozibt|ko lcd|poskozen|vadn|\bvada\b|na dily|nejde|nezapin|zatopen|polit|rozlit|nekompletni',re.I)
sc['txt']=(sc.name.fillna('')+' '+sc.short_description.fillna('')).map(mbfeat.strip_diacritics)
sc['damaged']=sc.txt.str.contains(DMG)
sc['spec_ok']=sc.year.notna()&(sc.chip_key!='unknown')&sc.ram_gb.notna()&sc.ssd_gb.notna()
gate=sc.spec_ok&~sc.damaged&(sc.price>5000)
for lab,m in [("flat: >=25% below MARKET", gate&(sc.resid_mkt<np.log(.75))),
              ("z<=-2 vs OWN seller baseline", gate&(sc.z<=-2)),
              ("BOTH (cheap for them AND vs market)", gate&(sc.z<=-2)&(sc.resid_mkt<np.log(.85)))]:
    g=sc[m]
    print(f"  {lab:38s} {len(g):3d} ads = {len(g)/days*7:4.1f}/wk | "
          f"tiers: " + " ".join(f"{t.split()[0]}={int((g.tier==t).sum())}" for t in
          ['private (1-2)','small (3-9)','medium (10-49)','large (50+)']))
