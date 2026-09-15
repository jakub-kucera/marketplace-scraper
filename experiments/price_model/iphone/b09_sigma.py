import sys, warnings
sys.path.insert(0, "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2")
sys.path.insert(0, "/Users/jakubkucera-sch/Documents/scraper/experiments/price_model/common")
import numpy as np, pandas as pd, lib
warnings.filterwarnings("ignore")
B = "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2/"
ip = pd.read_pickle(B+"ip2.pkl"); oof = np.load(B+"oofA_ip.npy")
ip["resid"] = ip.log_price - oof

# proxy for production `seller_prior_ads`: count of the email publisher across ALL queries in
# the 11-query pull (2025-12-13 .. 2026-09-12). Still an UNDERCOUNT -- the real COUNT is over
# the whole Ad table, all queries ever scraped.
a = pd.read_csv("/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/data/ads.csv")
cnt = a.dropna(subset=["email_publisher_id"]).groupby("email_publisher_id").size()
ip["prod_prior"] = ip.email_publisher_id.map(cnt).fillna(0).astype(int)
ip.loc[ip.email_publisher_id.isna(), "prod_prior"] = 0
ip["prod_prior"] = (ip.prod_prior - 1).clip(lower=0)   # exclude self
print("=== identity coverage")
print("  rows with an email publisher id: %.1f%%; phone id: %.1f%%; either: %.1f%%"
      % (100*ip.email_publisher_id.notna().mean(), 100*ip.phone_publisher_id.notna().mean(),
         100*(ip.email_publisher_id.notna()|ip.phone_publisher_id.notna()).mean()))
print("  prod_prior distribution:", ip.prod_prior.describe()[["mean","50%","max"]].round(1).to_dict())

def tab(key, label, bins, labels):
    print(f"\n=== residual sigma by {label}")
    b = pd.cut(ip[key], bins, labels=labels)
    for lab, sub in ip.groupby(b, observed=True):
        print(f"  {label}={str(lab):16s} n={len(sub):4d} sellers={sub.seller.nunique():3d} "
              f"sigma={np.std(sub.resid):.3f} MedAPE={100*np.median(np.abs(np.exp(oof[sub.index])-sub.price)/sub.price):5.2f}%"
              f"  -25% = {abs(np.log(0.75))/max(np.std(sub.resid),1e-6):.2f}s")

tab("prod_prior", "seller ads in the 11-query pull (production proxy)",
    [-1,0,2,9,49,10**7], ["0","1-2","3-9","10-49","50+"])
ip["win_prior"] = ip.sort_values("created").groupby("seller").cumcount().reindex(ip.index)
tab("win_prior", "prior ads inside the 3.3-day window", [-1,0,2,9,10**7], ["0","1-2","3-9","10+"])
vc = ip.seller.value_counts(); ip["stot"] = ip.seller.map(vc)
tab("stot", "seller total ads in the 3.3-day window", [0,1,2,4,9,10**7], ["1","2","3-4","5-9","10+"])

print("\n=== residual sigma by SPEC COMPLETENESS (the alternative sigma key)")
for lab, m in [("gen+tier+storage+battery", ip.storage_gb.notna()&ip.battery_pct.notna()),
               ("gen+tier+storage, no battery", ip.storage_gb.notna()&ip.battery_pct.isna()),
               ("no storage", ip.storage_gb.isna())]:
    s = np.std(ip.resid[m]); print(f"  {lab:30s} n={int(m.sum()):4d} sigma={s:.3f}  -25% = {abs(np.log(0.75))/s:.2f}s")

print("\n=== how much of residual variance is BETWEEN sellers?")
gm = ip.groupby("seller").resid.transform("mean")
print(f"  between-seller share = {np.var(gm)/np.var(ip.resid):.3f} (MacBook: 0.75 for ridge)")
print(f"  sellers with >=2 ads: {(vc>=2).sum()} of {len(vc)} ({100*(vc>=2).mean():.1f}%), "
      f"covering {100*ip.stot.ge(2).mean():.1f}% of ads")
print(f"  one-off share of sellers {100*(vc==1).mean():.1f}%, of ads {100*ip.stot.eq(1).mean():.1f}%")
print(f"  top-10 sellers hold {100*vc.head(10).sum()/len(ip):.1f}% of ads")

print("\n=== what a flat -25% means per sigma source")
for lab, s in [("global (all iPhone rows)", np.std(ip.resid)),
               ("complete-spec", np.std(ip.resid[ip.storage_gb.notna()]))]:
    print(f"  {lab:26s} sigma={s:.3f} -> -25% is {abs(np.log(0.75))/s:.2f} sigma")
