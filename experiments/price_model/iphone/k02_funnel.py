import sys, warnings
sys.path.insert(0, "/Users/jakubkucera-sch/Documents/scraper/experiments/price_model/common")
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
B = "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/alert_audit/"
ip = pd.read_pickle(B + "ip.pkl")
days = (ip.created.max() - ip.created.min()).total_seconds() / 86400
weeks = days / 7
print(f"window {days:.3f} d = {weeks:.4f} wk, n={len(ip)} iphone rows, {ip.seller.nunique()} sellers")

ip["day"] = ip.created.dt.floor("D")
print("\nrows/day:", {str(k)[:10]: v for k, v in ip.day.value_counts().sort_index().to_dict().items()})
print("median price/day:", {str(k)[:10]: v for k, v in ip.groupby("day").price.median().to_dict().items()})

sig_c = np.std(ip.resid[ip.storage_gb.notna()]); sig_all = np.std(ip.resid)
print(f"\nsigma: all-iphone {sig_all:.4f}  complete-spec {sig_c:.4f}")
for t in (.15, .20, .25, .30, .40):
    print(f"  -{int(t*100)}%  log ratio {np.log(1-t):+.4f} = {abs(np.log(1-t))/sig_c:.2f} sigma (complete-spec)  {abs(np.log(1-t))/sig_all:.2f} sigma (all)")

FLOOR = 1000.0
ip["at_floor"] = ip.price <= FLOOR * 1.01
complete = ip.generation.notna() & ip.tier_ord.notna() & ip.storage_gb.notna()
gate = complete & (~ip.damage) & (~ip.scratches) & (~ip.at_floor)
print(f"\ngate pass: complete {100*complete.mean():.1f}%  full gate {100*gate.mean():.1f}%  (n_gate={int(gate.sum())})")
ip["gate"] = gate

idx_by = {}
for i, s in enumerate(ip.seller.values):
    idx_by.setdefault(s, []).append(i)
SELLERS = list(idx_by)


def boot_rate(mask_hit, n=4000, seed=0):
    rng = np.random.RandomState(seed)
    hit = np.asarray(mask_hit)
    out = []
    for _ in range(n):
        pick = rng.choice(len(SELLERS), len(SELLERS), replace=True)
        rows = np.concatenate([idx_by[SELLERS[j]] for j in pick])
        out.append(hit[rows].sum() / max(len(rows), 1))
    return float(np.mean(out)), float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


STEADY = 150.0
obs_rate = len(ip) / days
print(f"\nobserved iPhone-classified rows/day = {obs_rate:.1f}")
rows = []
for t in (.15, .20, .25, .30, .40):
    hit = (ip.resid <= np.log(1 - t)).values
    hg = hit & gate.values
    m, lo, hi = boot_rate(hg)
    mu, lou, hiu = boot_rate(hit)
    rows.append(dict(thr=f"-{int(t*100)}%", sigma=round(abs(np.log(1 - t)) / sig_c, 2),
                     n_ung=int(hit.sum()), pct_ung=round(100 * hit.mean(), 2),
                     n_gate=int(hg.sum()), pct_gate=round(100 * hg.mean(), 2),
                     wk_obs_gate=round(hg.sum() / weeks, 1),
                     wk150_gate=round(m * STEADY * 7, 1), wk150_lo=round(lo * STEADY * 7, 1),
                     wk150_hi=round(hi * STEADY * 7, 1), wk150_ung=round(mu * STEADY * 7, 1)))
F = pd.DataFrame(rows)
print("\n=== ALERT FUNNEL (my run) ===")
print(F.to_string(index=False))
F.to_csv(B + "funnel.csv", index=False)

print("\n=== DEDUP (distinct seller|title|price) ===")
for t in (.25, .40):
    sub = ip[(ip.resid <= np.log(1 - t)) & gate]
    k = sub.groupby(["seller", "name", "price"]).size()
    print(f"  -{int(t*100)}% gated: {len(sub)} rows -> {len(k)} distinct listings; "
          f"max rows from one seller: {sub.seller.value_counts().max() if len(sub) else 0}")

sig_map = {"cb": np.std(ip.resid[complete & ip.battery_pct.notna()]),
           "cn": np.std(ip.resid[complete & ip.battery_pct.isna()]),
           "ns": np.std(ip.resid[~complete])}
print("\ncompleteness sigmas:", {k: round(v, 4) for k, v in sig_map.items()},
      "n:", {"cb": int((complete & ip.battery_pct.notna()).sum()), "cn": int((complete & ip.battery_pct.isna()).sum()), "ns": int((~complete).sum())})
sg = np.where(complete & ip.battery_pct.notna(), sig_map["cb"], np.where(complete, sig_map["cn"], sig_map["ns"]))
ip["z"] = ip.resid / sg
print("\n=== z-THRESHOLD FUNNEL (gated, completeness-keyed sigma) ===")
for zt in (-1.5, -2.0, -2.5, -3.0, -3.5):
    h = ((ip.z <= zt) & gate).values
    m, lo, hi = boot_rate(h)
    sub = ip[(ip.z <= zt) & gate]
    md = 100 * sub.disc.median() if len(sub) else float("nan")
    print(f"  z<={zt}: n={int(h.sum())} rows, {sub.groupby(['seller','name','price']).ngroups} distinct, "
          f"{m*STEADY*7:.1f}/wk @150/day [{lo*STEADY*7:.1f},{hi*STEADY*7:.1f}], median disc {md:.0f}%")
ip.to_pickle(B + "ip.pkl")
