import sys, warnings, pickle
sys.path.insert(0, "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2")
sys.path.insert(0, "/Users/jakubkucera-sch/Documents/scraper/experiments/price_model/common")
import numpy as np, pandas as pd, lib, ph
warnings.filterwarnings("ignore")
B = "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2/"
ip = pd.read_pickle(B+"ip2.pkl")
oofR = np.load(B+"oofA_ip.npy"); oofH = np.load(B+"oofH_ip.npy"); oofC = np.load(B+"oofCfg_ip.npy")

def show(tag, a, b, n=2000):
    d = ph.cluster_bootstrap_delta(ip, a, b, n=n)
    print(f"{tag:46s} dR2 {d['dr2'][0]:+.4f} [{d['dr2'][1]:+.4f},{d['dr2'][2]:+.4f}]  "
          f"dMedAPE {d['dmedape'][0]:+.2f}pp [{d['dmedape'][1]:+.2f},{d['dmedape'][2]:+.2f}]  reps={d['reps']}")
print("Paired seller-cluster bootstrap, 2000 replicates, 365 sellers / 639 iPhone rows\n")
show("HGB  - ridge (all rows)", oofH, oofR)
# config-median comparison must be on the rows the median can score
m = ~np.isnan(oofC)
sub = ip[m].reset_index(drop=True)
show(f"ridge - config-median (on its {int(m.sum())} covered rows)", oofR[m], oofC[m]) if False else None
d = ph.cluster_bootstrap_delta(sub, oofR[m], oofC[m], n=2000)
print(f"{'ridge - config-median (covered rows only)':46s} dR2 {d['dr2'][0]:+.4f} [{d['dr2'][1]:+.4f},{d['dr2'][2]:+.4f}]  "
      f"dMedAPE {d['dmedape'][0]:+.2f}pp [{d['dmedape'][1]:+.2f},{d['dmedape'][2]:+.2f}]  reps={d['reps']}")
print(f"\nconfig-median coverage {100*m.mean():.1f}% of iPhone rows; the {int((~m).sum())} it cannot score are")
print(ip[~m].groupby(ip[~m].storage_gb.isna()).size().rename({True:"no storage", False:"rare config"}).to_dict())
