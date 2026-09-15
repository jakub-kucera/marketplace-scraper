import sys, warnings
sys.path.insert(0, "/Users/jakubkucera-sch/Documents/scraper/experiments/price_model/common")
sys.path.insert(0, "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone")
import numpy as np, pandas as pd, ipfeat
warnings.filterwarnings("ignore")
B = "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/alert_audit/"
ip = pd.read_pickle(B + "ip.pkl")
bl = ip.apply(lambda r: ipfeat.norm(f"{r['name']} || {r.short_description or ''}"), axis=1)
g25 = ip[ip.gate].sort_values("resid").head(25)
FL = (ip.resid <= np.log(.75)) & ip.gate

print("=" * 110)
print("1. DOES THE BAIT FRACTION RISE WITH DEPTH? (my classification of the 25 gated -25% flags)")
print("=" * 110)
BAIT = {24260, 25341, 24845, 24800, 23713}
CLEAN = {23937, 24563}
for lab, sub in [("-25% (all 25)", g25), ("-30%", g25[g25.resid <= np.log(.70)]),
                 ("-40%", g25[g25.resid <= np.log(.60)]), ("z<=-2.5", g25[g25.z <= -2.5]),
                 ("z<=-3.0", g25[g25.z <= -3.0]), ("top 5 by residual", g25.head(5))]:
    nb = len(set(sub.id) & BAIT); nc = len(set(sub.id) & CLEAN)
    print(f"  {lab:20s} n={len(sub):2d}  bait/scam {nb}/{len(sub)} = {100*nb/max(len(sub),1):3.0f}%   "
          f"clean-deal candidates {nc}/{len(sub)} = {100*nc/max(len(sub),1):3.0f}%")

print("\n" + "=" * 110)
print("2. COMPOSITION OF THE 25 GATED -25% FLAGS vs CORPUS BASE RATE")
print("=" * 110)
PROX = {
    "bait/scam": (r"napiste mi svou nabidku|o ktere jsem ochotn|cenu si predstavuj|nevhodn\w* darek|odmitam utirat", 5),
    "duplicate relisting": (None, 2),
    "defect the gate misses": (r"prask\w*|\baz na\b|menen displej|vymenen\w* displej", 4),
    "thin-rung over-prediction": (None, 5),
    "dealer low-end price level": (None, 5),
    "no information / unsettleable": (None, 2),
    "genuinely cheap candidate": (None, 2),
}
k = ip.groupby(["seller", "name", "price"]).size()
dup = ip.set_index(["seller", "name", "price"]).index.isin(k[k > 1].index)
thin = ip.tier.isin(["se", "air", "max", "plus", "e"])
vc = ip.seller.value_counts()
dealer = ip.seller.isin(vc[vc >= 3].index)
BASE = {"duplicate relisting": dup, "thin-rung over-prediction": thin.values,
        "dealer low-end price level": dealer.values}
rows = []
for lab, (rx, n) in PROX.items():
    if rx is not None:
        b = bl.str.contains(rx, regex=True).values
    elif lab in BASE:
        b = BASE[lab]
    else:
        b = None
    br = 100 * b.mean() if b is not None else float("nan")
    rows.append(dict(bucket=lab, n_of_25=n, pct_of_flags=round(100 * n / 25, 0),
                     corpus_base_pct=(round(br, 2) if br == br else None),
                     enrichment=(round((n / 25) / (br / 100), 1) if br == br and br > 0 else None)))
print(pd.DataFrame(rows).to_string(index=False))
print("\n  (proxies are text/structure detectors that approximate the hand class; 'genuinely cheap',")
print("   'thin-rung over-prediction' and 'unsettleable' have no corpus-wide text proxy by construction)")

print("\n" + "=" * 110)
print("3. BATTERY SENSITIVITY -- how many flags survive if battery is priced at the HONEST")
print("   within-generation coefficient (+1.27%/pt) instead of the manifest's +0.58%/pt?")
print("=" * 110)
MED = 97.0
extra = 0.0127 - 0.0058
adj = np.where(ip.battery_pct.notna(), extra * (ip.battery_pct.fillna(MED) - MED), 0.0)
resid_adj = ip.resid.values - adj   # prediction moves by `adj`; residual moves the other way
print(f"  -25% gated flags, manifest battery coef: {int(FL.sum())}")
print(f"  -25% gated flags, honest battery coef  : {int(((resid_adj <= np.log(.75)) & ip.gate.values).sum())}")
print("\n  effect on the low-battery flags:")
for i, (_, r) in enumerate(g25.iterrows(), 1):
    if r.battery_pct == r.battery_pct and r.battery_pct < 90:
        a = extra * (r.battery_pct - MED)
        nr = r.resid - a
        print(f"    rank {i:2d} id={r.id} bat={r.battery_pct:.0f}%  disc {100*r.disc:5.1f}% -> "
              f"{100*(1-np.exp(nr)):5.1f}%   {'still flags' if nr<=np.log(.75) else 'DROPS OUT'}")

print("\n" + "=" * 110)
print("4. THE 'zadn' DAMAGE-GATE BUG, stated precisely")
print("=" * 110)
print("  ipfeat._NEG = (?:bez|zadn\\w*|nema|neni|nebyl\\w*|nikde neni|krome)\\s+(?:\\w+\\s+){0,2}")
print("  Czech 'zadni' = REAR/BACK; 'zadny/zadne/zadnych' = NONE. ipfeat.strip_diacritics maps")
print("  both to the stem 'zadn', so 'zadni sklo je prasklé' ('the BACK GLASS IS CRACKED') is read")
print("  as a negated damage claim and ipfeat.flags()['damage'] returns False.")
crack = bl.str.contains(r"prask\w*|rozbit\w*|puknut\w*", regex=True)
miss = crack & ~ip.damage
print(f"    rows with a crack word: {int(crack.sum())}   damage=True on {int(ip.damage[crack].sum())}   MISSED {int(miss.sum())}")
print(f"    missed rows that pass the gate: {int(ip.gate[miss].sum())}")
print(f"    missed rows in the -25% gated flags: {int((miss & FL).sum())}  (ids {list(ip.id[miss & FL])})")
print(f"    -> {int((miss & FL).sum())}/25 = {100*(miss & FL).sum()/25:.0f}% of the gated funnel is a cracked phone the gate was supposed to stop")
