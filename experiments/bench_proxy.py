#!/usr/bin/env python3
"""Throwaway Bazos proxy/bandwidth benchmark.

Standalone (no Django, no DB). Measures REAL on-the-wire byte sizes, latency,
and HTTP status for the three request shapes the scraper uses:

  1. HTML search page   (search.php)            -- what run_scraper does today
  2. API listing        (api/v1/ads.php)        -- BazosApiScraper, tunable limit
  3. API ad detail      (api/v1/ad-detail-2.php) -- load_full_description

Then extrapolates monthly bandwidth at several cadences so you can see what
"run more often" costs, and doubles as a block-rate probe (--repeat) to compare
proxies (Tor vs a provider vs direct).

Usage:
  python bench_proxy.py                         # direct (no proxy)
  python bench_proxy.py --proxy socks5h://127.0.0.1:9050          # Tor
  python bench_proxy.py --proxy http://user:pass@host:port        # provider
  python bench_proxy.py --queries 15 --query auto --repeat 20     # block-rate probe

Notes:
  * "wire" = compressed bytes as billed by a proxy (Accept-Encoding: gzip forced,
    so no brotli dependency). "decoded" = uncompressed payload you actually parse.
  * Proxy billing usually adds ~5-10% for request + header overhead on top of the
    response body measured here.
  * SOCKS support needs PySocks (already present for Tor: `requests[socks]`).
"""
import argparse
import gzip
import json
import time
import zlib

import requests

API_BASE = "https://www.bazos.cz/api/v1"
HTML_SEARCH = "https://www.bazos.cz/search.php"

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
# The hidden API is the mobile app's backend; use a plausible app-ish UA.
MOBILE_UA = "okhttp/4.12.0"


def human(n_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n_bytes) < 1024 or unit == "GB":
            return f"{n_bytes:.1f} {unit}"
        n_bytes /= 1024
    return f"{n_bytes:.1f} GB"


