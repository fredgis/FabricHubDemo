# Workspace Task Flow and physical organization

**Workspace:** MSFlix, `d9c835a9-16d2-4997-9969-16cc4389a7c7`.
**Capacity:** active F16 `msflixf16sea`, Singapore;
`6e2bdf47-e6c5-4715-99ed-6c40461f59b7`.
The workspace description is blank.

## Execution result: actual native graph and item assignments

| Deliverable | Result |
|---|---|
| Physical inventory | **47 actual related items**, including the native Flixy Data Agent. |
| Safe organization | **9 real folders; 46 of 47 physical items placed and read back.** |
| Native organization | **24 BPS artifacts in `02 Salesforce BPS`, all 4 cockpit items in `08 Cockpit`**; native children followed their parents, all names/IDs/connections preserved. |
| Remaining folder gate | Native BPS solution `64a5f407-9261-4613-9095-3d72ce8c0dd3` remains at root: documented move returned **404 EntityNotFound**. |
| Actual Fabric Task Flow | **Persisted and read back: 9 tasks, 12 connectors and 47 unique native artifact assignments.** Flixy's extension preserved the original eight tasks and 46 assignments using ETag concurrency. |

A folder or Markdown diagram is not a Task Flow. This delivery now includes
the **actual saved native graph**, not just documentation artifacts.

| Native graph identity | Actual value |
|---|---|
| Name | `MSFlix Business Architecture` |
| Flow ID | `253cac16-938e-56ad-8461-b8e9d01f96d5` |
| Native resource ID | `6125bf4b-bd67-42d3-97ad-7bf0a17096d9` |
| Flixy extension ETag | `"0x8DF25122042A717"` |

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
  `https://d9c835a916d24997996916cc4389a7c7.zd9.w.api.fabric.microsoft.com`.
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
| Oracle references | `04ed5036-badd-5489-8fc4-528c4ce3c50e` |
| Salesforce BPS CRM | `3c343a2f-bc5b-56e0-bba6-3d6217ff25e7` |
| RTI transactions | `5749046c-0ca6-58ae-b6d0-cd861dfd3a69` |
| Raw | `e1470752-c089-53a7-884c-2a050f6ae8e4` |
| Silver conformance | `349b9864-c5c2-5265-9aed-19b64a386959` |
| Warehouse Gold business domains | `19c837bb-005a-5e53-8ab0-22394cc7cde1` |
| Ontology v2 | `c6d9479c-79f1-5a00-9e39-74b7941f96f5` |
| Cockpit Apps | `6d8cba5c-d5d2-58d5-af33-bb5346233922` |
| Flixy | `a5d3fed3-3d04-54ac-b2f6-5027a3385ffc` |

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
| `01 Oracle References` | `ffe17764-01f3-44d8-a5c5-b9b54d601fe7` | 2 |
| `02 Salesforce BPS` | `ca4d4423-c9b9-449b-9355-f834da5dd6ec` | 24 |
| `03 RTI Transactions` | `4d53cf49-fec0-449e-b5d7-7f739ac3ccdd` | 4 |
| `04 Raw` | `64c04e70-fb83-4fe5-9f94-b3b169d2fb71` | 3 |
| `05 Silver Conformance` | `63cb2eab-c2cc-497c-9a9a-20466e478d45` | 3 |
| `06 Gold Business Domains` | `97d45536-222a-4611-80ed-f6e4e114cfc8` | 1 |
| `07 Ontology v2` | `1a0a641e-bfe6-463c-adfb-3ed7a8bbe9f0` | 4 |
| `08 Cockpit` | `727513cb-e77d-43a1-91b7-1db1b6a331f1` | 4 |
| `09 Flixy` | `cc0976df-f747-4954-92c7-7967d27ec91d` | 1 |

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
| `MSFlix_OracleMirror` | MirroredDatabase | `f8e15a9a-ee3a-4e94-92eb-e28b3b4b7584` |
| `MSFlix_OracleMirror` | SQLEndpoint | `02dc7f01-2224-4ab8-8504-16edc04189e5` |

### Salesforce BPS CRM — 25

