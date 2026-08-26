"""Idea 3: hierarchical (partial-pooling) model.

Two prices per listing, which is the whole point:
  market_log   = what the SPEC is worth, seller-blind        -> "cheap vs market?"
  expected_log = market_log + shrunk seller effect           -> "cheap for THIS seller?"
The seller effect is estimated time-causally and shrunk toward zero by sample size,
so a seller with one prior ad contributes almost nothing and a 200-ad dealer nearly all.
"""
import numpy as np, pandas as pd, seller_base, harness as H
from sklearn.metrics import r2_score

d = seller_base.load()
X, ci = H.build_X(d)
y = d.log_price.values

# ---------- stage 1: seller-blind market price, expanding window ----------
base = np.load('mb/base_causal.npy')
d['market_log'] = base
scored = ~np.isnan(base)
print(f"scored rows: {scored.sum()} / {len(d)}")

# ---------- estimate variance components on the scored region ----------
r = pd.Series(y - base, index=d.index)[scored]
sell = d.seller[scored]
grp = r.groupby(sell)
n_s = grp.size()
within = grp.apply(lambda x: x.var(ddof=1) if len(x) > 1 else np.nan)
sigma2_within = np.nansum((n_s[within.notna()]-1)*within.dropna()) / max((n_s[within.notna()]-1).sum(), 1)
# between-seller variance of TRUE effects: var(observed means) - sigma2_within * mean(1/n)
means = grp.mean()
multi = n_s[n_s >= 2].index
sigma2_between = max(means[multi].var(ddof=1) - sigma2_within*np.mean(1/n_s[multi]), 1e-6)
KAPPA = sigma2_within / sigma2_between
print(f"\nsigma_within  = {np.sqrt(sigma2_within):.4f}  (noise of one listing around its seller's level)")
print(f"sigma_between = {np.sqrt(sigma2_between):.4f}  (spread of true seller price levels)")
print(f"=> kappa = {KAPPA:.2f}  : a seller needs ~{KAPPA:.0f} ads before half their apparent")
print(f"   discount is believed. shrinkage w = n/(n+{KAPPA:.1f})")
print("   " + "  ".join(f"n={n}:{n/(n+KAPPA):.2f}" for n in [1,2,3,5,10,25,50,200]))

# ---------- stage 2: time-causal shrunk seller effect ----------
def run(kappa, use_shrink=True):
    ssum, scnt = {}, {}
    eff = np.zeros(len(d)); pri = np.zeros(len(d))
    for i in range(len(d)):
        s = d.seller.iat[i]
        c = scnt.get(s, 0); tot = ssum.get(s, 0.0)
        pri[i] = c
        if c == 0: eff[i] = 0.0
        elif use_shrink: eff[i] = tot / (c + kappa)      # == mean * n/(n+kappa)
        else:           eff[i] = tot / c                  # raw mean, no pooling
        if scored[i]:                                     # only learn from scored rows
            ssum[s] = tot + (y[i] - base[i]); scnt[s] = c + 1
    return eff, pri

eff_shrunk, prior = run(KAPPA, True)
eff_raw, _        = run(KAPPA, False)
d['seller_effect'] = eff_shrunk
d['prior_seen'] = prior
d['expected_log'] = d.market_log + d.seller_effect

def rep(name, pred, mask=None):
    m = scored if mask is None else (scored & mask)
    if m.sum() < 15: return
    yy, pp, pr = y[m], pred[m], d.price.values[m]
    print(f"  {name:34s} n={m.sum():5d}  R2={r2_score(yy,pp):6.3f}  "
          f"MedAPE={np.median(np.abs(np.exp(pp)-pr)/pr)*100:5.1f}%  sd={np.std(yy-pp):.3f}")

print("\n=== DOES THE SELLER TERM HELP? (time-causal, no leakage) ===")
rep("market only (seller-blind)", base)
rep("+ RAW seller mean (no pooling)", base + eff_raw)
rep("+ SHRUNK seller effect", base + eff_shrunk)

print("\n=== BY HOW MUCH HISTORY THE SELLER HAD (the cold-start check) ===")
buckets = [(0,0,'0 prior ads (NEW seller)'),(1,2,'1-2 prior'),(3,9,'3-9 prior'),
           (10,49,'10-49 prior'),(50,10**6,'50+ prior')]
for lo,hi,lab in buckets:
    m = (prior>=lo)&(prior<=hi)
    print(f"\n {lab}")
    rep("   market only", base, m)
    rep("   + raw seller mean", base+eff_raw, m)
    rep("   + shrunk seller effect", base+eff_shrunk, m)
d.to_pickle('mb/p3.pkl')