def fetch(session, url, params=None, ua=DESKTOP_UA):
    """One GET. Returns (status, wire_bytes, decoded_bytes, elapsed_s, decoded_bytes_obj, headers)."""
    headers = {"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}
    t0 = time.perf_counter()
    resp = session.get(url, params=params, headers=headers, stream=True, timeout=30)
    raw = resp.raw.read(decode_content=False)  # bytes exactly as sent over the wire
    elapsed = time.perf_counter() - t0

    enc = (resp.headers.get("Content-Encoding") or "").lower()
    try:
        if "gzip" in enc:
            decoded = gzip.decompress(raw)
        elif "deflate" in enc:
            try:
                decoded = zlib.decompress(raw)
            except zlib.error:
                decoded = zlib.decompress(raw, -zlib.MAX_WBITS)
        else:
            decoded = raw
    except Exception:
        decoded = raw
    resp.close()
    return resp.status_code, len(raw), len(decoded), elapsed, decoded, resp.headers


def try_json(decoded_bytes):
    try:
        return json.loads(decoded_bytes)
    except Exception:
        return None


def count_html_ads(decoded_bytes) -> int:
    # cheap heuristic matching BazosScraper's find_all(class_='inzeraty')
    return decoded_bytes.count(b'class="inzeraty"')


def line(label, status, wire, decoded, elapsed, extra=""):
    ok = "OK " if status == 200 else "!! "
    print(f"  {ok}{label:<34} status={status}  wire={human(wire):>9}  "
          f"decoded={human(decoded):>9}  {elapsed:5.2f}s  {extra}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proxy", default="", help="proxy URL, e.g. socks5h://127.0.0.1:9050 or http://user:pass@host:port")
    ap.add_argument("--query", default="iphone", help="search term (try a broad one like 'auto')")
    ap.add_argument("--queries", type=int, default=12, help="enabled-query count for the extrapolation")
    ap.add_argument("--repeat", type=int, default=1, help="hit the API listing N times to sample block-rate + latency")
    args = ap.parse_args()

    session = requests.Session()
    if args.proxy:
        session.proxies = {"http": args.proxy, "https": args.proxy}

    print("=== Bazos proxy benchmark ===")
    print(f"Proxy: {args.proxy or 'DIRECT (no proxy)'}")

    # egress IP + country (best effort) -- confirms the proxy routes & where it exits
    try:
        ip = session.get("https://icanhazip.com", timeout=15).text.strip()
        try:
            country = session.get("https://ipinfo.io/country", timeout=15).text.strip()
        except Exception:
            country = "?"
        print(f"Egress IP: {ip}  country={country}")
    except Exception as e:
        print(f"Egress IP: FAILED ({e}) -- proxy may be down")

    print()
    print("--- request shapes (single sample each) ---")

    # 1. HTML search page (mirrors the blacklist-check / listing request)
    html_params = {"hledat": args.query, "hlokalita": "", "humkreis": "25",
                   "cenaod": "", "cenado": "", "Submit": "Hledat"}
    s, wire_html, dec_html, t, body, _ = fetch(session, HTML_SEARCH, html_params, ua=DESKTOP_UA)
    n_html_ads = count_html_ads(body) or 20
    line("HTML search.php", s, wire_html, dec_html, t,
         f"ads~{n_html_ads}  {human(wire_html / max(n_html_ads,1))}/ad")

    # 2a. API listing, small limit (steady-state dedup probe)
    s, wire_api10, dec, t, body, hdrs = fetch(
        session, f"{API_BASE}/ads.php",
        {"query": args.query, "limit": 10, "offset": 0, "sort": "date"}, ua=MOBILE_UA)
    data = try_json(body) or []
    total = hdrs.get("x-total-count", "?")
    n = len(data) if isinstance(data, list) else 0
    line("API ads.php limit=10", s, wire_api10, dec, t,
         f"ads={n}  total={total}  {human(wire_api10 / max(n,1))}/ad")
    first_id = data[0]["id"] if n else None

    # 2b. API listing, full page (backfill / deep paging)
    s, wire_api210, dec, t, body, hdrs = fetch(
        session, f"{API_BASE}/ads.php",
        {"query": args.query, "limit": 210, "offset": 0, "sort": "date"}, ua=MOBILE_UA)
    data2 = try_json(body) or []
    n2 = len(data2) if isinstance(data2, list) else 0
    line("API ads.php limit=210", s, wire_api210, dec, t,
         f"ads={n2}  {human(wire_api210 / max(n2,1))}/ad")

    # 3. API ad detail
    wire_detail = None
    detail = None
    if first_id:
        s, wire_detail, dec, t, body, _ = fetch(
            session, f"{API_BASE}/ad-detail-2.php", {"ad_id": first_id}, ua=MOBILE_UA)
        detail = try_json(body)
        n_imgs = len(detail.get("images", [])) if isinstance(detail, dict) else 0
        line(f"API ad-detail-2.php id={first_id}", s, wire_detail, dec, t, f"images[]={n_imgs}")
    else:
        print("  -- skipped ad detail (no ad id from listing)")

    # 3b. Images: download the full-size gallery + one thumbnail, measure real bytes.
    #     Images are the dominant bandwidth term in any "download all images" plan.
    img_full_avg = None
    thumb_bytes = None
    n_imgs = 0
    if isinstance(detail, dict):
        images = detail.get("images") or []
        n_imgs = len(images)
        thumb_url = detail.get("image_thumbnail")
        if thumb_url:
            try:
                s, thumb_bytes, _, t, _, _ = fetch(session, thumb_url, ua=MOBILE_UA)
                line("image thumbnail (image_thumbnail)", s, thumb_bytes, thumb_bytes, t)
            except Exception as e:
                print(f"  -- thumbnail fetch failed: {e}")
        # sample up to 3 full-size images to get an average
        sample = images[:3]
        sizes = []
        for u in sample:
            try:
                s, w, _, t, _, _ = fetch(session, u, ua=MOBILE_UA)
                sizes.append(w)
            except Exception:
                pass
        if sizes:
            img_full_avg = sum(sizes) / len(sizes)
            line(f"full-size image (avg of {len(sizes)})", 200, img_full_avg, img_full_avg, 0.0,
                 f"gallery: {n_imgs} imgs -> {human(img_full_avg * n_imgs)}/ad full, "
                 f"{human((thumb_bytes or 0) * n_imgs)}/ad thumbs")

    # optional block-rate / latency sampling on the API listing
    if args.repeat > 1:
        print()
        print(f"--- block-rate probe: {args.repeat}x API ads.php limit=10 ---")
        statuses, lats = {}, []
        for _ in range(args.repeat):
            try:
                s, w, d, t, _, _ = fetch(
                    session, f"{API_BASE}/ads.php",
                    {"query": args.query, "limit": 10, "offset": 0, "sort": "date"}, ua=MOBILE_UA)
            except Exception as e:
                s, t = f"ERR:{type(e).__name__}", 0.0
            statuses[s] = statuses.get(s, 0) + 1
            lats.append(t)
        ok = statuses.get(200, 0)
        print(f"  status distribution: {statuses}")
        print(f"  success: {ok}/{args.repeat} ({100*ok/args.repeat:.0f}%)  "
              f"avg latency: {sum(lats)/len(lats):.2f}s")

    # --- extrapolation --------------------------------------------------------
    N = args.queries
    print()
    print(f"=== monthly bandwidth extrapolation (N={N} queries) ===")
    print("passes/day = 1200 / interval_min   (16h day + 8h night@x2)")
    print(f"per-request wire bytes measured: HTML={human(wire_html)}  "
          f"API(limit=10)={human(wire_api10)}"
          + (f"  detail={human(wire_detail)}" if wire_detail else ""))
    print()
    print(f"  {'cadence':>9} {'passes/d':>9} {'HTML now (3x page/q)':>22} {'API trimmed (1x l=10/q)':>26}")
    for interval_min in (30, 15, 5, 2):
        passes = 1200 / interval_min
        # HTML today: ~3 Bazos requests/query, each ~ a search page
        html_month = passes * N * 3 * wire_html * 30
        # API trimmed: 1 small listing request/query
        api_month = passes * N * 1 * wire_api10 * 30
        print(f"  {str(interval_min)+' min':>9} {passes:>9.0f} "
              f"{human(html_month):>22} {human(api_month):>26}")

    print()
    print("Detail-endpoint cost scales with (#ads pulled) x (passes/day), NOT #queries:")
    if wire_detail:
        for tracked in (50, 300):
            for interval_min in (30, 5):
                passes = 1200 / interval_min
                reqs = tracked * passes
                gb = reqs * wire_detail * 30
                print(f"  {tracked:>4} ads x {interval_min:>2} min  -> "
                      f"{reqs:>8.0f} detail req/day, {human(gb):>9}/mo  "
                      f"(req/IP/day over a 100-IP pool: {reqs/100:.0f})")
    # image-download scenario: bandwidth scales with (ads with images pulled) x (imgs/ad),
    # independent of cadence. This dwarfs every other term.
    if img_full_avg:
        print()
        print(f"Image download cost (measured: {human(img_full_avg)}/full img, "
              f"{human(thumb_bytes or 0)}/thumb, gallery~{n_imgs} imgs/ad):")
        print("scales with (new ads you pull images for) x (imgs/ad) -- NOT cadence")
        for ads_per_day in (500, 2000):
            full_mo = ads_per_day * n_imgs * img_full_avg * 30
            thumb_mo = ads_per_day * n_imgs * (thumb_bytes or 0) * 30
            print(f"  {ads_per_day:>4} ads/day x {n_imgs} imgs -> "
                  f"full={human(full_mo):>9}/mo   thumbs-only={human(thumb_mo):>9}/mo")
        print("  -> route image bulk-download through a cheap DATACENTER unlimited-bandwidth")
        print("     plan (static assets, low ban-sensitivity); keep API/listing on residential.")

    print()
    print("Reminder: ban risk = requests/day / pool_size (per-IP rate), not GB.")


if __name__ == "__main__":
    main()
