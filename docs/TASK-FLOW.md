# Workspace Task Flow and physical organization

**Workspace:** MSFlix, `<WORKSPACE_ID>`.
**Capacity:** active F16 `<capacity-name>`, Singapore;
`<CAPACITY_ID>`.
The workspace description is blank.

## Execution result: actual native graph and item assignments

| Deliverable | Result |
|---|---|
| Physical inventory | **47 actual related items**, including the native Flixy Data Agent. |
| Safe organization | **9 real folders; 46 of 47 physical items placed and read back.** |
| Native organization | **24 BPS artifacts in `02 Salesforce BPS`, all 4 cockpit items in `08 Cockpit`**; native children followed their parents, all names/IDs/connections preserved. |
| Remaining folder gate | Native BPS solution `<CRM_BPS_ITEM_ID>` remains at root: documented move returned **404 EntityNotFound**. |
| Actual Fabric Task Flow | **Persisted and read back: 9 tasks, 12 connectors and 47 unique native artifact assignments.** Flixy's extension preserved the original eight tasks and 46 assignments using ETag concurrency. |

A folder or Markdown diagram is not a Task Flow. This delivery now includes
the **actual saved native graph**, not just documentation artifacts.

| Native graph identity | Actual value |
|---|---|
| Name | `MSFlix Business Architecture` |
| Flow ID | `<TASK_FLOW_ID>` |
| Native resource ID | `<TASK_FLOW_RESOURCE_ID>` |
| Flixy extension ETag | `"<TASK_FLOW_ETAG>"` |

### Exact observed contract and resolved routing

- Microsoft Learn documents task creation, connectors and assignment through
  the **Fabric portal**, not the public core REST API.
- The official Fabric CLI command reference exposes no Task Flow command;
  `fab` is not installed in this environment.
- Installed `semantic-link-labs 0.17.0` and the public Microsoft source expose no
  Task Flow helper.
- The exact current portal module
  `web.workspace-task-flow.min.21c2e7bb59ddc9688d54.js` was then observed. It
  defines `metadata/workspaces/{workspaceId}/taskflow202602` for reads,
  `taskflow202512` for creates/updates, ETag concurrency and native task/item DTOs.
- The generic `api.powerbi.com` host initially returned **403 Tenant not
  authorized for cluster**. This was a routing error, not proof that the feature
  or admin permissions were unavailable.
- The captured `sharedBEWorkspaceApi` host adapter uses the workspace's
  `apiEndpoint`. The already-tested workspace DNS route is
  `https://<workspace-api-host>`.
  The native read succeeded there with the cached **Power BI-audience token**.
- The original native flow list was **empty** and backed up before creation.
  POST `taskflow202512` returned **201** and a resource location/ETag.
  PUT with `If-Match` returned **200**; GET `taskflow202602` returned the exact
  original 8-task/9-edge/46-item structure. The 8 October Flixy extension returned
  the exact 9-task/12-edge/47-item structure, without replacing prior assignments.

No cluster hostname was guessed: the route came from the captured portal adapter
and previously tested workspace DNS. No browser, login popup, global debug
change or unrelated flow overwrite was required.

## Logical tasks and boundaries

These are the **persisted native tasks**. Connectors express logical
relationships; they do not create data connections or schedule jobs.

| Task | Recommended type | Actual item count | Responsibility |
|---|---|---:|---|
| Oracle references | Mirror data | 2 | Reference mirror and its SQL endpoint |
| Salesforce BPS CRM | Get data | 25 | Whole native CRM solution family; 24 artifacts grouped, native launcher move gated |
| RTI transactions | Track data | 4 | Eventstream relay and Eventhouse/KQL |
| Raw | Store data | 3 | Source trace, physical event ingress and processing |
| Silver conformance | Prepare data | 3 | Validated current business state |
| Warehouse Gold business domains | Store data | 1 | Catalogue, offers, audiences, sales, playback, marketing |
| Ontology v2 | General | 4 | Gold-backed business context and native graph family |
| Cockpit Apps | Develop data | 4 | App, operational SQL, endpoint and trusted functions |
| Flixy | General | 1 | Native Data Agent using Gold and the ontology-owned graph |
| **Total** | | **47** | |

