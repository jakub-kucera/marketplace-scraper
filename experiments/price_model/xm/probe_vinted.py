"""Live probe: measure Vinted total_item_price vs price (buyer-protection fee) on MacBooks."""
import json, sys
from vinted_scraper import VintedScraper
s = VintedScraper(baseurl="https://www.vinted.cz")
items = s.search({"search_text": "macbook", "order": "newest_first", "per_page": 96,
                  "price_from": 2000, "price_to": 100000})
rows = []
for i in items:
    if i.price is None or i.total_item_price is None:
        continue
    rows.append({"id": i.id, "title": i.title, "price": float(i.price),
                 "total": float(i.total_item_price), "currency": i.currency,
                 "promoted": bool(getattr(i, "promoted", False))})
print("n =", len(rows))
json.dump(rows, open("xm/vinted_probe.json", "w"), ensure_ascii=False, indent=1)
for r in rows[:8]:
    print(f"{r['price']:>10.2f} -> {r['total']:>10.2f}   diff {r['total']-r['price']:>8.2f}")