All names and IDs below were preserved. The 24 standard artifacts are now in
`02 Salesforce BPS`; only the unsupported native solution launcher remains at
root. BPS's own Bronze/Silver/Gold are a native CRM subsystem, not the
cross-business Raw/Silver/Warehouse stages.

| Item | Type | Actual item ID |
|---|---|---|
| `MSFlix` | Microsoft.WaaS.BusinessProcessSolutions | `64a5f407-9261-4613-9095-3d72ce8c0dd3` |
| `MSFlixSalesforceSQLdb` | SQLDatabase | `97fcca9f-79c7-4954-8bc9-6d343e9ce88d` |
| `MSFlixSalesforceSQLdb` | SQLEndpoint | `20df54dd-169b-4839-8578-a1cabc393272` |
| `bps_bronze_8fbe0076` | Lakehouse | `f9085d15-3994-45a8-ad81-b99fa28f9ad4` |
| `bps_bronze_8fbe0076` | SQLEndpoint | `37ab6fe0-1b87-4ddc-903c-cb5d423266a6` |
| `bps_env_8fbe0076` | Environment | `92e952ee-3b17-4c4a-877a-e5be28c19a6e` |
| `bps_gold_8fbe0076` | Lakehouse | `9577df9b-c737-4831-8123-67c94612de53` |
| `bps_gold_8fbe0076` | SQLEndpoint | `5ad76795-facf-48ae-b5c6-06bebd42189c` |
| `bps_log_collector_pipeline_8fbe0076` | DataPipeline | `340ed3ab-75fd-430b-b7ba-51cd8053a83e` |
| `bps_metadata_db_8fbe0076` | SQLDatabase | `0cef968c-cecf-4752-a330-b5aa29d287fc` |
| `bps_metadata_db_8fbe0076` | SQLEndpoint | `d8f20042-9e54-4d0a-b66b-0074205f5cb8` |
| `bps_nb_log_collector_8fbe0076` | Notebook | `4c02e076-ce3b-4bb9-b917-37df819dbe26` |
| `bps_sf_fact_processing_child_pipeline_8fbe0076` | DataPipeline | `b18e4f53-7e98-46b1-949f-36f1755f40d9` |
| `bps_sf_get_salesforce_data_8fbe0076` | DataPipeline | `f9152506-b520-4271-8f44-d57a507c59ad` |
| `bps_sf_nb_b2s_dimension_8fbe0076` | Notebook | `946487a8-2585-4ebb-9dc0-3671c149480e` |
| `bps_sf_nb_s2g_dimension_8fbe0076` | Notebook | `d71f6fe3-4542-4279-8680-599c2361266e` |
| `bps_sf_nb_s2g_fact_8fbe0076` | Notebook | `bb752239-a42f-4dfc-b527-ce6a110aa69e` |
| `bps_sf_nb_table_checkpoint_update_8fbe0076` | Notebook | `75de8f1b-33a7-476f-b2bc-835c34006afe` |
| `bps_sf_orchestration_pipeline_b2s_processing_8fbe0076` | DataPipeline | `fc20e5b0-434e-427d-a39b-d8efef738c1b` |
| `bps_sf_orchestration_pipeline_s2g_dimension_processing_8fbe0076` | DataPipeline | `a75dbec2-b421-46e2-b2ce-daeac7a2df40` |
| `bps_sf_orchestration_pipeline_s2g_fact_processing_8fbe0076` | DataPipeline | `9f698bc7-ce62-45aa-8d73-0388058fed6a` |
| `bps_sf_populate_salesforce_tables_metadata_8fbe0076` | DataPipeline | `2fba2a39-1187-4556-b685-961974c4f43c` |
| `bps_sf_salesforce_data_pull_8fbe0076` | DataPipeline | `aa27d311-4be5-4926-a497-8b94b92b347b` |
| `bps_silver_8fbe0076` | Lakehouse | `a4d465ac-9633-4e71-86ec-c92fafbac0fb` |
| `bps_silver_8fbe0076` | SQLEndpoint | `2b418c91-4663-4bc1-8fcd-b55ce401f996` |

