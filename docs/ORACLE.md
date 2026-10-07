# Oracle references: private source → mirror → Raw

**Qualified on 7 October 2026.** This is the completed reference-data branch,
not a snapshot dressed up as CDC.

## Physical path

`msflix-oracle-vm` (`10.60.1.4`, Singapore) → dedicated Windows gateway
(`10.60.2.4`) → `MSFlix_OracleMirror` → five shortcuts in
`MSFlixRaw.DEMO_DW`.

| Component | Actual identifier |
|---|---|
| Mirror | `f8e15a9a-ee3a-4e94-92eb-e28b3b4b7584` |
| Mirror SQL endpoint | `02dc7f01-2224-4ab8-8504-16edc04189e5` |
| Raw Lakehouse | `a37f4d51-ae84-4a46-880e-bb23d33fbd03` |
| MSFlix Oracle Gateway Fabric | `6db3385a-1324-407d-9c1a-d0199b6cc329` |
| Dedicated Oracle connection | `65ff2bca-2bc4-464e-bbdc-6718d746a1dd` |

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

- Demo Oracle Gateway: `c7d59606-b2ad-4653-98e2-a3e858075e37`.
- Demo Oracle Connection: `2639bfce-20d0-44e3-b9d5-23d3d0287516`.

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

## Implementation and references

- `sources/oracle/Deploy-ReferenceMirror.ps1`
- `sources/oracle/Generate-ReferenceMigration.ps1`
- `sources/oracle/Register-Gateway.ps1`
- `sources/oracle/Test-PrivatePaths.ps1`
- `scripts/verify_oracle_mirror.py`
- `scripts/expand_catalog.py`, `data/catalog.json`
- [Oracle mirroring in Fabric](https://learn.microsoft.com/en-us/fabric/database/mirrored-database/oracle)
- Upstream [oracletofabric](https://github.com/fredgis/oracletofabric);
  retained MIT license at `sources/oracle/reference/LICENSE`.
