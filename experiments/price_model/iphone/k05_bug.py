import sys, warnings, re
sys.path.insert(0, "/Users/jakubkucera-sch/Documents/scraper/experiments/price_model/common")
sys.path.insert(0, "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone")
import numpy as np, pandas as pd, ipfeat
warnings.filterwarnings("ignore")
B = "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/alert_audit/"
ip = pd.read_pickle(B + "ip.pkl")
bl = ip.apply(lambda r: ipfeat.norm(f"{r['name']} || {r.short_description or ''}"), axis=1)

print("=" * 100)
print("BUG: 'zadni' (rear) de-accents to the same stem as 'zadne' (none) -> _NEG swallows real damage")
print("=" * 100)
print("  _NEG alternation:", r"(?:bez|zadn\w*|nema|neni|nebyl\w*|nikde neni|krome)")
print("  Czech 'zadni'=REAR/BACK, 'zadny/zadne'=NONE. strip_diacritics maps zadni<-zadni, zadne<-zadne. Both hit zadn\\w*.")
hit = bl.str.contains(r"zadn\w*\s+(?:\w+\s+){0,2}(?:prask|rozbit|poskozen|nefunk|vadn|skraban|oder|promackl)", regex=True)
print(f"\n  rows where a damage/scratch word is preceded within 2 words by 'zadn...': {int(hit.sum())}")
for i in ip.index[hit]:
    r = ip.loc[i]
    ex = ipfeat.extract(r["name"], r.short_description)
    seg = re.findall(r".{0,40}zadn\w*\s+(?:\w+\s+){0,2}(?:prask|rozbit|poskozen|nefunk|vadn|skraban|oder|promackl)\w*.{0,30}", bl[i])
    print(f"    id={r.id} damage={ex['damage']} scratches={ex['scratches']} gate={r.gate} resid={r.resid:+.3f} price={int(r.price)}")
    print(f"       ...{seg[0] if seg else ''}...")

print("\n  how many corpus rows contain a crack word at all vs how many get damage=True:")
crack = bl.str.contains(r"prask\w*|rozbit\w*|puknut\w*", regex=True)
print(f"    crack word present: {int(crack.sum())}  of which damage flag True: {int(ip.damage[crack].sum())}  MISSED: {int((~ip.damage[crack]).sum())}")
print(f"    of the missed, how many pass the gate: {int(ip.gate[crack & ~ip.damage].sum())}")
print(f"    of the missed & gated, how many flag at -25%: {int(((ip.resid<=np.log(.75)) & ip.gate & crack & ~ip.damage).sum())}")

print("\n" + "=" * 100)
print("WHO SUPPLIES THE 25 GATED -25% FLAGS")
print("=" * 100)
f = ip[(ip.resid <= np.log(.75)) & ip.gate]
vc = f.seller.value_counts()
print(vc.to_string())
print(f"\n  top-3 sellers supply {int(vc.head(3).sum())}/{len(f)} = {100*vc.head(3).sum()/len(f):.0f}% of flags")
print(f"  distinct sellers among 25 flags: {f.seller.nunique()}")
print(f"  corpus: 365 sellers / 639 ads")

print("\n" + "=" * 100)
print("iPHONE-SPECIFIC FAILURE MODES -- every matching row, with its gate/flag state")
print("=" * 100)
MODES = {
    "LOCKED (icloud/carrier/blokovany/zamceny)": r"\b(?:za)?blokovan\w*|(?:za)?zamcen\w*|icloud lock|zamek aktivace|operator lock|blokace|vazan\w* na operator",
    "REPLACED/NON-GENUINE DISPLAY or BATTERY": r"novy\s+displej|vymenen\w*\s+displej|displej\w*\s+(?:byl\s+)?vymenen|novy lcd|neoriginal\w*|aftermarket|neorig\b|kopie displej|servisovan",
    "BATTERY REPLACED (100% health on a swapped cell)": r"nova bater\w*|vymenen\w* bater\w*|bater\w* (?:byla )?vymenen|novou bater\w*|vymena bater",
    "GREY MARKET / non-EU": r"\busa\b|\bus verz\w*|americk\w* verz\w*|dovoz z\b|import\w*|japonsk\w*|hongkong|\bhk\b|dual sim fyzick",
    "MULTI-UNIT LOT": r"\b\d\s*x\s*iphone|iphone\s+\d+\s+a\s+(?:iphone\s+)?\d+|vice kusu|vice ks\b|\d\s*ks\b|cena za kus|dva kusy|tri kusy",
}
for lab, rx in MODES.items():
    m = bl.str.contains(rx, regex=True)
    fl = (ip.resid <= np.log(.75)) & ip.gate
    print(f"\n  {lab}")
    print(f"    corpus {int(m.sum())} rows ({100*m.mean():.2f}%) | passing gate {int(ip.gate[m].sum())} "
          f"| in -25% gated flags {int((m & fl).sum())}/{int(fl.sum())}")
    seen = 0
    for i in ip.index[m]:
        if seen >= 4:
            break
        g = re.findall(r".{0,45}(?:" + rx + r").{0,45}", bl[i])
        print(f"      id={ip.loc[i,'id']} price={int(ip.loc[i,'price'])} resid={ip.loc[i,'resid']:+.2f} gate={ip.loc[i,'gate']} :: ...{(g[0] if g else '')[:110]}...")
        seen += 1
# battery 100% with a replaced cell
rep = bl.str.contains(r"nova bater\w*|vymenen\w* bater\w*|novou bater\w*", regex=True)
b100 = ip.battery_pct >= 99
print(f"\n  SWAPPED CELL REPORTING >=99%: {int((rep & b100).sum())} rows "
      f"({100*(rep & b100).mean():.2f}%) | battery>=99 overall {int(b100.sum())} ({100*b100.mean():.1f}% of all, "
      f"{100*b100.sum()/ip.battery_pct.notna().sum():.1f}% of those stating one)")
print(f"  mean resid for battery>=99 & replaced: {ip.resid[rep & b100].mean():+.3f} vs battery>=99 not replaced: {ip.resid[b100 & ~rep].mean():+.3f}")
