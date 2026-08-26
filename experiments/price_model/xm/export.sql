COPY (
  SELECT a.id, a.marketplace, a.external_id, a.created, a.modified, a.name,
         a.price_raw, a.price, a.price_type, a.location, a.view_count, a.publish_date,
         a.topped, a.short_description, a.full_description, a.publisher_name,
         a.email_publisher_id, a.phone_publisher_id, a.url,
         d.query_id, d.status, d.filter_reason
  FROM bazos_ad a
  JOIN bazos_addelivery d ON d.ad_id = a.id
  WHERE d.query_id IN (8, 13, 14)
) TO STDOUT WITH CSV HEADER;
