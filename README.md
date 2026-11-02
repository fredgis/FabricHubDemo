<p align="center">
  <img src="docs/assets/msflix-banner.svg" alt="MSFlix Business Control" width="100%">
</p>

<p align="center">
  <strong>Entertainment operations, grounded in actual business activity.</strong><br>
  Oracle · Salesforce · SAP · Kafka / RTI · Microsoft Fabric · Planning · Ontology v2 · Rayfin
</p>

# MSFlix Business Control

*For demonstration purposes only; all business data is fictional.*

A shared view of the entertainment business: films and offers, fictional CRM
audiences, actual demonstration rentals, purchases and playback. The cockpit
executes transactions; the business model consolidates them; Ontology connects
their customer, campaign, content and commercial relationships.

https://github.com/user-attachments/assets/226308ce-ce07-4e5a-ba60-c2cd0478adc2

## Where the Gold business tables come from

Overall MSFlix business architecture, with source-to-table lineage.

```mermaid
flowchart LR
  Oracle["ORACLE<br/>Films · rental/purchase offers<br/>Territories · prices · reference distributors"]
  CRM["SALESFORCE / BPS<br/>Fictional CRM customers<br/>Campaigns · marketing touches · consents"]
  RTI["RTI / KAFKA<br/>Persisted rentals · purchases · playback<br/>Cockpit → SQL outbox → events"]

  subgraph GOLD["MSFLIX BUSINESS MODEL · GOLD WAREHOUSE"]
    Catalogue["CATALOGUE<br/>gold.dim_content · gold.dim_offer<br/>gold.dim_distributor · gold.dim_territory"]
    Clients["CLIENTS<br/>gold.dim_customer"]
    Marketing["MARKETING<br/>gold.dim_campaign · gold.fact_customer_consent<br/>gold.fact_campaign_touch"]
    Transactions["TRANSACTIONS<br/>gold.fact_order_line<br/>gold.fact_playback_session"]
    Conversions["RECORDED CONVERSIONS · 0<br/>gold.fact_campaign_conversion"]
  end

  Ontology["ONTOLOGY v2<br/>Shared business relationships"]
  App["MSFLIX BUSINESS CONTROL<br/>Cockpit · operations · business views"]
  SAP["SAP<br/>Subscriptions · billing<br/>Distributor contracts · financial data"]
  Planning["PLANNING<br/>Forecasts and scenarios"]
  Flixy["FLIXY<br/>Native Fabric Data Agent<br/>Gold + ontology native graph"]

  Oracle --> Catalogue
  CRM --> Clients
  CRM --> Marketing
  RTI --> Transactions
  Marketing -->|"Campaign key"| Conversions
  RTI -->|"Explicit recorded attribution only"| Conversions
  GOLD --> Ontology
  GOLD --> App
  Ontology --> App
  App -->|"Committed transactions"| RTI
  SAP --> GOLD
  GOLD --> Planning
  GOLD --> Flixy
  Ontology -->|"Native graph"| Flixy
  Flixy -->|"Read-only conversation"| App

  classDef source fill:#1B1C1F,stroke:#ED6757,color:#F3F0EC;
  classDef business fill:#ED6757,stroke:#ED6757,color:#121315;
  class Oracle,CRM,RTI,Ontology,App,SAP,Planning,Flixy source;
  class Catalogue,Clients,Marketing,Transactions,Conversions business;
  style GOLD fill:#121315,stroke:#ED6757,color:#F3F0EC;
  linkStyle 2 stroke:#ED6757,stroke-width:2px;
```

`content_key`, `customer_key`, `offer_key` and `campaign_key` link the same
business entities across sources, Gold and Ontology.

Clients, campaigns, consents and marketing touches reach Gold through native BPS.
Recorded conversions remain **0**: none are invented.

**Verified backbone:** actual Task Flow **9 tasks / 12 connectors / 47
assignments**, Gold **1,008 demonstration orders**, and a live Gold-backed
Ontology graph. The cockpit combines a cinematic film-led home, business views
and an interactive graph with visible relationships, zoom and node selection.