| Native task | Actual task ID |
|---|---|
| Oracle references | `<ORACLE_REFERENCES_TASK_ID>` |
| Salesforce BPS CRM | `<SALESFORCE_BPS_CRM_TASK_ID>` |
| RTI transactions | `<RTI_TRANSACTIONS_TASK_ID>` |
| Raw | `<RAW_TASK_ID>` |
| Silver conformance | `<SILVER_CONFORMANCE_TASK_ID>` |
| Warehouse Gold business domains | `<WAREHOUSE_GOLD_BUSINESS_DOMAINS_TASK_ID>` |
| Ontology v2 | `<ONTOLOGY_V2_TASK_ID>` |
| Cockpit Apps | `<COCKPIT_APPS_TASK_ID>` |
| Flixy | `<FLIXY_TASK_ID>` |

The twelve saved connectors are:

1. Oracle references → Raw: mirrored-reference shortcuts.
2. Salesforce BPS CRM → Raw: qualified MSFlix-keyed CRM handoff.
3. RTI transactions → Raw: KQL native OneLake → physical materialization.
4. Raw → Silver conformance: validation, sequence and identity contract.
5. Silver conformance → Warehouse Gold: publication-gated load.
6. Warehouse Gold → Ontology v2: business facts and relationship junctions.
7. Warehouse Gold → Cockpit Apps: actual Warehouse analytics reads.
8. Ontology v2 → Cockpit Apps: instance-qualified Business Graph.
9. Cockpit Apps → RTI transactions: committed operational outbox.
10. Warehouse Gold → Flixy: native Warehouse source.
11. Ontology v2 → Flixy: its actual native graph source.
12. Flixy → Cockpit Apps: read-only conversation.

Source and execution boundaries remain explicit in [ARCHITECTURE.md](ARCHITECTURE.md).
Automatic propagation reached 13,458 event IDs and 1,003 Gold order lines.
SAP and Planning do not appear as deployed tasks.

## Real folder IDs and placements

Native children were moved only by the documented parent move operation.
No independent SQL-endpoint, KQL-child or Ontology-child move was attempted.

| Real folder | Folder ID | Physical items |
|---|---|---:|
| `01 Oracle References` | `<ORACLE_REFERENCES_FOLDER_ID>` | 2 |
| `02 Salesforce BPS` | `<SALESFORCE_BPS_FOLDER_ID>` | 24 |
| `03 RTI Transactions` | `<RTI_TRANSACTIONS_FOLDER_ID>` | 4 |
| `04 Raw` | `<RAW_FOLDER_ID>` | 3 |
| `05 Silver Conformance` | `<SILVER_CONFORMANCE_FOLDER_ID>` | 3 |
| `06 Gold Business Domains` | `<GOLD_BUSINESS_DOMAINS_FOLDER_ID>` | 1 |
| `07 Ontology v2` | `<ONTOLOGY_V2_FOLDER_ID>` | 4 |
| `08 Cockpit` | `<COCKPIT_FOLDER_ID>` | 4 |
| `09 Flixy` | `<FLIXY_FOLDER_ID>` | 1 |

The user explicitly authorized extending the organization to native BPS and
cockpit parents. Native jobs use unchanged item IDs and display names; the BPS
owner confirmed no folder-sensitive operation or concurrent move. Folder moves
alter navigation, not source names, business definitions, connections or IDs.

## Every actual item and its logical task

This table records the physical public item IDs. Native assignment DTOs were
persisted/read back for all 47 items; portal identities use the captured
artifact-type adapters. Extended folder readback completed at
**2026-10-07 20:01 UTC**; graph/assignment proof is recorded separately below.

### Oracle references — 2

| Item | Type | Actual item ID |
|---|---|---|
| `MSFlix_OracleMirror` | MirroredDatabase | `<ORACLE_MIRROR_ID>` |
| `MSFlix_OracleMirror` | SQLEndpoint | `<ORACLE_MIRROR_SQL_ENDPOINT_ID>` |

