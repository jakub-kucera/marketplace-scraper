\pset format aligned
SELECT d.query_id, a.marketplace, count(*) AS n,
       min(a.created)::date AS first_seen, max(a.created)::date AS last_seen,
       count(a.price) AS price_nn,
       count(NULLIF(a.location,'')) AS loc_nn,
       count(a.view_count) AS views_nn,
       count(a.publish_date) AS pubdate_nn,
       count(a.email_publisher_id) AS email_nn,
       count(a.phone_publisher_id) AS phone_nn,
       count(NULLIF(a.publisher_name,'')) AS pubname_nn,
       count(NULLIF(a.short_description,'')) AS shortdesc_nn,
       count(NULLIF(a.full_description,'')) AS fulldesc_nn,
       sum(CASE WHEN a.topped THEN 1 ELSE 0 END) AS topped_n,
       round(avg(length(a.name))) AS avg_name_len,
       round(avg(length(a.short_description))) AS avg_short_len,
       round(avg(length(coalesce(a.full_description,'')))) AS avg_full_len
FROM bazos_ad a JOIN bazos_addelivery d ON d.ad_id=a.id
WHERE d.query_id IN (8,13,14)
GROUP BY d.query_id, a.marketplace ORDER BY d.query_id;

SELECT a.marketplace, a.price_type, count(*) FROM bazos_ad a JOIN bazos_addelivery d ON d.ad_id=a.id
WHERE d.query_id IN (8,13,14) GROUP BY 1,2 ORDER BY 1,3 DESC;

SELECT a.marketplace, count(*) AS zero_price FROM bazos_ad a JOIN bazos_addelivery d ON d.ad_id=a.id
WHERE d.query_id IN (8,13,14) AND a.price = 0 GROUP BY 1;

SELECT d.query_id, d.status, count(*) FROM bazos_addelivery d WHERE d.query_id IN (8,13,14) GROUP BY 1,2 ORDER BY 1,3 DESC;
