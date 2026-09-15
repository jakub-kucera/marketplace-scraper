import sys, warnings
sys.path.insert(0, "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2")
sys.path.insert(0, "/Users/jakubkucera-sch/Documents/scraper/experiments/price_model/common")
import numpy as np, pandas as pd, lib, ph
warnings.filterwarnings("ignore")
B = "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2/"
ip = pd.read_pickle(B+"ip2.pkl")
oofR = np.load(B+"oofA_ip.npy"); oofC = np.load(B+"oofCfg_ip.npy")
m = ~np.isnan(oofC)
print("=== HEAD-TO-HEAD on the rows BOTH can score (config-median k>=3 coverage)")
for tag, o in [("ridge FULL", oofR), ("config median", oofC)]:
    r = lib.M(ip, o, m); print(f"  {tag:16s} n={r['n']} R2={r['r2']:+.3f} MedAPE={r['medape']:.2f}% sigma={r['sigma']:.3f}")
sub = ip[m].reset_index(drop=True)
d = ph.cluster_bootstrap_delta(sub, oofR[m], oofC[m], n=2000)
print(f"  ridge - median: dR2 {d['dr2'][0]:+.4f} [{d['dr2'][1]:+.4f},{d['dr2'][2]:+.4f}]  "
      f"dMedAPE {d['dmedape'][0]:+.2f}pp [{d['dmedape'][1]:+.2f},{d['dmedape'][2]:+.2f}] reps={d['reps']}")
print("\n=== on the rows ONLY the ridge can score (config median has <3 comparables)")
r = lib.M(ip, oofR, ~m); print(f"  ridge n={r['n']} R2={r['r2']:+.3f} MedAPE={r['medape']:.2f}% sigma={r['sigma']:.3f}")
print("  what they are:", ip[~m].storage_gb.isna().sum(), "no-storage,",
      int((~m).sum())-int(ip[~m].storage_gb.isna().sum()), "rare config")
print("  their gen/tier mix:", ip[~m].gen_tier.value_counts().head(8).to_dict())

print("\n=== HYBRID: config median where k>=3, ridge otherwise")
hyb = np.where(m, oofC, oofR)
r = lib.M(ip, hyb); print(f"  hybrid  n={r['n']} R2={r['r2']:+.3f} MedAPE={r['medape']:.2f}% sigma={r['sigma']:.3f}")
r = lib.M(ip, oofR); print(f"  ridge   n={r['n']} R2={r['r2']:+.3f} MedAPE={r['medape']:.2f}% sigma={r['sigma']:.3f}")
d = ph.cluster_bootstrap_delta(ip, hyb, oofR, n=2000)
print(f"  hybrid - ridge: dR2 {d['dr2'][0]:+.4f} [{d['dr2'][1]:+.4f},{d['dr2'][2]:+.4f}]  "
      f"dMedAPE {d['dmedape'][0]:+.2f}pp [{d['dmedape'][1]:+.2f},{d['dmedape'][2]:+.2f}]")

print("\n=== how repetitive is the config space? (this is what makes the median work)")
cfg = ip.gen_tier.astype(str)+" "+ip.storage_gb.astype("Int64").astype(str)
vc = cfg.value_counts()
print(f"  {len(vc)} distinct gen x tier x storage configs over {len(ip)} ads; "
      f"median ads/config {vc.median():.0f}; top config {vc.index[0]} n={vc.iloc[0]}")
print(f"  share of ads in a config with >=3 others in corpus: {100*(cfg.map(vc)>=4).mean():.1f}%")
print("  top 12:", vc.head(12).to_dict())
# same statistic for MacBook comparison basis
print(f"  rows in configs seen >=3 times: {100*(cfg.map(vc)>=3).mean():.1f}%")