### Salesforce BPS CRM — 25

All names and IDs below were preserved. The 24 standard artifacts are now in
`02 Salesforce BPS`; only the unsupported native solution launcher remains at
root. BPS's own Bronze/Silver/Gold are a native CRM subsystem, not the
cross-business Raw/Silver/Warehouse stages.

| Item | Type | Actual item ID |
|---|---|---|
| `MSFlix` | Microsoft.WaaS.BusinessProcessSolutions | `<CRM_BPS_ITEM_ID>` |
| `MSFlixSalesforceSQLdb` | SQLDatabase | `<MSFLIXSALESFORCESQLDB_SQLDATABASE_ID>` |
| `MSFlixSalesforceSQLdb` | SQLEndpoint | `<MSFLIXSALESFORCESQLDB_SQLENDPOINT_ID>` |
| `bps_bronze_<CRM_SYSTEM_SUFFIX>` | Lakehouse | `<BPS_BRONZE_LAKEHOUSE_ID>` |
| `bps_bronze_<CRM_SYSTEM_SUFFIX>` | SQLEndpoint | `<BPS_BRONZE_SQLENDPOINT_ID>` |
| `bps_env_<CRM_SYSTEM_SUFFIX>` | Environment | `<BPS_ENV_ENVIRONMENT_ID>` |
| `bps_gold_<CRM_SYSTEM_SUFFIX>` | Lakehouse | `<BPS_GOLD_LAKEHOUSE_ID>` |
| `bps_gold_<CRM_SYSTEM_SUFFIX>` | SQLEndpoint | `<BPS_GOLD_SQLENDPOINT_ID>` |
| `bps_log_collector_pipeline_<CRM_SYSTEM_SUFFIX>` | DataPipeline | `<BPS_LOG_COLLECTOR_PIPELINE_DATAPIPELINE_ID>` |
| `bps_metadata_db_<CRM_SYSTEM_SUFFIX>` | SQLDatabase | `<BPS_METADATA_DB_SQLDATABASE_ID>` |
| `bps_metadata_db_<CRM_SYSTEM_SUFFIX>` | SQLEndpoint | `<BPS_METADATA_DB_SQLENDPOINT_ID>` |
| `bps_nb_log_collector_<CRM_SYSTEM_SUFFIX>` | Notebook | `<BPS_NB_LOG_COLLECTOR_NOTEBOOK_ID>` |
| `bps_sf_fact_processing_child_pipeline_<CRM_SYSTEM_SUFFIX>` | DataPipeline | `<BPS_SF_FACT_PROCESSING_CHILD_PIPELINE_DATAPIPELINE_ID>` |
| `bps_sf_get_salesforce_data_<CRM_SYSTEM_SUFFIX>` | DataPipeline | `<BPS_SF_GET_SALESFORCE_DATA_DATAPIPELINE_ID>` |
| `bps_sf_nb_b2s_dimension_<CRM_SYSTEM_SUFFIX>` | Notebook | `<BPS_SF_NB_B2S_DIMENSION_NOTEBOOK_ID>` |
| `bps_sf_nb_s2g_dimension_<CRM_SYSTEM_SUFFIX>` | Notebook | `<BPS_SF_NB_S2G_DIMENSION_NOTEBOOK_ID>` |
| `bps_sf_nb_s2g_fact_<CRM_SYSTEM_SUFFIX>` | Notebook | `<BPS_SF_NB_S2G_FACT_NOTEBOOK_ID>` |
| `bps_sf_nb_table_checkpoint_update_<CRM_SYSTEM_SUFFIX>` | Notebook | `<BPS_SF_NB_TABLE_CHECKPOINT_UPDATE_NOTEBOOK_ID>` |
| `bps_sf_orchestration_pipeline_b2s_processing_<CRM_SYSTEM_SUFFIX>` | DataPipeline | `<BPS_SF_ORCHESTRATION_PIPELINE_B2S_PROCESSING_DATAPIPELINE_ID>` |
| `bps_sf_orchestration_pipeline_s2g_dimension_processing_<CRM_SYSTEM_SUFFIX>` | DataPipeline | `<BPS_SF_ORCHESTRATION_PIPELINE_S2G_DIMENSION_PROCESSING_DATAPIPELINE_ID>` |
| `bps_sf_orchestration_pipeline_s2g_fact_processing_<CRM_SYSTEM_SUFFIX>` | DataPipeline | `<BPS_SF_ORCHESTRATION_PIPELINE_S2G_FACT_PROCESSING_DATAPIPELINE_ID>` |
| `bps_sf_populate_salesforce_tables_metadata_<CRM_SYSTEM_SUFFIX>` | DataPipeline | `<BPS_SF_POPULATE_SALESFORCE_TABLES_METADATA_DATAPIPELINE_ID>` |
| `bps_sf_salesforce_data_pull_<CRM_SYSTEM_SUFFIX>` | DataPipeline | `<BPS_SF_SALESFORCE_DATA_PULL_DATAPIPELINE_ID>` |
| `bps_silver_<CRM_SYSTEM_SUFFIX>` | Lakehouse | `<BPS_SILVER_LAKEHOUSE_ID>` |
| `bps_silver_<CRM_SYSTEM_SUFFIX>` | SQLEndpoint | `<BPS_SILVER_SQLENDPOINT_ID>` |

