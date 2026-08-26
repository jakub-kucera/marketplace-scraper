import numpy as np, pandas as pd, seller_base
from sklearn.metrics import r2_score
d=seller_base.load(); base=np.load('mb/base_causal.npy'); y=d.log_price.values
scored=~np.isnan(base); res=y-base

def run(kappa):
    acc={}; eff=np.zeros(len(d)); pri=np.zeros(len(d))
    for i in range(len(d)):
        s=d.seller.iat[i]; c,tot=acc.get(s,(0,0.0)); pri[i]=c
        eff[i]= tot/(c+kappa) if c else 0.0
        if scored[i]: acc[s]=(c+1,tot+res[i])
    return eff,pri

_,pri = run(1.0)
buckets={'1-2':(pri>=1)&(pri<=2),'3-9':(pri>=3)&(pri<=9),
         '10+':(pri>=10),'all known':(pri>=1)}
print("=== KAPPA SWEEP (time-causal; kappa = pseudo-ads of population prior) ===")
print(f"{'kappa':>6} {'w@n=1':>6} {'w@n=5':>6} {'w@n=50':>7} | " +
      " | ".join(f"{k:>14}" for k in buckets) + " | overall")
best=None
for k in [0.5,1,2,3,5,8,12,20,35,60,1e6]:
    eff,_=run(k); p=base+eff
    cells=[]
    for name,m in buckets.items():
        mm=scored&m
        cells.append(f"{np.median(np.abs(np.exp(p[mm])-d.price.values[mm])/d.price.values[mm])*100:5.2f}%/{r2_score(y[mm],p[mm]):5.3f}")
    ov=np.median(np.abs(np.exp(p[scored])-d.price.values[scored])/d.price.values[scored])*100
    tag='  (no pooling→ +raw mean)' if k==0.5 else ('  (full pooling → seller term off)' if k>1e5 else '')
    print(f"{k:6.1f} {1/(1+k):6.2f} {5/(5+k):6.2f} {50/(50+k):7.2f} | " + " | ".join(cells) + f" | {ov:5.2f}%{tag}")
