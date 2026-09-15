import sys, warnings
sys.path.insert(0, "/Users/jakubkucera-sch/Documents/scraper/experiments/price_model/common")
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
B = "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/alert_audit/"
ip = pd.read_pickle(B + "ip.pkl")
CLS = {  # my independent classification, keyed by ad id
    24260: "bait/joke", 25341: "bait/price-anchor", 25086: "dealer low-end (e10771)",
    24069: "unsettleable (bare ad, 75% battery unparsed)", 24845: "bait/scam (sealed flagship at 52% of cheapest peer)",
    23742: "dealer low-end (e10682) / pre-11", 24800: "bait/price-anchor", 24230: "thin rung SE (comps disagree)",
    25483: "dealer under-market, relisted 3x", 23743: "DUPLICATE of 25483", 25076: "DUPLICATE of 25483",
    23713: "bait/scam suspected (unwanted-gift template, 0 comparables)", 23504: "thin rung AIR (comps disagree: -0.1%)",
    24228: "DEFECT gate-miss: 'funkcni az na Face ID'", 23937: "GENUINELY CHEAP candidate",
    24890: "DEFECT gate-BUG: 'zadni sklo je prasklé'", 23558: "thin rung AIR (comps disagree: -8.3%)",
    24563: "GENUINELY CHEAP candidate", 23980: "dealer low-end (e10771)", 23914: "dealer low-end (e2550) / pre-11",
    24757: "DEFECT gate-BUG: 'zadni sklo je prasklé'", 23474: "NO INFORMATION (desc == 'Apple')",
    24539: "thin rung MAX n=2 (comps disagree: -10.3%)", 23373: "DEFECT gate-miss: 'menen displej'",
    24793: "thin rung SE (comps disagree: -18.2%)",
}
ip["cls"] = ip.id.map(CLS)
g = ip[ip.gate].sort_values("resid").head(25).copy()
print("WHICH ROWS SURVIVE EACH THRESHOLD  (gated funnel, my classification)")
print("=" * 120)
print(f"{'rk':>3} {'id':>6} {'price':>7} {'disc%':>6} {'z':>6}  {'-25%':>5} {'-40%':>5} {'z<=-2.5':>8} {'z<=-3':>6}  class")
for i, (_, r) in enumerate(g.iterrows(), 1):
    print(f"{i:3d} {r.id:6d} {int(r.price):7,d} {100*r.disc:6.1f} {r.z:+6.2f}  "
          f"{'Y' if r.resid<=np.log(.75) else '.':>5} {'Y' if r.resid<=np.log(.60) else '.':>5} "
          f"{'Y' if r.z<=-2.5 else '.':>8} {'Y' if r.z<=-3.0 else '.':>6}  {r.cls}")

print("\n" + "=" * 120)
print("COMPOSITION BY THRESHOLD")
print("=" * 120)
BUCKET = lambda c: ("bait/scam" if c.startswith("bait") else
                    "duplicate" if c.startswith("DUPLICATE") else
                    "defect (gate miss/bug)" if c.startswith("DEFECT") else
                    "thin-rung over-prediction" if c.startswith("thin") else
                    "dealer low-end price level" if c.startswith("dealer") else
                    "genuinely cheap candidate" if c.startswith("GENUINELY") else
                    "no information / unsettleable")
g["bucket"] = g.cls.map(BUCKET)
for lab, m in [("-25% gated (25)", g.resid <= np.log(.75)), ("-30% gated", g.resid <= np.log(.70)),
               ("-40% gated", g.resid <= np.log(.60)), ("z<=-2.5 gated", g.z <= -2.5), ("z<=-3.0 gated", g.z <= -3.0)]:
    sub = g[m]
    vc = sub.bucket.value_counts()
    print(f"\n  {lab}: n={len(sub)}")
    for k, v in vc.items():
        print(f"      {v:2d}  {k}")
    print(f"      -> genuinely cheap candidates: {int((sub.bucket=='genuinely cheap candidate').sum())}/{len(sub)}")
    if len(sub):
        print(f"      -> ids: {list(sub.id)}")
g.to_csv(B + "top25_classified.csv", index=False)
