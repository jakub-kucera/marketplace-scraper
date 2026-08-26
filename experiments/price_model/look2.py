import pandas as pd, re, collections
df = pd.read_csv('mb/macbook_ads.csv')
b = df[df.marketplace=='bazos'].copy()
b['blob'] = (b.name.fillna('') + ' || ' + b.short_description.fillna('')).str.lower()

# how many actually mention macbook at all
print("mentions macbook in name:", b.name.str.lower().str.contains('macbook|mac book').sum(), "/", len(b))
print("mentions macbook in blob:", b.blob.str.contains('macbook|mac book').sum())
print("\n--- names NOT containing macbook (first 25) ---")
for n in b[~b.name.str.lower().str.contains('macbook|mac book')].name.head(25): print("  ", n)

print("\n\n--- token frequency for spec-ish tokens ---")
pats = {
 'chip_M': r'\bm[1-4]\b', 'pro_chip': r'm[1-4]\s*pro', 'max_chip': r'm[1-4]\s*max', 'ultra': r'm[1-4]\s*ultra',
 'intel_i': r'\bi[357]\b', 'ram_gb': r'\d{1,3}\s*gb\s*(ram|pam)', 'gb_any': r'\d{1,4}\s*gb', 'tb': r'\d\s*tb',
 'ssd': r'ssd', 'year': r'\b20[0-2]\d\b', 'inch': r'(13|14|15|16|11|12)[\s]*("|”|“|\'\'|palc|″)',
 'zaruka': r'z[áa]ruka', 'cykly': r'cykl', 'baterie': r'baterie|battery', 'stav': r'stav',
 'dph': r'dph', 'novy': r'nov[ýy]', 'top':'top', 'sleva': r'sleva', 'vada': r'vad[ay]|nefunk|rozbit|poškoz|praskl',
 'air': r'\bair\b', 'prom': r'\bpro\b', 'retina': r'retina', 'touchbar': r'touch\s*bar',
 'kondice_pct': r'\d{1,3}\s*%', 'a1\d{3}': r'a1\d{3}', 'us_kbd': r'\bus\b', 'cz_kbd': r'\bcz\b',
}
for k,p in pats.items():
    print(f"  {k:14s} {b.blob.str.contains(p, regex=True).sum():5d}  ({b.blob.str.contains(p,regex=True).mean()*100:.1f}%)")
