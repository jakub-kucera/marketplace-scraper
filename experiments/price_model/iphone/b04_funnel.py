import sys, warnings, textwrap
sys.path.insert(0, "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2")
sys.path.insert(0, "/Users/jakubkucera-sch/Documents/scraper/experiments/price_model/common")
import numpy as np, pandas as pd, lib, ph
warnings.filterwarnings("ignore")
B = "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/s2/"
ip = pd.read_pickle(B+"ip2.pkl")
oof = np.load(B+"oofA_ip.npy")
oofH = np.load(B+"oofH_ip.npy")
ip["pred"] = np.exp(oof)
ip["resid"] = ip.log_price - oof
ip["disc"] = 1 - ip.price/ip.pred
days = (ip.created.max()-ip.created.min()).total_seconds()/86400
weeks = days/7
print(f"window {days:.2f} days = {weeks:.3f} weeks; n={len(ip)} iphone rows")

FLOOR = 1000.0
ip["at_floor"] = ip.price <= FLOOR*1.01
ip["near_floor"] = ip.price <= FLOOR*1.25
print("at-floor base rate %.2f%%  near-floor(<=1250) %.2f%%" % (100*ip.at_floor.mean(), 100*ip.near_floor.mean()))

sig_all = np.std(ip.resid); sig_c = np.std(ip.resid[ip.storage_gb.notna()])
print(f"sigma all-iphone {sig_all:.3f}   complete-spec {sig_c:.3f}")
for t in (0.15,0.20,0.25,0.30,0.40):
    print(f"  -{int(t*100)}% = {abs(np.log(1-t))/sig_all:.2f} sigma (all)  {abs(np.log(1-t))/sig_c:.2f} sigma (complete)")

gate_complete = ip.storage_gb.notna()
gate = gate_complete & (~ip.damage) & (~ip.scratches) & (~ip.at_floor)
gate_nofloorword = gate_complete & (~ip.damage) & (~ip.at_floor)
print("\ngate pass rates: complete %.1f%%  +no-damage/scratch+floor %.1f%%  +no-damage+floor %.1f%%"
      % (100*gate_complete.mean(), 100*gate.mean(), 100*gate_nofloorword.mean()))

rows=[]
for t in (0.15,0.20,0.25,0.30,0.40):
    hit = ip.resid <= np.log(1-t)
    rows.append(dict(threshold=f"-{int(t*100)}%",
        n_ungated=int(hit.sum()), per_wk_ungated=round(hit.sum()/weeks,1),
        n_gate_complete=int((hit&gate_complete).sum()), per_wk_complete=round((hit&gate_complete).sum()/weeks,1),
        n_gated=int((hit&gate).sum()), per_wk_gated=round((hit&gate).sum()/weeks,1),
        sigma_equiv=round(abs(np.log(1-t))/sig_c,2)))
F=pd.DataFrame(rows); print("\n=== ALERT FUNNEL (ridge FULL, protocol A OOF)"); print(F.to_string(index=False))

# floor-ad enrichment inside the tail
K = min(100, max(25, int(0.10*len(ip))))
tail = ip.nsmallest(K, "resid")
print(f"\nfloor ads in the {K} most-underpriced: {100*tail.at_floor.mean():.1f}% vs base {100*ip.at_floor.mean():.2f}%"
      f"  enrichment {(tail.at_floor.mean()/max(ip.at_floor.mean(),1e-9)):.1f}x")
hit25 = ip.resid <= np.log(0.75)
print(f"share of -25% flags that are floor ads: {100*ip.at_floor[hit25].mean():.1f}% (n={int(hit25.sum())})")

# composition of the bottom tail
print("\n=== BOTTOM-%d RESIDUAL COMPOSITION (enrichment vs base)" % K)
for f in ["damage","scratches","multi_unit","swap","locked","battery_replaced","at_floor","dealer_pickup","new_word","mint_words"]:
    b = ip[f].mean(); a = tail[f].mean()
    print(f"  {f:16s} tail {100*a:5.1f}%  base {100*b:5.1f}%  {a/max(b,1e-9):5.2f}x")
for lab, m in [("gen<=11", ip.generation<=11), ("battery missing", ip.battery_pct.isna()),
               ("battery<=80", ip.battery_pct<=80), ("storage missing", ip.storage_gb.isna())]:
    b = m.mean(); a = m[tail.index].mean()
    print(f"  {lab:16s} tail {100*a:5.1f}%  base {100*b:5.1f}%  {a/max(b,1e-9):5.2f}x")

# ---- the top 12 GATED flags, for hand audit
g = ip[gate].sort_values("resid").head(12)
print("\n" + "="*110)
print("TOP 12 GATED FLAGS (complete spec, no damage/scratch vocabulary, above the 1000 CZK floor)")
print("="*110)
for i,(_,r) in enumerate(g.iterrows(),1):
    print(f"\n[{i}] id={r.id} price={int(r.price):,} CZK  pred={int(r.pred):,}  disc={100*r.disc:.1f}%  resid={r.resid:+.2f} ({r.resid/sig_c:+.2f}s)")
    print(f"    spec: gen={r.gen_label} tier={r.tier} storage={r.storage_gb} battery={r.battery_pct} colour={r.color} seller={r.seller} seller_ads={r.seller_total} status={r.status}")
    print(f"    TITLE: {r['name']}")
    print("    PREV: " + textwrap.shorten((r.short_description or "").replace("\n"," "), 300))
    print(f"    url: {r.url}")
F.to_csv(B+"funnel.csv", index=False)
g.to_csv(B+"top12.csv", index=False)
