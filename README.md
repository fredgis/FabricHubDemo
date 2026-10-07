<p align="center">
  <img src="docs/assets/msflix-banner.svg" alt="MSFlix Business Control" width="100%">
</p>

<p align="center">
  <strong>Entertainment operations, grounded in actual business activity.</strong><br>
  Oracle · Salesforce · SAP · Kafka / RTI · Microsoft Fabric · Planning · Ontology v2 · Rayfin
</p>

# MSFlix Business Control

A shared view of the entertainment business: films and offers, fictional CRM
audiences, actual demonstration rentals, purchases and playback. The cockpit
executes transactions; the business model consolidates them; Ontology connects
their customer, campaign, content and commercial relationships.

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
    Marketing["MARKETING · BOOTSTRAP TODAY<br/>gold.dim_campaign · gold.fact_customer_consent<br/>gold.fact_campaign_touch"]
    Transactions["TRANSACTIONS<br/>gold.fact_order_line<br/>gold.fact_playback_session"]
    Conversions["RECORDED CONVERSIONS · 0<br/>gold.fact_campaign_conversion"]
  end

  Ontology["ONTOLOGY v2<br/>Shared business relationships"]
  App["MSFLIX BUSINESS CONTROL<br/>Cockpit · operations · business views"]
  SAP["SAP<br/>Subscriptions · billing<br/>Distributor contracts · financial data"]
  Planning["PLANNING<br/>Forecasts and scenarios"]

  Oracle --> Catalogue
  CRM -->|"700 native Contacts ready + staged"| Clients
  CRM -.->|"Three native marketing objects pending"| Marketing
  RTI --> Transactions
  Marketing -->|"Campaign key"| Conversions
  RTI -->|"Explicit recorded attribution only"| Conversions
  GOLD --> Ontology
  GOLD --> App
  Ontology --> App
  App -->|"Committed transactions"| RTI
  SAP --> GOLD
  GOLD --> Planning

  classDef source fill:#1B1C1F,stroke:#ED6757,color:#F3F0EC;
  classDef business fill:#ED6757,stroke:#ED6757,color:#121315;
  classDef pending fill:#1B1C1F,stroke:#ED6757,color:#F3F0EC,stroke-dasharray:5 4;
  class Oracle,CRM,RTI,Ontology,App,SAP,Planning source;
  class Catalogue,Clients,Transactions,Conversions business;
  class Marketing pending;
  style GOLD fill:#121315,stroke:#ED6757,color:#F3F0EC;
  linkStyle 2 stroke:#ED6757,color:#ED6757;
```

`content_key`, `customer_key`, `offer_key` and `campaign_key` link the same
business entities across sources, Gold and Ontology.

Native BPS Contacts are ready and staged; their Gold refresh is running.
**Red dashed:** campaigns, consents and touches still use bootstrap data until
those three objects are added to native BPS. Recorded conversions remain
**0**—none are invented.

RTI and the first Gold publication are verified, including **1,002 actual
demonstration orders**. The cockpit is deployed; source refresh and Gold-backed
graph qualification are tracked in the deep dives.

The originally proposed **notebook-based simulation was not delivered**.
A cockpit **Demo tab is an idea only**, outside the current implementation scope.

## Run it

Open the [MSFlix cockpit](https://<app-host>)
with an authorized identity. For deployment or replay, use the
[source and execution documentation](docs/ARCHITECTURE.md); run only the needed
stage against the approved environment, never reset existing source data.

## Deep dives

[Architecture](docs/ARCHITECTURE.md) · [Oracle](docs/ORACLE.md) ·
[Salesforce / BPS](docs/SALESFORCE-BPS.md) · [RTI](docs/RTI.md) ·
[Warehouse → Ontology](docs/WAREHOUSE-ONTOLOGY.md) ·
[Workspace Task Flow and folders](docs/TASK-FLOW.md) · [Cockpit](docs/COCKPIT.md)

Customer identities are fictional. No real bank charge or commercial
film-distribution right is claimed. Sourced imagery retains its individual
license; original editorial imagery is never presented as an official poster.
See [catalog provenance](data/catalog.sources.json).