The public BPS item ID is `<CRM_BPS_ITEM_ID>`.
Its caller-supplied native portal identity is
`Microsoft.WaaS:<CRM_BPS_PORTAL_ITEM_ID>`, which is used in the
persisted Task Flow assignment. No new BPS item was created to make the IDs
match. The public move failure leaves the launcher at root, but does not prevent
its native task assignment.

### RTI transactions — 4

| Item | Type | Actual item ID |
|---|---|---|
| `MSFlixEventhouse` | Eventhouse | `<EVENTHOUSE_ID>` |
| `MSFlixEventhouse` | KQLDatabase | `<EVENTHOUSE_KQL_DATABASE_ID>` |
| `MSFlixEvents` | KQLDatabase | `<EVENTS_KQL_DATABASE_ID>` |
| `MSFlixIngress` | Eventstream | `<EVENTSTREAM_ID>` |

### Raw — 3

| Item | Type | Actual item ID |
|---|---|---|
| `MSFlixRaw` | Lakehouse | `<RAW_LAKEHOUSE_ID>` |
| `MSFlixRaw` | SQLEndpoint | `<RAW_SQL_ENDPOINT_ID>` |
| `MSFlixRawProcessing` | Notebook | `<RAW_NOTEBOOK_ID>` |

### Silver conformance — 3

| Item | Type | Actual item ID |
|---|---|---|
| `MSFlixSilver` | Lakehouse | `<SILVER_LAKEHOUSE_ID>` |
| `MSFlixSilver` | SQLEndpoint | `<SILVER_SQL_ENDPOINT_ID>` |
| `MSFlixSilverProcessing` | Notebook | `<SILVER_NOTEBOOK_ID>` |

### Warehouse Gold business domains — 1

| Item | Type | Actual item ID |
|---|---|---|
| `MSFlixGold` | Warehouse | `<WAREHOUSE_ID>` |

### Ontology v2 — 4

| Item | Type | Actual item ID |
|---|---|---|
| `MSFlixBusiness` | Ontology | `<ONTOLOGY_ID>` |
| `MSFlixBusiness_eh_<ONTOLOGY_ID_COMPACT>` | Eventhouse | `<ONTOLOGY_EVENTHOUSE_ID>` |
| `MSFlixBusiness_eh_<ONTOLOGY_ID_COMPACT>` | KQLDatabase | `<ONTOLOGY_KQL_DATABASE_ID>` |
| `MSFlixBusiness_graph_<ONTOLOGY_ID_COMPACT>` | GraphModel | `<GRAPH_MODEL_ID>` |

### Cockpit Apps — 4

