-- Render {{SILVER_DATABASE}}, {{RUN_ID}}, {{CURRENCY_ROWS}}, {{STATUS_ROWS}}.
-- Only the approved same-workspace Silver SQL endpoint is a source.
-- Single writer required: serialize Spark publication and this bounded load.
SET NOCOUNT ON;
IF NOT EXISTS (SELECT 1 FROM {{SILVER_DATABASE}}.silver.publication WHERE run_id={{RUN_ID}})
    THROW 51000, 'Silver publication missing or failed; serving gate closed', 1;
IF EXISTS (SELECT order_id FROM {{SILVER_DATABASE}}.silver.rental GROUP BY order_id HAVING COUNT_BIG(*)<>1)
    THROW 51001, 'Duplicate current order natural key', 1;
IF EXISTS (SELECT session_id FROM {{SILVER_DATABASE}}.silver.playback GROUP BY session_id HAVING COUNT_BIG(*)<>1)
    THROW 51002, 'Duplicate playback session natural key', 1;
IF EXISTS (
    SELECT 1 FROM {{SILVER_DATABASE}}.silver.rental r
    LEFT JOIN {{SILVER_DATABASE}}.silver.offer o ON o.offer_key=r.offer_key
    LEFT JOIN {{SILVER_DATABASE}}.silver.customer c ON c.customer_key=r.customer_key
    WHERE o.offer_key IS NULL OR c.customer_key IS NULL OR r.currency<>o.currency
)
    THROW 51003, 'Unresolved order dimension or currency mismatch', 1;

BEGIN TRY
    BEGIN TRANSACTION;
    DELETE FROM gold.currency;
    INSERT INTO gold.currency (currency, minor_exponent) VALUES {{CURRENCY_ROWS}};
    DELETE FROM gold.commercial_status;
    INSERT INTO gold.commercial_status (status) VALUES {{STATUS_ROWS}};
    IF EXISTS (
        SELECT 1 FROM {{SILVER_DATABASE}}.silver.rental r
        LEFT JOIN gold.currency c ON c.currency=r.currency WHERE c.currency IS NULL
    ) THROW 51004, 'Currency minor-unit exponent missing', 1;

    -- Snapshot replacement is atomic inside the Warehouse. This does not assert
    -- atomicity with Eventstream sinks or Lakehouse writes.
    DELETE FROM gold.dim_customer;
    INSERT INTO gold.dim_customer
    SELECT customer_key, name, territory, source_customer_id FROM {{SILVER_DATABASE}}.silver.customer;
    DELETE FROM gold.dim_content;
    INSERT INTO gold.dim_content
    SELECT content_key, title, release_date, duration_seconds, genre, image_url,
           source_url, license, attribution, distributor_key FROM {{SILVER_DATABASE}}.silver.content;
    DELETE FROM gold.dim_offer;
    INSERT INTO gold.dim_offer
    SELECT offer_key, content_key, territory, currency, transaction_type, price_minor,
           start_window_hours, play_window_hours FROM {{SILVER_DATABASE}}.silver.offer;
    DELETE FROM gold.dim_distributor;
    INSERT INTO gold.dim_distributor SELECT distributor_key, name FROM {{SILVER_DATABASE}}.silver.distributor;
    DELETE FROM gold.dim_territory;
    INSERT INTO gold.dim_territory SELECT territory FROM {{SILVER_DATABASE}}.silver.territory;
    DELETE FROM gold.dim_campaign;
    INSERT INTO gold.dim_campaign
    SELECT campaign_key, name, territory, budget_minor, currency, channel, source_campaign_id
    FROM {{SILVER_DATABASE}}.silver.campaign;
    DELETE FROM gold.dim_date;
    INSERT INTO gold.dim_date
    SELECT d, YEAR(d), MONTH(d), DAY(d) FROM (
        SELECT CAST(created_at AS date) AS d FROM {{SILVER_DATABASE}}.silver.rental
        UNION SELECT release_date FROM {{SILVER_DATABASE}}.silver.content
        UNION SELECT CAST(converted_at AS date) FROM {{SILVER_DATABASE}}.silver.campaign_conversion
    ) observed_dates WHERE d IS NOT NULL;

    DELETE FROM gold.fact_order_line;
    INSERT INTO gold.fact_order_line
    SELECT r.order_id, 1, r.customer_key, r.offer_key, o.content_key, o.territory,
           r.currency, o.transaction_type, r.status, r.amount_minor,
           CAST(CAST(r.amount_minor AS decimal(23,4)) /
               CAST(CASE c.minor_exponent WHEN 0 THEN 1 WHEN 1 THEN 10
                    WHEN 2 THEN 100 WHEN 3 THEN 1000 WHEN 4 THEN 10000 END AS decimal(5,0))
               AS decimal(23,4)),
           r.created_at, r.start_deadline, r.first_play_at, r.expires_at,
           r.campaign_key, r.source_sequence, r.event_id, r.run_id
    FROM {{SILVER_DATABASE}}.silver.rental r
    JOIN {{SILVER_DATABASE}}.silver.offer o ON o.offer_key=r.offer_key
    JOIN gold.currency c ON c.currency=r.currency;
    DELETE FROM gold.fact_playback_session;
    INSERT INTO gold.fact_playback_session
    SELECT session_id, order_id, content_key, customer_key, position_seconds, status,
           last_event_at, source_sequence, event_id, run_id FROM {{SILVER_DATABASE}}.silver.playback;
    DELETE FROM gold.fact_campaign_conversion;
    INSERT INTO gold.fact_campaign_conversion
    SELECT conversion_key, campaign_key, customer_key, order_id, converted_at, source_sequence
    FROM {{SILVER_DATABASE}}.silver.campaign_conversion;
    DELETE FROM gold.fact_customer_consent;
    INSERT INTO gold.fact_customer_consent
    SELECT consent_key, customer_key, purpose, channel, granted, effective_at,
           source_consent_id, source_sequence, event_id, run_id
    FROM {{SILVER_DATABASE}}.silver.consent;
    DELETE FROM gold.fact_campaign_touch;
    INSERT INTO gold.fact_campaign_touch
    SELECT touch_key, customer_key, campaign_key, channel, touch_type, occurred_at,
           tracking_token, source_touch_id, source_sequence, event_id, run_id
    FROM {{SILVER_DATABASE}}.silver.touch;
    {{LINK_LOADS}}
    IF (SELECT COUNT_BIG(*) FROM gold.fact_order_line) <>
       (SELECT COUNT_BIG(*) FROM {{SILVER_DATABASE}}.silver.rental)
        THROW 51005, 'Order count reconciliation failed', 1;
    IF EXISTS (
        SELECT currency, SUM(CAST(amount_minor AS decimal(38,0))) amount_minor
        FROM gold.fact_order_line GROUP BY currency
        EXCEPT
        SELECT currency, SUM(CAST(amount_minor AS decimal(38,0)))
        FROM {{SILVER_DATABASE}}.silver.rental GROUP BY currency
    ) THROW 51006, 'Minor-unit reconciliation failed', 1;
    DELETE FROM gold.publication;
    INSERT INTO gold.publication
    SELECT {{RUN_ID}}, SYSUTCDATETIME(), COUNT_BIG(*) FROM gold.fact_order_line;
    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