**MSFlix Insights**, immediately below Business Graph, joins published Gold
orders, Oracle catalogue, Salesforce customer context and associated RTI playback.
A shared date, territory, genre, transaction and currency selection drives the
daily charts, territory/genre heatmap and film ranking. Amounts stay separated
by currency; the source panel identifies unpublished integrations, including SAP.
See the [dashboard definitions](docs/COCKPIT.md#msflix-insights) for the cohort
and source boundaries.

The **Demo tab** generates bounded, real business transactions through the same
application commands. A persistent cloud worker publishes their events to Kafka,
then refreshes Raw, Silver, Gold and the ontology graph. Its accepted checkpoint
contains **13,477 propagated events**. Analytics refresh is asynchronous, not an
instantaneous consequence of clicking a command.

**Flixy** is available from its floating bubble on every cockpit tab, connected
to the native Fabric Data Agent for Gold and the ontology's real relationships.
Microsoft currently blocks direct ontology-v2
attachment, so its supported **native graph** is used instead. Access is
identity-scoped; see [Flixy](docs/FLIXY.md) for the source and authentication details.

## Run it

Open the MSFlix cockpit at the privately supplied `https://<app-host>`
with an authorized identity. For deployment or replay, use the
[source and execution documentation](docs/ARCHITECTURE.md); run only the needed
stage against the approved environment, never reset existing source data.

Keep real deployment identifiers, endpoints and identity bindings only in
ignored local `.env`, `.state`, or private binding files; never commit them.
Copy `fabric/target-policy.example.json` to ignored `fabric/target-policy.json`
and fill the approved values locally. Flixy authoring uses ignored
`.state/flixy/target.json`, based on `agents/flixy/target.example.json`.
Documentation placeholders are labels, not additional runtime settings.
Publishing is a separate operation requiring explicit authorization.

## Deep dives

[Architecture](docs/ARCHITECTURE.md) · [Oracle](docs/ORACLE.md) ·
[Salesforce / BPS](docs/SALESFORCE-BPS.md) · [RTI](docs/RTI.md) ·
[Warehouse → Ontology](docs/WAREHOUSE-ONTOLOGY.md) ·
[Workspace Task Flow and folders](docs/TASK-FLOW.md) · [Cockpit](docs/COCKPIT.md) ·
[Automatic Demo propagation](docs/DEMO-AUTOMATION.md) · [Flixy](docs/FLIXY.md)

[SAP data model and cross-domain links](docs/SAP-DATA-MODEL.md) ·
[Visual model](docs/assets/sap-msflix-model.html).
The [native SAP integration](docs/IMPLEMENTATION-PLAN.md#sap-native-bps-and-warehouse-publication)
uses a private Datasphere landing, mirroring and isolated BPS processing.
SAP serving is moving to **native BPS Gold → `sap_live` SQL views/functions,
without copied Warehouse SAP tables or a second feeding pipeline**.
The old Warehouse writer is retired; Silver/Gold qualification and upstream
BPS processing remain. Final deployment status is recorded in the
[execution plan](docs/IMPLEMENTATION-PLAN.md#sap-zero-copy-serving--migration-authorized).
The scenario remains synthetic SVOD; the native ORDER_ID link to TVOD/EST orders
is not populated. This change does not implement SAP in the cockpit or Planning.

Customer identities are fictional. No real bank charge or commercial
film-distribution right is claimed. Sourced imagery retains its individual
license; original editorial imagery is never presented as an official poster.
See [catalog provenance](data/catalog.sources.json).

<details>
<summary>Refresh the operational Warehouse</summary>

Oracle Mirroring runs continuously. New Demo transactions propagate automatically;
this sequence is for a **complete source/master refresh**. Pause the automatic
worker first and wait for its current cycle to finish; follow the
[automation runbook](docs/DEMO-AUTOMATION.md) before resuming it with the updated
master configuration. Kafka broker ACKs and exact event coverage must precede
analytics publication; native OneLake availability has a **five-minute target**,
not a guaranteed maximum delay.

1. Complete **Salesforce native BPS extraction → native B2S/Silver**. Salesforce
   native BPS Gold is optional for this operational refresh.
2. Export/stage the **processed BPS snapshots through our CLI**, following the
   [native-source handoff](docs/SALESFORCE-BPS.md).
3. Run **MSFlixRawProcessing before MSFlixSilverProcessing**:
   `--stage process` runs both automatically in that order.
4. Load **Gold through the CLI**, not a Gold notebook.
5. Refresh the **Gold-backed Ontology graph**.

```powershell
py -3 -m fabric.deploy --config fabric\config.live.local.json --stage process
py -3 -m fabric.deploy --config fabric\config.live.local.json --stage gold
py -3 -m scripts.refresh_ontology_graph
```

Full prerequisites and source commands are in the
[BPS](docs/SALESFORCE-BPS.md), [RTI](docs/RTI.md) and
[Warehouse](docs/WAREHOUSE-ONTOLOGY.md) deep dives. The native BPS Touch/facts
relationship gate is separate; it does not block loading its processed Silver
data into this Warehouse. SAP reuses native BPS Gold through zero-copy SQL
interfaces; the operational refresh does not load SAP. Do not invoke the retired
Warehouse SAP publisher.

</details>

## License

This project is licensed under the [MIT License](LICENSE).
Third-party code and assets retain their respective licenses.