| Item | Type | Actual item ID |
|---|---|---|
| `MSFlix Business Control` | AppBackend | `<APP_ITEM_ID>` |
| `MSFlix Business Control` | SQLDatabase | `<APP_SQL_ITEM_ID>` |
| `MSFlix Business Control` | SQLEndpoint | `<APP_SQL_ENDPOINT_ID>` |
| `MSFlix Business Control` | UserDataFunction | `<APP_UDF_ITEM_ID>` |

### Flixy — 1

| Item | Type | Actual item ID |
|---|---|---|
| `Flixy` | DataAgent | `<DATA_AGENT_ID>` |

## Reproducible bounded script and evidence

`scripts/workspace_taskflow.py` requires explicit approved tenant, subscription,
workspace and capacity parameters. It verifies the target, lists paginated
items/folders and can deploy/read back the **actual native Task Flow**.

```powershell
py -3 scripts\workspace_taskflow.py --tenant <tenant> --subscription <subscription> `
  --workspace <workspace> --capacity-name <capacity-name> --require-taskflow
```

`--require-taskflow` returns **0 only when the native graph and all exact item
assignments are present**, otherwise exit 2. An inventory-only run does not
claim graph completion.

Add `--deploy-taskflow` to idempotently upsert the graph. Existing native flow
state is backed up, stable task IDs and user-adjusted locations are preserved,
and updates use the retrieved ETag. First creation requires the observed
`--bps-portal-item-id`; subsequent runs can retain its already-saved native
identity. Unrelated canvases are not replaced.
Unrecognized existing tasks/connectors or any lost assignment now stop an update
instead of silently replacing it. Flixy's task is included only when its actual
native Data Agent is present.

`--organize-folders` opt-in uses only documented create-folder and native
parent-move operations. It moves positively owned root items. The additionally
authorized `--include-native-groups` includes native BPS/cockpit parents and
preserves automatic child moves. It does not delete or flatten an existing
folder hierarchy. All Fabric calls
carry `x-ms-fabric-skill: spark-cli`. There are no deletes or renames.

Ignored `.state/workspace-taskflow.json` preserves the actual folder operations
and readback. A subsequent mapping-only refresh may be stored separately as
`.state/workspace-taskflow-mapping.json`, preserving the mutation proof.
The extended organization readback is
`.state/taskflow/full-folder-organization.json`; public portal bundle evidence
is also ignored under `.state/taskflow/`.

Native execution proof in that ignored directory:

- `native-taskflow-backup.json`: original empty native flow list.
- `native-taskflow-create-proof.json`: actual 201 response, resource URI and ETag.
- `native-taskflow-before-assignments.json`: pre-update state.
- `native-taskflow-item-bindings.json`: all 46 public/native identity bindings.
- `native-taskflow-assignment-write-proof.json`: ETag-protected 200 update.
- `native-taskflow-final-readback.json`: exact saved 8-task/9-edge/46-item graph.
- `flixy-final-readback.json`: exact saved 9-task/12-edge/47-item extension.

Public item types and portal identities differ for several native workloads.
The captured adapters include `SynapseNotebook`, `Pipeline`, `SQLDbNative`,
`SqlAnalyticsEndpoint`, `KustoDatabase`, `KustoEventHouse`, `EventStream`,
`MountedRelationalDatabase`, `FunctionSet` and `GraphIndex`. API names were not
blindly used as frontend identity prefixes.

## Official references checked

- [Task Flow overview and logical connectors](https://learn.microsoft.com/en-us/fabric/fundamentals/task-flow-overview)
- [Portal task/item assignment and export limitations](https://learn.microsoft.com/en-us/fabric/fundamentals/task-flow-work-with)
- [Official Fabric CLI commands](https://microsoft.github.io/fabric-cli/commands/)
- [List physical items](https://learn.microsoft.com/en-us/rest/api/fabric/core/items/list-items)
- [List folders](https://learn.microsoft.com/en-us/rest/api/fabric/core/folders/list-folders)
- [Create folder, public preview](https://learn.microsoft.com/en-us/rest/api/fabric/core/folders/create-folder)
- [Native parent/child move](https://learn.microsoft.com/en-us/rest/api/fabric/core/items/move-item)
