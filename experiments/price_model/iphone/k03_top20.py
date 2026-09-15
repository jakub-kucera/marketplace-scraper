import sys, warnings, textwrap
sys.path.insert(0, "/Users/jakubkucera-sch/Documents/scraper/experiments/price_model/common")
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
B = "/private/tmp/claude-502/-Users-jakubkucera-sch-Documents-scraper/18f66f1b-ff25-4403-a13b-d145a0332ec1/scratchpad/iphone/alert_audit/"
ip = pd.read_pickle(B + "ip.pkl")
g = ip[ip.gate].sort_values("resid").head(20)
print("TOP 20 GATED FLAGS -- complete spec, no damage/scratch vocab, price > 1000 CZK floor")
print("=" * 120)
for i, (_, r) in enumerate(g.iterrows(), 1):
    print(f"\n[{i}] id={r.id} ext={r.external_id} price={int(r.price):,} pred={int(r.pred):,} "
          f"disc={100*r.disc:.1f}% resid={r.resid:+.3f} z={r.z:+.2f}")
    print(f"    spec gen={r.gen_label} tier={r.tier} storage={r.storage_gb} bat={r.battery_pct} "
          f"colour={r.color} | seller={r.seller} seller_ads={r.seller_total} name={r.publisher_name} "
          f"loc={r.location} views={r.view_count} status={r.status} created={str(r.created)[:16]}")
    fl = [f for f in ["damage", "scratches", "swap", "new_word", "warranty", "mint_words", "box", "vat_dph",
                      "battery_replaced", "locked", "multi_unit", "sealed_new", "urgent", "dealer_pickup",
                      "icloud_clear", "invoice", "cz_region", "eu_region", "usa_region", "bundle_other", "esim"] if bool(r[f])]
    print(f"    flags: {','.join(fl) or '-'}")
    print(f"    TITLE: {r['name']}")
    print("    DESC : " + (r.short_description or "").replace("\n", " ⏎ "))
    print(f"    url  : {r.url}")
g.to_csv(B + "top20.csv", index=False)
