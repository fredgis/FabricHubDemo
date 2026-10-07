SET NOCOUNT ON;
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name='gold') EXEC('CREATE SCHEMA gold');

IF OBJECT_ID('gold.dim_customer','U') IS NULL
CREATE TABLE gold.dim_customer (
    customer_key varchar(128) NOT NULL, name varchar(300) NULL,
    territory varchar(64) NULL, source_customer_id varchar(128) NULL
);
IF OBJECT_ID('gold.dim_content','U') IS NULL
CREATE TABLE gold.dim_content (
    content_key varchar(128) NOT NULL, title varchar(500) NULL,
    release_date date NULL, duration_seconds bigint NULL, genre varchar(128) NULL,
    image_url varchar(1500) NULL, source_url varchar(1500) NULL,
    license varchar(300) NULL, attribution varchar(2000) NULL,
    distributor_key varchar(128) NULL
);
IF OBJECT_ID('gold.dim_offer','U') IS NULL
CREATE TABLE gold.dim_offer (
    offer_key varchar(128) NOT NULL, content_key varchar(128) NULL,
    territory varchar(64) NULL, currency varchar(3) NULL,
    transaction_type varchar(16) NULL, price_minor bigint NULL,
    start_window_hours bigint NULL, play_window_hours bigint NULL
);
IF OBJECT_ID('gold.dim_distributor','U') IS NULL
CREATE TABLE gold.dim_distributor (distributor_key varchar(128) NOT NULL, name varchar(300) NULL);
IF OBJECT_ID('gold.dim_territory','U') IS NULL
CREATE TABLE gold.dim_territory (territory varchar(64) NOT NULL);
IF OBJECT_ID('gold.dim_campaign','U') IS NULL
CREATE TABLE gold.dim_campaign (
    campaign_key varchar(128) NOT NULL, name varchar(300) NULL, territory varchar(64) NULL,
    budget_minor bigint NULL, currency varchar(3) NULL, channel varchar(64) NULL,
    source_campaign_id varchar(128) NULL
);
IF OBJECT_ID('gold.dim_date','U') IS NULL
CREATE TABLE gold.dim_date (date_key date NOT NULL, calendar_year int NULL, calendar_month int NULL, day_of_month int NULL);
IF OBJECT_ID('gold.currency','U') IS NULL
CREATE TABLE gold.currency (currency varchar(3) NOT NULL, minor_exponent int NOT NULL);
IF OBJECT_ID('gold.commercial_status','U') IS NULL
CREATE TABLE gold.commercial_status (status varchar(64) NOT NULL);
IF OBJECT_ID('gold.fact_order_line','U') IS NULL
CREATE TABLE gold.fact_order_line (
    order_id varchar(128) NOT NULL, line_number int NOT NULL,
    customer_key varchar(128) NOT NULL, offer_key varchar(128) NOT NULL,
    content_key varchar(128) NOT NULL, territory varchar(64) NULL,
    currency varchar(3) NOT NULL, transaction_type varchar(16) NOT NULL,
    status varchar(64) NOT NULL, amount_minor bigint NOT NULL,
    amount_decimal decimal(23,4) NOT NULL, created_at datetime2(6) NOT NULL,
    start_deadline datetime2(6) NULL, first_play_at datetime2(6) NULL,
    expires_at datetime2(6) NULL, campaign_key varchar(128) NULL,
    source_sequence bigint NOT NULL, event_id varchar(128) NOT NULL,
    run_id varchar(128) NOT NULL
);
IF OBJECT_ID('gold.fact_playback_session','U') IS NULL
CREATE TABLE gold.fact_playback_session (
    session_id varchar(128) NOT NULL, order_id varchar(128) NOT NULL,
    content_key varchar(128) NOT NULL, customer_key varchar(128) NOT NULL,
    position_seconds bigint NOT NULL, status varchar(64) NOT NULL,
    occurred_at datetime2(6) NULL, source_sequence bigint NOT NULL,
    event_id varchar(128) NOT NULL, run_id varchar(128) NOT NULL
);
IF OBJECT_ID('gold.fact_campaign_conversion','U') IS NULL
CREATE TABLE gold.fact_campaign_conversion (
    conversion_key varchar(128) NOT NULL, campaign_key varchar(128) NOT NULL,
    customer_key varchar(128) NOT NULL, order_id varchar(128) NOT NULL,
    converted_at datetime2(6) NOT NULL, source_sequence bigint NOT NULL
);
IF OBJECT_ID('gold.publication','U') IS NULL
CREATE TABLE gold.publication (run_id varchar(128) NOT NULL, completed_at datetime2(6) NOT NULL, order_lines bigint NOT NULL);
IF OBJECT_ID('gold.fact_customer_consent','U') IS NULL
CREATE TABLE gold.fact_customer_consent (
    consent_key varchar(128) NOT NULL, customer_key varchar(128) NOT NULL,
    purpose varchar(128) NOT NULL, channel varchar(64) NOT NULL, granted bit NOT NULL,
    effective_at datetime2(6) NOT NULL, source_consent_id varchar(128) NULL,
    source_sequence bigint NOT NULL, event_id varchar(128) NOT NULL, run_id varchar(128) NOT NULL
);
IF OBJECT_ID('gold.fact_campaign_touch','U') IS NULL
CREATE TABLE gold.fact_campaign_touch (
    touch_key varchar(128) NOT NULL, customer_key varchar(128) NOT NULL,
    campaign_key varchar(128) NOT NULL, channel varchar(64) NOT NULL,
    touch_type varchar(128) NOT NULL, occurred_at datetime2(6) NOT NULL,
    tracking_token varchar(256) NULL, source_touch_id varchar(128) NULL,
    source_sequence bigint NOT NULL, event_id varchar(128) NOT NULL, run_id varchar(128) NOT NULL
);
