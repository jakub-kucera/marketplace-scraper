import sys, warnings, re
sys.path.insert(0, "/Users/jakubkucera-sch/Documents/scraper/experiments/price_model/common")
sys.path.insert(0, "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone")
import numpy as np, pandas as pd, ipfeat
warnings.filterwarnings("ignore")
B = "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/alert_audit/"
ip = pd.read_pickle(B + "ip.pkl")

print("=" * 100)
print("A. IS THE ALERT FLAGGING SELLERS RATHER THAN LISTINGS?")
print("=" * 100)
top = ip[ip.gate].sort_values("resid").head(20)
print("sellers contributing >1 of the top 20:")
for s, k in top.seller.value_counts().items():
    sub = ip[ip.seller == s]
    print(f"  {s:8s} {k} of top20 | {len(sub):2d} ads in corpus | mean resid {sub.resid.mean():+.3f} "
          f"| median resid {sub.resid.median():+.3f} | frac gated-flagged@-25% "
          f"{((sub.resid<=np.log(.75))&sub.gate).mean():.2f} | name={sub.publisher_name.iloc[0]}")
print("\ncorpus mean |seller mean resid| for sellers with >=3 ads:")
vc = ip.seller.value_counts()
m3 = ip[ip.seller.isin(vc[vc >= 3].index)]
gm = m3.groupby("seller").resid.agg(["mean", "size"]).sort_values("mean")
print(gm.head(8).to_string())
print("... between-seller share of residual variance (sellers with >=2 ads):")
m2 = ip[ip.seller.isin(vc[vc >= 2].index)]
bet = m2.groupby("seller").resid.mean()
n_by = m2.groupby("seller").size()
grand = m2.resid.mean()
ssb = float((n_by * (bet - grand) ** 2).sum()); sst = float(((m2.resid - grand) ** 2).sum())
print(f"    n={len(m2)} rows / {m2.seller.nunique()} sellers, between-share {ssb/sst:.3f}")

print("\n" + "=" * 100)
print("B. THE DAMAGE GATE ON FLAG #16 ('Zadni sklo je prasklé') -- does the gate really miss it?")
print("=" * 100)
r16 = ip[ip.id == 24890].iloc[0]
ex = ipfeat.extract(r16["name"], r16.short_description)
print("  damage=", ex["damage"], " scratches=", ex["scratches"])
t = ipfeat.norm(f"{r16['name']} || {r16.short_description}")
print("  normalised blob:", t[:400])
print("  'prask' present:", bool(re.search(r"prask\w*", t)))
print("  _neg_aware(prask...):", ipfeat._neg_aware(t, r"prask\w*"))
for pat in [r"(?:bez|zadn\w*|nema|neni|nebyl\w*|nikde neni|krome)\s+(?:\w+\s+){0,2}prask\w*"]:
    print("  NEG-match:", re.findall(pat, t))

print("\n" + "=" * 100)
print("C. THE THIN RUNGS -- are two flagged Airs two bargains, or one mis-calibrated rung?")
print("=" * 100)
for tier in ["air", "se", "mini", "plus"]:
    sub = ip[ip.tier == tier]
    print(f"\n  tier={tier}: n={len(sub)} median resid {sub.resid.median():+.3f} mean {sub.resid.mean():+.3f} "
          f"sigma {sub.resid.std():.3f} | flagged@-25% gated {int(((sub.resid<=np.log(.75))&sub.gate).sum())}")
    if tier in ("air", "plus"):
        print(sub[["id", "gen_label", "storage_gb", "price", "pred", "resid", "seller"]].sort_values("price").to_string(index=False))
print("\n  pre-11 generations (gen<=10.5):")
sub = ip[ip.generation <= 10.5]
print(f"    n={len(sub)} median resid {sub.resid.median():+.3f} mean {sub.resid.mean():+.3f} sigma {sub.resid.std():.3f} "
      f"| flagged@-25% gated {int(((sub.resid<=np.log(.75))&sub.gate).sum())} = {100*((sub.resid<=np.log(.75))&sub.gate).mean():.1f}% vs corpus {100*((ip.resid<=np.log(.75))&ip.gate).mean():.1f}%")

