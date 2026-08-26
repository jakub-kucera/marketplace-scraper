import pandas as pd, sys
sys.path.insert(0,'.'); import mbfeat
df = pd.read_pickle('xm/raw.pkl'); f = pd.read_pickle('xm/f_title.pkl')
d = pd.concat([df.reset_index(drop=True), f.reset_index(drop=True).add_prefix('x_')], axis=1)
d = d[d.x_kind=='macbook']
for m in ['vinted','sbazar']:
    s = d[d.marketplace==m]
    for field, label in [('x_screen','SCREEN'),('x_chip_brand','CHIP'),('x_ram_gb','RAM'),('x_ssd_gb','SSD'),('x_year','YEAR')]:
        miss = s[s[field].isna()]
        print(f"\n===== {m}: {label} missing {len(miss)}/{len(s)} =====")
        print('\n'.join('  '+t for t in miss.name.head(14)))
