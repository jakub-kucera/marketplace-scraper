\pset format aligned
-- when did bazos full_description start?
SELECT min(a.created)::date, max(a.created)::date, count(*) FROM bazos_ad a JOIN bazos_addelivery d ON d.ad_id=a.id WHERE d.query_id=8 AND a.full_description IS NOT NULL AND a.full_description<>'';
-- vinted price_raw shapes
SELECT a.marketplace, count(*) FILTER (WHERE a.price_raw ~ '\.') AS with_dot, count(*) AS n,
       min(a.price), max(a.price), round(avg(a.price)) AS mean, percentile_disc(0.5) WITHIN GROUP (ORDER BY a.price) AS median
FROM bazos_ad a JOIN bazos_addelivery d ON d.ad_id=a.id WHERE d.query_id IN (8,13,14) GROUP BY 1;
-- sample price_raw per marketplace
SELECT DISTINCT a.marketplace, a.price_raw FROM bazos_ad a JOIN bazos_addelivery d ON d.ad_id=a.id WHERE d.query_id IN (13,14) ORDER BY 1,2 LIMIT 20;
-- sbazar negotiable rows
SELECT a.name, a.price_raw, a.price, a.price_type FROM bazos_ad a JOIN bazos_addelivery d ON d.ad_id=a.id WHERE d.query_id=14 AND a.price_type<>'exact';
