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
