-- @batch
CREATE OR ALTER VIEW gold.commercial_activity AS
SELECT f.currency, f.transaction_type, COUNT_BIG(*) AS current_order_lines,
       SUM(CAST(f.amount_minor AS decimal(38,0))) AS booked_amount_minor,
       SUM(f.amount_decimal) AS booked_amount_decimal
FROM gold.fact_order_line f
JOIN gold.commercial_status s ON s.status=f.status
WHERE f.transaction_type IN ('TVOD','EST')
GROUP BY f.currency, f.transaction_type;
-- @batch
CREATE OR ALTER VIEW gold.playback_activity AS
SELECT content_key, status, COUNT_BIG(*) AS current_sessions,
       MAX(position_seconds) AS furthest_position_seconds
FROM gold.fact_playback_session GROUP BY content_key, status;
-- @batch
CREATE OR ALTER VIEW gold.campaign_activity AS
SELECT campaign_key, COUNT_BIG(*) AS recorded_conversions
FROM gold.fact_campaign_conversion GROUP BY campaign_key;
-- @batch
CREATE OR ALTER VIEW gold.campaign_engaged_revenue AS
WITH contacts AS (
    SELECT campaign_key, customer_key, MIN(occurred_at) AS first_contact_at,
           COUNT_BIG(*) AS touches
    FROM gold.fact_campaign_touch
    GROUP BY campaign_key, customer_key
), link_candidates AS (
    -- UNION collapses the same recorded link supplied by both transaction and conversion.
    SELECT order_id, customer_key, campaign_key FROM gold.fact_order_line
    WHERE NULLIF(campaign_key,'') IS NOT NULL
    UNION
    SELECT order_id, customer_key, campaign_key FROM gold.fact_campaign_conversion
    WHERE NULLIF(campaign_key,'') IS NOT NULL
), recorded_links AS (
    SELECT order_id, customer_key, MIN(campaign_key) AS campaign_key,
           COUNT_BIG(*) AS campaign_count
    FROM link_candidates GROUP BY order_id, customer_key
), playback AS (
    -- Aggregate sessions before joining money; positions are progress, never watch time.
    SELECT order_id, customer_key, content_key, MAX(position_seconds) AS furthest_position_seconds,
           COUNT_BIG(*) AS sessions
    FROM gold.fact_playback_session GROUP BY order_id, customer_key, content_key
), orders AS (
    SELECT f.order_id, f.line_number, f.customer_key, f.content_key, f.currency, f.amount_minor,
           CAST(f.created_at AS date) AS created_date,
           CASE WHEN l.campaign_count=1 THEN l.campaign_key END AS campaign_key,
           a.first_contact_at,
           CASE WHEN l.campaign_count IS NULL THEN 'unattributed'
                WHEN l.campaign_count>1 THEN 'ambiguous'
                WHEN a.first_contact_at IS NULL OR a.first_contact_at>f.created_at THEN 'without_contact'
                ELSE 'recorded' END AS attribution_status,
           CAST(CASE WHEN p.sessions>0 OR f.first_play_at IS NOT NULL THEN 1 ELSE 0 END AS int) AS played,
           CAST(CASE WHEN c.duration_seconds>0 AND
                CAST(p.furthest_position_seconds AS decimal(38,0))*5 >= CAST(c.duration_seconds AS decimal(38,0))*4
                THEN 1 ELSE 0 END AS int) AS engaged,
           CAST(CASE WHEN c.duration_seconds IS NULL OR c.duration_seconds<=0 THEN 1 ELSE 0 END AS int) AS unknown_duration
    FROM gold.fact_order_line f
    LEFT JOIN recorded_links l ON l.order_id=f.order_id AND l.customer_key=f.customer_key
    LEFT JOIN contacts a ON l.campaign_count=1 AND a.campaign_key=l.campaign_key AND a.customer_key=f.customer_key
    LEFT JOIN playback p ON p.order_id=f.order_id AND p.customer_key=f.customer_key AND p.content_key=f.content_key
    LEFT JOIN gold.dim_content c ON c.content_key=f.content_key
    WHERE f.transaction_type IN ('TVOD','EST')
      AND EXISTS (SELECT 1 FROM gold.commercial_status s WHERE s.status=f.status)
)
-- Contact rows preserve non-buyers. They have no currency and must not carry money.
SELECT CAST('contact' AS varchar(7)) AS record_kind, a.campaign_key, a.customer_key,
       COALESCE(NULLIF(u.territory,''),'Unknown') AS territory,
       CAST(a.first_contact_at AS date) AS cohort_date, CAST(NULL AS date) AS created_date,
       a.first_contact_at, CAST(NULL AS varchar(3)) AS currency, a.touches,
       CAST(NULL AS varchar(128)) AS order_id, CAST(NULL AS int) AS line_number,
       CAST(NULL AS varchar(128)) AS content_key, CAST(NULL AS varchar(500)) AS title,
       CAST(NULL AS varchar(128)) AS genre, CAST(NULL AS varchar(300)) AS distributor,
       CAST(0 AS bigint) AS amount_minor, CAST('contact' AS varchar(16)) AS attribution_status,
       CAST(0 AS int) AS played, CAST(0 AS int) AS engaged, CAST(0 AS int) AS unknown_duration
FROM contacts a
LEFT JOIN gold.dim_customer u ON u.customer_key=a.customer_key
UNION ALL
SELECT CAST('order' AS varchar(7)), o.campaign_key, o.customer_key,
       COALESCE(NULLIF(u.territory,''),'Unknown'),
       CASE WHEN o.attribution_status='recorded' THEN CAST(o.first_contact_at AS date) END,
       o.created_date, o.first_contact_at, o.currency, CAST(0 AS bigint),
       o.order_id, o.line_number, o.content_key, COALESCE(NULLIF(c.title,''),o.content_key),
       COALESCE(NULLIF(c.genre,''),'Unknown'), COALESCE(NULLIF(d.name,''),'Unknown'),
       o.amount_minor, o.attribution_status, o.played, o.engaged, o.unknown_duration
FROM orders o
LEFT JOIN gold.dim_customer u ON u.customer_key=o.customer_key
LEFT JOIN gold.dim_content c ON c.content_key=o.content_key
LEFT JOIN gold.dim_distributor d ON d.distributor_key=c.distributor_key;