The public BPS item ID is `64a5f407-9261-4613-9095-3d72ce8c0dd3`.
Its caller-supplied native portal identity is
`Microsoft.WaaS:9af07115-016f-43b9-9f3a-7edbb6c315c0`, which is used in the
persisted Task Flow assignment. No new BPS item was created to make the IDs
match. The public move failure leaves the launcher at root, but does not prevent
its native task assignment.

### RTI transactions — 4

| Item | Type | Actual item ID |
|---|---|---|
| `MSFlixEventhouse` | Eventhouse | `df0f578d-6aa2-4901-a55e-39cc37db03f3` |
| `MSFlixEventhouse` | KQLDatabase | `a40543f8-20ab-4580-9b6b-af1916d53af7` |
| `MSFlixEvents` | KQLDatabase | `2d7abed1-e7a7-4afd-9e35-4ab441423ac1` |
| `MSFlixIngress` | Eventstream | `5b40dec1-85db-4b2b-b8b1-1487155cfaed` |

### Raw — 3

| Item | Type | Actual item ID |
|---|---|---|
| `MSFlixRaw` | Lakehouse | `a37f4d51-ae84-4a46-880e-bb23d33fbd03` |
| `MSFlixRaw` | SQLEndpoint | `51959641-d08b-4689-aa1d-832e5abe9fbb` |
| `MSFlixRawProcessing` | Notebook | `f6cc6bb3-2f10-4cfa-a80d-ae041cb8c119` |

### Silver conformance — 3

| Item | Type | Actual item ID |
|---|---|---|
| `MSFlixSilver` | Lakehouse | `3fa1c0b6-89da-4ea4-85c1-009f8cada6c1` |
| `MSFlixSilver` | SQLEndpoint | `9c4c1b76-ce42-4a59-afc3-7e1a80867133` |
| `MSFlixSilverProcessing` | Notebook | `5c3716a8-6fac-421d-b418-0cc9dfe17ff4` |

### Warehouse Gold business domains — 1

| Item | Type | Actual item ID |
|---|---|---|
| `MSFlixGold` | Warehouse | `7eb1318d-e4b5-4bc4-ae12-6c3a46b1b7f5` |

### Ontology v2 — 4

| Item | Type | Actual item ID |
|---|---|---|
| `MSFlixBusiness` | Ontology | `3534d696-e727-45b3-9387-bbd155a82a52` |
| `MSFlixBusiness_eh_3534d696e72745b39387bbd155a82a52` | Eventhouse | `7cdd123e-a6fb-4b2e-9e1a-5e9248a4ea41` |
| `MSFlixBusiness_eh_3534d696e72745b39387bbd155a82a52` | KQLDatabase | `798cbb22-d6c7-43ce-b5c1-0dd99f9b87ff` |
| `MSFlixBusiness_graph_3534d696e72745b39387bbd155a82a52` | GraphModel | `1f368a35-95da-42a2-924d-ef4bb6bc9413` |

### Cockpit Apps — 4

| Item | Type | Actual item ID |
|---|---|---|
| `MSFlix Business Control` | AppBackend | `6ab44a5c-cb98-4445-aa00-670e6219abc7` |
| `MSFlix Business Control` | SQLDatabase | `cf1d77e0-b953-4de8-a0ca-38ae4aabe57c` |
| `MSFlix Business Control` | SQLEndpoint | `6ce7ed79-d134-404b-bf01-709c9f62bb7d` |
| `MSFlix Business Control` | UserDataFunction | `62904465-1297-4b4c-97aa-1e4228dcd54b` |

### Flixy — 1

| Item | Type | Actual item ID |
|---|---|---|
| `Flixy` | DataAgent | `664008b5-3de3-497b-b78f-14c4533147bd` |

## Reproducible bounded script and evidence

`scripts/workspace_taskflow.py` requires explicit approved tenant, subscription,
workspace and capacity parameters. It verifies the target, lists paginated
items/folders and can deploy/read back the **actual native Task Flow**.

```powershell
py -3 scripts\workspace_taskflow.py --tenant <tenant> --subscription <subscription> `
  --workspace <workspace> --capacity-name msflixf16sea --require-taskflow
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
