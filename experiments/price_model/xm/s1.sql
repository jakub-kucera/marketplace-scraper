\pset format wrapped
\x on
SELECT * FROM bazos_ad a JOIN bazos_addelivery d ON d.ad_id=a.id WHERE d.query_id=13 ORDER BY a.created DESC LIMIT 3;
SELECT * FROM bazos_ad a JOIN bazos_addelivery d ON d.ad_id=a.id WHERE d.query_id=14 ORDER BY a.created DESC LIMIT 3;
