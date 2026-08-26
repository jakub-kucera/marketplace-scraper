import numpy as np, pandas as pd, seller_base, harness as H
d = seller_base.load()
X, ci = H.build_X(d)
small = (d.tier.isin(['private (1-2)','small (3-9)'])).values   # the "opportunity" market
large = (d.tier == 'large (50+)').values

print("=== IDEA 1: does restricting to small sellers help? ===\n")
p_all   = H.replay(d, X, ci)                       # train on everything
p_small = H.replay(d, X, ci, train_mask=small)     # train only on small sellers
p_large = H.replay(d, X, ci, train_mask=large)     # train only on dealers

rows = [
 H.score(d, p_all,   small, "train ALL      → score small sellers"),
 H.score(d, p_small, small, "train SMALL    → score small sellers"),
 H.score(d, p_large, small, "train DEALERS  → score small sellers"),
 None,
 H.score(d, p_all,   large, "train ALL      → score dealers"),
 H.score(d, p_large, large, "train DEALERS  → score dealers"),
 H.score(d, p_small, large, "train SMALL    → score dealers"),
]
H.show([r for r in rows if r])

print("\n=== predictability by tier (train on ALL) ===")
H.show([H.score(d, p_all, (d.tier==t).values, f"  {t}") for t in
        ['private (1-2)','small (3-9)','medium (10-49)','large (50+)']])

print("\n=== where do the gated alerts come from? ===")
d['pred'] = np.exp(p_all); d['resid'] = d.log_price - p_all
d['spec_ok'] = d.year.notna()&(d.chip_key!='unknown')&d.ram_gb.notna()&d.ssd_gb.notna()
import re, mbfeat
DMG=re.compile(r'nefunk|praskl|prakl|rozbit|rozibt|ko lcd|poskozen|vadn|\bvada\b|na dily|nejde|nezapin|zatopen|polit|rozlit|nekompletni',re.I)
d['txt']=(d.name.fillna('')+' '+d.short_description.fillna('')).map(mbfeat.strip_diacritics)
d['damaged']=d.txt.str.contains(DMG)
g = d[d.resid.notna() & d.spec_ok & ~d.damaged & (d.price>5000) & (d.resid < np.log(0.75))]
days=(d[d.resid.notna()].created.max()-d[d.resid.notna()].created.min()).days
print(f"  {len(g)} gated alerts over {days} days")
tt = g.groupby('tier', observed=True).size()
base = d[d.resid.notna()].groupby('tier', observed=True).size()
for t in base.index:
    k=tt.get(t,0)
    print(f"    {t:16s} {k:3d} alerts ({k/days*7:4.1f}/wk)  from {base[t]:4d} scored ads = {k/base[t]*100:4.1f}% hit rate")
d.to_pickle('mb/p1.pkl')
