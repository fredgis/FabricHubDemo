# Oracle references: private source → mirror → Raw

**Qualified on 7 October 2026.** This is the completed reference-data branch,
not a snapshot dressed up as CDC.

## Physical path

`<oracle-vm>` (`<oracle-private-ip>`, Singapore) → dedicated Windows gateway
(`<gateway-private-ip>`) → `MSFlix_OracleMirror` → five shortcuts in
`MSFlixRaw.DEMO_DW`.

| Component | Actual identifier |
|---|---|
| Mirror | `<ORACLE_MIRROR_ID>` |
| Mirror SQL endpoint | `<ORACLE_MIRROR_SQL_ENDPOINT_ID>` |
| Raw Lakehouse | `<RAW_LAKEHOUSE_ID>` |
| <oracle-gateway-name> | `<ORACLE_GATEWAY_ID>` |
| Dedicated Oracle connection | `<ORACLE_CONNECTION_ID>` |

The mirror and its native SQL endpoint now reside in the real
`01 Oracle References` folder. Item names and IDs are unchanged.

## Business content and observed counts

| Oracle table | Role | Mirror **and** Raw rows |
|---|---|---:|
| `REF_CONTENT` | Sourced film metadata and provenance | 305 |
| `REF_PRICE_RULE` | Configured film/territory/commercial pricing | 2,440 |
| `REF_OFFER` | Commercial offer reference types | 2 |
| `REF_DISTRIBUTOR` | Distributor reference | 1 |
| `REF_TERRITORY` | Territory/currency reference | 4 |

The catalog combines Blender open films and Wikidata metadata. Artwork has its
own qualifying license; film metadata or artwork reuse does **not** establish
commercial distribution rights.

Reference offers support the rental/purchase business model. Actual order
amounts and entitlements come from the operational transaction, not a count of
reference prices. Rental start/play windows are explicit offer policies rather
than an assumed universal duration.

## CDC was actually observed

The bounded probe reserved territory ID `973099`, refused to overwrite any
existing probe, and committed these source changes:

1. Insert `DE / Germany / EUR`.
2. Update its name to `Allemagne`.
3. Delete only the owned row.

Each state appeared through the real mirror SQL endpoint. Baseline counts were
restored. The ignored `.state/oracle-cdc-proof.json` records
`live_success=true`, all three phases and completion at
**2026-10-07 15:35 UTC**.

The Raw tables are native mirror shortcuts, not independent copied snapshots.
Their visibility is qualified; downstream notebook/Gold publication is a
different acceptance boundary and must not be inferred merely from CDC success.

## Region and isolation: the important distinction

The Oracle VM, gateway VM and F16 remain in **Southeast Asia**. The gateway
service is registered in **centralus**, the tenant's default Power BI region.
The initial Southeast Asia registration was not recognized by the Fabric
gateway API; the tenant-default registration was recognized. This is gateway
service registration, **not a VM or data-capacity relocation**.

The following belong to another user environment and must never be reused,
renamed, reconfigured or deleted:

- <other-environment-gateway-name>: `<OTHER_ENVIRONMENT_GATEWAY_ID>`.
- <other-environment-connection-name>: `<OTHER_ENVIRONMENT_CONNECTION_ID>`.

Workspace private endpoint approval and authenticated private API access are
proved, but public access remains **Allow**. See [NETWORK.md](NETWORK.md);
do not describe the overall workspace as fully private.

## Rerunnable entry points

Source migrations are additive and target the dedicated MSFlix environment.
`sources/oracle/Deploy-ReferenceMirror.ps1` loads the catalog, registers the
dedicated gateway and configures the reference mirror. Do not rerun a destructive
installer to demonstrate a new transaction.

The already-completed CDC test can be rerun deliberately with cached approved
credentials and the ignored local deployment configuration:

```powershell
py -3 -m scripts.verify_oracle_mirror
```

It performs real bounded source writes. Use the saved proof for an ordinary
documentation review rather than generating new CDC traffic unnecessarily.

### Unicode-safe catalog updates

`Oracle-Literals.ps1` emits ASCII SQL using Oracle `UNISTR` for non-ASCII text.
This avoids dependence on the VM shell and SQL*Plus client encodings, while
preserving film names, apostrophes and attribution in the AL32UTF8 database.

On 8 October, 74 titles/attributions with damaged characters in the initial
mirror snapshot were replayed from the unchanged canonical catalog, using the
same content keys. The source and mirror then contained no replacement
characters. SQL endpoint metadata was refreshed after CDC before the repaired
native references were staged for Raw, Silver and Gold.

`Repair-CatalogEncoding.ps1` only targets the dedicated MSFlix subscription/VM.
Its default mode updates damaged source text; `-ReplayContentKeys` explicitly
re-emits selected reference rows when the source is correct but the initial
mirror copy needs a CDC replacement. It never resets the schema or changes
order identities, prices or existing environment resources.

## Implementation and references

- `sources/oracle/Deploy-ReferenceMirror.ps1`
- `sources/oracle/Generate-ReferenceMigration.ps1`
- `sources/oracle/Oracle-Literals.ps1`, `sources/oracle/Repair-CatalogEncoding.ps1`
- `sources/oracle/Register-Gateway.ps1`
- `sources/oracle/Test-PrivatePaths.ps1`
- `scripts/verify_oracle_mirror.py`
- `scripts/expand_catalog.py`, `data/catalog.json`
- [Oracle mirroring in Fabric](https://learn.microsoft.com/en-us/fabric/database/mirrored-database/oracle)
- Upstream [oracletofabric](https://github.com/<repository-owner>/oracletofabric);
  retained MIT license at `sources/oracle/reference/LICENSE`.
