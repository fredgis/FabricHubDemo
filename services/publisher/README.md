# Actual Kafka outbox publisher

The publisher sends **only persisted business events** from the app-linked
operational `dbo.Outboxes`; it never creates fake rental messages to make a chart
look populated. It authenticates to SQL and the Event Hubs Kafka endpoint with
an explicitly selected Entra credential: Azure CLI's cache for a bounded
operator run, or VM managed identity for deployed automation.

The deploying user needs Event Hubs Data Sender scoped to `msflix-events` and
read/update access to this application's actual operational database.
Discover that database from the Rayfin app, not an unrelated workspace SQL DB.

```powershell
py -3 -m pip install -r services\publisher\requirements.txt
py -3 services\publisher\publish.py --tenant <tenant> --server <app-sql-server> `
  --database <app-database> --namespace <namespace> --duration 120 --max-messages 1000
```

One SQL session lock prevents competing publishers. Marking `published_at`
happens only after Kafka broker acknowledgement. A crash between broker ACK and
SQL commit can replay an event; consumers must deduplicate `event_id`. The JSON
envelope retains the payload object and the equivalent canonical `payload_json`
required by the Raw Lakehouse sink. No secrets are written or displayed.

The publisher fetches and acknowledges batches (128 events by default,
`--batch-size` from 1 to 512), then commits one SQL update for the fully
acknowledged batch. Any failed or missing ACK leaves the whole batch unpublished
in SQL; already acknowledged events can replay and are deduplicated downstream.
`--max-messages` is bounded at 20,000 per run; duration remains bounded at
600 seconds plus the current batch's acknowledgement wait.

Use `--auth managed-identity` on an Azure VM (optional
`--managed-identity-client-id` for a user-assigned identity).
`--exit-when-empty` ends a bounded pass as soon as the outbox is drained.
It never falls back to Azure CLI when managed identity is selected.

The persistent systemd worker and exact-ID Raw → Silver → Gold → graph gates
are documented in [DEMO-AUTOMATION.md](../../docs/DEMO-AUTOMATION.md). This service
uses the existing VM/capacity, not a detached workstation process.