print("\n" + "=" * 100)
print("D. FLAG #4 -- would fixing the 'procent' extraction miss remove the flag?")
print("=" * 100)
med_bat = ip.battery_pct.median()
print(f"  median stated battery = {med_bat}")
print("  coefficients from the full-corpus unscaled ridge (b05/manifest): battery +0.58%/pt, battery-missing -9.1%")
r4 = ip[ip.id == 24069].iloc[0]
print(f"  #4: price {int(r4.price)} pred {int(r4.pred)} resid {r4.resid:+.3f}")
delta = 0.0058 * (75 - med_bat) + 0.091  # remove the missing penalty, apply battery=75 vs median fill
print(f"  counterfactual log-pred shift if battery_pct=75 were parsed: {delta:+.3f}")
print(f"  -> corrected resid approx {r4.resid - delta:+.3f} (discount {100*(1-np.exp(r4.resid-delta)):.1f}%) "
      f"-- {'STILL flags at -25%' if (r4.resid-delta) <= np.log(.75) else 'no longer flags'}")

print("\n" + "=" * 100)
print("E. CORPUS BASE RATES for the audit categories")
print("=" * 100)


def blob(r):
    return ipfeat.norm(f"{r['name']} || {r.short_description or ''}")


bl = ip.apply(blob, axis=1)
CATS = {
    "locked/iCloud/carrier words": r"\b(?:za)?blokovan\w*|(?:za)?zamcen\w*|icloud lock|zamek aktivace|operator lock|blokace",
    "icloud mentioned at all": r"icloud",
    "operator mentioned": r"operator\w*",
    "replaced display": r"novy\s+displej|vymenen\w*\s+displej|displej\w*\s+vymenen|novy lcd",
    "non-genuine/aftermarket": r"neoriginal\w*|aftermarket|kopie displej|neorig\w*",
    "battery replaced": r"nova bater\w*|vymenen\w* bater\w*|bater\w* vymenen|novou bater\w*",
    "grey-market/non-EU": r"\busa\b|\bus verz\w*|americk\w* verz\w*|dovoz z|import z|japonsk\w* verz|hongkong|\bhk verz",
    "multi-unit lot": r"\b\dx\s*iphone|\biphone\s+\d+\s+a\s+\d+\b|vice kusu|vice ks\b|\d\s*ks\b|cena za kus",
    "swap offered (any phrasing)": r"vymen\w*|smen\w*|protiucet",
    "swap offered (ipfeat regex)": r"vymen\w*\s*za|prodam nebo vymen\w*|mozna vymena|protiucet",
    "defect-as-exception (az na / krome)": r"\baz na\b|\bkrome\b|nefunguje pouze|jen\s+\w+\s+nefunguje",
    "price-anchor / make-me-an-offer": r"napiste mi svou nabidku|cena dohod\w*|o ktere jsem ochotn|cenu si predstavuj|nabidnete",
    "unwanted gift": r"nevhodn\w* darek|nechten\w* darek|darek ktery",
    "cracked glass/display words": r"prask\w*|rozbit\w*|puknut\w*",
}
rows = []
for lab, rx in CATS.items():
    base = bl.str.contains(rx, regex=True)
    tail = base[top.index]
    f25 = base[(ip.resid <= np.log(.75)) & ip.gate]
    rows.append(dict(cat=lab, n_corpus=int(base.sum()), pct_corpus=round(100 * base.mean(), 2),
                     n_top20=int(tail.sum()), n_flag25gated=int(f25.sum()), pct_flag25=round(100 * f25.mean(), 1),
                     enrich=round(f25.mean() / max(base.mean(), 1e-9), 2)))
print(pd.DataFrame(rows).to_string(index=False))

print("\n" + "=" * 100)
print("F. RELISTING base rate")
print("=" * 100)
k = ip.groupby(["seller", "name", "price"]).size()
dup = k[k > 1]
dupmask = ip.set_index(["seller", "name", "price"]).index.isin(dup.index)
print(f"  (seller,title,price) triples repeating: {len(dup)}, covering {int(dupmask.sum())} rows = {100*dupmask.mean():.2f}% of corpus")
f25m = (ip.resid <= np.log(.75)) & ip.gate
print(f"  in the -25% gated flags: {int(dupmask[f25m.values].sum())}/{int(f25m.sum())} = {100*dupmask[f25m.values].mean():.1f}%  "
      f"enrichment {dupmask[f25m.values].mean()/max(dupmask.mean(),1e-9):.2f}x")
print(f"  in the top 20:            {int(dupmask[[ip.index.get_loc(i) for i in top.index]].sum())}/20")
print(f"  distinct titles: {ip['name'].nunique()}/{len(ip)} = {100*ip['name'].nunique()/len(ip):.1f}%")
