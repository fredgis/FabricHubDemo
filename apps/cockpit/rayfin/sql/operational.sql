-- Run AFTER Rayfin has applied its decorated entity schema, on its verified
-- app-linked SQL database. Additive, rerunnable; no destructive schema changes.
SET XACT_ABORT ON;
BEGIN TRANSACTION;
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='UX_MSFlix_receipt_key' AND object_id=OBJECT_ID('dbo.CommandReceipts'))
  CREATE UNIQUE INDEX UX_MSFlix_receipt_key ON dbo.CommandReceipts(idempotency_key);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='UX_MSFlix_outbox_event' AND object_id=OBJECT_ID('dbo.Outboxes'))
  CREATE UNIQUE INDEX UX_MSFlix_outbox_event ON dbo.Outboxes(event_id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='UX_MSFlix_sequence' AND object_id=OBJECT_ID('dbo.EventSequences'))
  CREATE UNIQUE INDEX UX_MSFlix_sequence ON dbo.EventSequences(sequence_key);
IF NOT EXISTS (SELECT 1 FROM dbo.EventSequences WITH (UPDLOCK,HOLDLOCK) WHERE sequence_key='operational')
  INSERT dbo.EventSequences(id,sequence_key,value) VALUES (NEWID(),'operational',0);
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name='CK_MSFlix_OfferMoney')
  ALTER TABLE dbo.Offers ADD CONSTRAINT CK_MSFlix_OfferMoney CHECK (
    price_minor>=0 AND transaction_type IN ('TVOD','EST','SVOD') AND
    (transaction_type<>'TVOD' OR (start_window_hours BETWEEN 1 AND 8760 AND play_window_hours BETWEEN 1 AND 8760)));
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name='CK_MSFlix_RentalMoney')
  ALTER TABLE dbo.Rentals ADD CONSTRAINT CK_MSFlix_RentalMoney CHECK (amount_minor>=0);
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name='CK_MSFlix_OutboxJson')
  ALTER TABLE dbo.Outboxes ADD CONSTRAINT CK_MSFlix_OutboxJson CHECK (ISJSON(payload_json)=1 AND payload=payload_json);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_MSFlix_OutboxPending' AND object_id=OBJECT_ID('dbo.Outboxes'))
  CREATE INDEX IX_MSFlix_OutboxPending ON dbo.Outboxes(source_sequence) WHERE published_at IS NULL;
IF OBJECT_ID('dbo.VolumeRuns') IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM sys.check_constraints WHERE name='CK_MSFlix_VolumeBounds')
  ALTER TABLE dbo.VolumeRuns ADD CONSTRAINT CK_MSFlix_VolumeBounds CHECK (
    total_orders BETWEEN 1 AND 100000 AND total_events BETWEEN total_orders AND 1900000
    AND committed_orders BETWEEN 0 AND total_orders AND committed_events BETWEEN 0 AND total_events
    AND committed_batches>=0);
COMMIT;

-- Worker database principals must be provisioned by the infrastructure owner.
-- No GRANT to public, db_owner, or browser identities.
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name='msflix_outbox_publisher')
  CREATE ROLE msflix_outbox_publisher;
GRANT SELECT ON dbo.Outboxes TO msflix_outbox_publisher;
GRANT UPDATE (published_at) ON dbo.Outboxes TO msflix_outbox_publisher;
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name='msflix_control_worker')
  CREATE ROLE msflix_control_worker;
GRANT SELECT ON dbo.ControlCommands TO msflix_control_worker;
GRANT UPDATE (status,completed_at,error) ON dbo.ControlCommands TO msflix_control_worker;
