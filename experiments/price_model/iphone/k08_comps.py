import sys, warnings
sys.path.insert(0, "/Users/jakubkucera-sch/Documents/scraper/experiments/price_model/common")
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
B = "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/alert_audit/"
ip = pd.read_pickle(B + "ip.pkl")
ip["cfg"] = ip.gen_label.astype(str) + "|" + ip.tier.astype(str) + "|" + ip.storage_gb.astype(str)
tab = ip.groupby("cfg").price.agg(["median", "size", "min", "max"])
g = ip[ip.gate].sort_values("resid").head(25)
print("DOES A PURE COMPARABLES CHECK AGREE THE LISTING IS CHEAP? "
      "(same generation x tier x storage, OTHER sellers only)")
print("=" * 120)
rows = []
for i, (idx, r) in enumerate(g.iterrows(), 1):
    peers = ip[(ip.cfg == r.cfg) & (ip.seller != r.seller) & (ip.id != r.id)]
    med = peers.price.median() if len(peers) else np.nan
    disc_comp = (1 - r.price / med) * 100 if len(peers) and med == med else np.nan
    rows.append(dict(rank=i, id=r.id, cfg=r.cfg, price=int(r.price), model_pred=int(r.pred),
                     model_disc=round(100 * r.disc, 1), n_peers=len(peers),
                     peer_median=(int(med) if med == med else None),
                     peer_min=(int(peers.price.min()) if len(peers) else None),
                     comp_disc=(round(disc_comp, 1) if disc_comp == disc_comp else None)))
D = pd.DataFrame(rows)
print(D.to_string(index=False))
D.to_csv(B + "comps.csv", index=False)
print("\nsummary: of the 25 gated -25% flags,")
print(f"  with >=3 same-config peers from OTHER sellers: {int((D.n_peers>=3).sum())}")
sub = D[D.n_peers >= 3]
print(f"  of those, comp_disc >= 25%: {int((sub.comp_disc>=25).sum())}   comp_disc < 25%: {int((sub.comp_disc<25).sum())}")
print(f"  median model_disc {D.model_disc.median():.1f}% vs median comp_disc {sub.comp_disc.median():.1f}% (n={len(sub)})")
print(f"  flags with ZERO other-seller peers at their exact config: {int((D.n_peers==0).sum())}")
