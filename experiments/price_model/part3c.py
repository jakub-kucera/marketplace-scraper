"""Idea 3, corrected: the NOISE prior must depend on seller maturity, not just the level.

Shrinking sigma toward one population value is wrong here: that value (0.125) is dominated
by high-volume dealers, whose pricing is formulaic. A first-time private seller is ~2.4x
noisier. Using the dealer sigma for them makes z<=-2 fire on 15% of their listings.
"""
import numpy as np, pandas as pd, seller_base
d=seller_base.load(); base=np.load('mb/base_causal.npy'); y=d.log_price.values
scored=~np.isnan(base); res=y-base
KAPPA=12.0; NU=8.0

# time-causal prior counts
pri=np.zeros(len(d)); acc={}
for i in range(len(d)):
    s=d.seller.iat[i]; pri[i]=acc.get(s,0)
    if scored[i]: acc[s]=acc.get(s,0)+1
d['prior_seen']=pri

print("=== RESIDUAL NOISE BY SELLER MATURITY (this is the prior we actually need) ===")
BK=[(0,0),(1,2),(3,9),(10,49),(50,10**6)]
sig_prior={}
for lo,hi in BK:
    m=scored&(pri>=lo)&(pri<=hi)
    sd=np.std(res[m]); sig_prior[(lo,hi)]=sd
    print(f"  prior_ads {lo:>2}-{hi if hi<1000 else '+':<3}: n={m.sum():5d}  residual sd={sd:.3f}")
print("  => a brand-new seller is ~%.1fx noisier than a 50+ ad dealer" %
      (sig_prior[(0,0)]/sig_prior[(50,10**6)]))

def prior_sigma(n):
    for (lo,hi),v in sig_prior.items():
        if lo<=n<=hi: return v
    return sig_prior[(0,0)]

# rebuild level + maturity-aware sigma
lvl=np.zeros(len(d)); sig=np.zeros(len(d)); acc2={}
for i in range(len(d)):
    s=d.seller.iat[i]; c,tot,sq=acc2.get(s,(0,0.0,0.0))
    lvl[i]= tot/(c+KAPPA) if c else 0.0
    sp=prior_sigma(c)
    if c>=2:
        m_=tot/c; var_s=max(sq/c-m_*m_,0.0)*c/(c-1)
        sig[i]=np.sqrt((c*var_s+NU*sp*sp)/(c+NU))
    else:
        sig[i]=sp
    if scored[i]:
        e=res[i]; acc2[s]=(c+1,tot+e,sq+e*e)
d['seller_level']=lvl; d['seller_sigma']=sig
d['market_log']=base
d['expected_log']=base+lvl
d['resid_mkt']=y-base
d['resid_own']=y-d.expected_log
d['z']=d.resid_own/d.seller_sigma
d.to_pickle('mb/p3c.pkl')

sc=d[scored].copy()
print("\n=== EVIDENCE STANDARD IS NOW COMPARABLE ACROSS SELLER TYPES ===")
print(f"{'tier':17s} {'median sigma':>13} {'z<=-2 means':>13} {'% of ads firing':>16}")
for t in ['private (1-2)','small (3-9)','medium (10-49)','large (50+)']:
    g=sc[sc.tier==t]
    print(f"{t:17s} {g.seller_sigma.median():13.3f} {(1-np.exp(-2*g.seller_sigma.median()))*100:12.0f}% {(g.z<=-2).mean()*100:15.1f}%")
print("  (a flat -25% rule fired on 10.4% of private ads and 1.2% of dealer ads —")
print("   the z rule equalises that, which is the point.)")

import re, mbfeat
DMG=re.compile(r'nefunk|praskl|prakl|rozbit|rozibt|ko lcd|poskozen|vadn|\bvada\b|na dily|nejde|nezapin|zatopen|polit|rozlit|nekompletni',re.I)
sc['txt']=(sc.name.fillna('')+' '+sc.short_description.fillna('')).map(mbfeat.strip_diacritics)
sc['damaged']=sc.txt.str.contains(DMG)
sc['spec_ok']=sc.year.notna()&(sc.chip_key!='unknown')&sc.ram_gb.notna()&sc.ssd_gb.notna()
gate=sc.spec_ok&~sc.damaged&(sc.price>5000)
days=(sc.created.max()-sc.created.min()).days
print(f"\n=== GATED ALERT RULES ({days} days, {len(sc)} scored ads) ===")
for lab,m in [("A  flat: >=25% below market",        gate&(sc.resid_mkt<np.log(.75))),
              ("B  z<=-2 vs own seller baseline",    gate&(sc.z<=-2)),
              ("C  z<=-2 AND >=10% below market",    gate&(sc.z<=-2)&(sc.resid_mkt<np.log(.90)))]:
    g=sc[m]
    tiers=" ".join(f"{t.split()[0]}={int((g.tier==t).sum())}" for t in ['private (1-2)','small (3-9)','medium (10-49)','large (50+)'])
    print(f"  {lab:36s} {len(g):3d} ads = {len(g)/days*7:4.1f}/wk | {tiers}")
    print(f"  {'':36s}     median discount vs market {np.median((1-np.exp(-g.resid_mkt))*100):.0f}%")
print("\n=== WHAT RULE C FIRES ON ===")
for _,r in sc[gate&(sc.z<=-2)&(sc.resid_mkt<np.log(.90))].nsmallest(12,'z').iterrows():
    print(f"  {int(r.price):>6} | mkt {int(np.exp(r.market_log)):>6} | this-seller {int(np.exp(r.expected_log)):>6} "
          f"| z={r.z:5.2f} | prior={int(r.prior_seen):3d} | {r['name'][:38]}")
