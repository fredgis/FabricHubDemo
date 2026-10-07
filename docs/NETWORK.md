# MSFlix network boundary

## Verified deployed source network

| Resource | Confirmed state |
|---|---|
| Oracle VM | Private IP `10.60.1.4`, no public IP |
| Gateway VM | Private IP `10.60.2.4`, no public IP |
| Key Vault private endpoint | `10.60.3.4`, approved, private DNS integration |
| Azure Bastion | `msflix-bastion`, Developer SKU, deployed |
| Oracle Net | TCP 1521 from gateway subnet only, enforced by NSG |
| Public NAT IP | Outbound control-plane/package traffic; not inbound VM access |

## Workspace private endpoint

`infra/workspace-private-link.bicep` targets the specific MSFlix workspace through
`Microsoft.Fabric/privateLinkServicesForFabric@2024-06-01`, subresource `workspace`.
It reuses the private-endpoint subnet and integrates
`privatelink.fabric.microsoft.com`.

The deployed endpoint is `msflix-fabric-workspace-pe` in `rg-msflix-demo-sea`,
subscription `ce9dbfdd-c341-4e8d-a1fa-51617c74c3eb`, Southeast Asia.
Azure readback on 2026-10-07 confirms `Succeeded`, connection `Approved`,
subresource `workspace`, targeting `msflix-workspace-link`. It is distinct from
`msflix-keyvault-pe`.

[Open the Fabric workspace Private Endpoint in Azure](https://portal.azure.com/#@1e45d0cb-b0dd-408c-8806-58b447605e96/resource/subscriptions/ce9dbfdd-c341-4e8d-a1fa-51617c74c3eb/resourceGroups/rg-msflix-demo-sea/providers/Microsoft.Network/privateEndpoints/msflix-fabric-workspace-pe/overview).
The backing Fabric private link service is a hidden Azure resource; enable
**Show hidden resources** to see `msflix-workspace-link` in the resource group.

Private DNS records point the workspace API to `10.60.3.5` and OneLake to
`10.60.3.7`. On 2026-10-07 at 16:32 local time, the gateway VM resolved these
exact private addresses, reached both services on TCP 443 and Oracle
`10.60.1.4` on TCP 1521, and successfully read the authenticated MSFlix
workspace API through its private hostname. The gateway service was Running.
Evidence: `.state/network/private-paths-20261007.json` (ignored operational
state, no credentials). Gateway registration is a separate unfinished step;
workspace public access remains Allow.
`sources/oracle/Test-PrivatePaths.ps1` verifies exact DNS answers, TCP 443 to
the workspace and OneLake, TCP 1521 to Oracle, and optionally an authenticated
workspace API read. Pass access tokens only as protected VM Run Command
parameters, never as ordinary arguments or persisted evidence.

## Dedicated gateway registration and existing-environment isolation

The Windows VM and F16 capacity remain in Southeast Asia. Gateway service
registration is a separate setting: use the tenant's default Power BI region,
resolved with `Get-DataGatewayRegion | Where-Object IsDefaultPowerBIRegion`.
For this tenant, the default is `centralus`.

The first MSFlix gateway registration in `southeastasia` was discoverable with
the regional PowerShell cmdlet but returned `EntityNotFound` from the Fabric
gateway API. The dedicated VM is now registered as
`MSFlix Oracle Gateway Fabric`, ID `6db3385a-1324-407d-9c1a-d0199b6cc329`, in
`centralus`. Fabric API readback succeeded for its automation identity and the
deploying administrator. This does not relocate the Azure VM or capacity.

`Register-Gateway.ps1` and the guest registration script check the approved
subscription, resource group and exact VM. The guest verifies its identity
using Azure Instance Metadata before replacing any local registration.
Only `msflix-fabric-gateway-vm` is in scope.

The existing `Demo Oracle Gateway`
(`c7d59606-b2ad-4653-98e2-a3e858075e37`) and `Demo Oracle Connection`
(`2639bfce-20d0-44e3-b9d5-23d3d0287516`) belong to another environment.
Never reuse, rename, replace, reconfigure or delete them. The original
`oracletofabric` repository and its state are not deployment inputs to mutate;
MSFlix uses its isolated source copy and `%LOCALAPPDATA%\MSFlixOracle\state.json`.

## Oracle mirroring acceptance

The dedicated `MSFlix Oracle Connection`
(`65ff2bca-2bc4-464e-bbdc-6718d746a1dd`) uses the MSFlix gateway.
`MSFlix_OracleMirror` (`f8e15a9a-ee3a-4e94-92eb-e28b3b4b7584`) reached
Running with all five reference tables Replicating. Five shortcuts expose the
same tables in `MSFlixRaw`, schema `DEMO_DW`.

SQL reads verified these counts in both the mirror and Raw:

| Table | Rows |
|---|---:|
| REF_CONTENT | 305 |
| REF_PRICE_RULE | 2,440 |
| REF_OFFER | 2 |
| REF_DISTRIBUTOR | 1 |
| REF_TERRITORY | 4 |

Run the bounded live CDC acceptance separately:

```powershell
py -3 -m scripts.verify_oracle_mirror
```

It refuses an existing probe territory, temporarily inserts Germany (`DE`,
EUR) with reserved ID `973099`, changes its name to `Allemagne`, then removes
only that owned row. Each committed source mutation must be observed through
the actual mirror SQL endpoint. The baseline counts must be restored.
Successful evidence is written to ignored `.state/oracle-cdc-proof.json`.
The test does not use the other environment's original DIM/FACT CDC scripts.

**Private endpoint presence and public-access denial are separate controls.**
After endpoint approval, resolve the workspace FQDN from the gateway VM and prove
private connectivity before tightening the communication policy. Do not label a
hybrid/test workspace fully private.

Full denial needs supported item types and a private management/consumption path.
Current documented restrictions include Power BI semantic models and deployment
pipelines. Fabric Apps/native Functions and Ontology v2 access must also be
qualified before denying public access, so the deployed cockpit isn't silently
broken.

No tenant-wide Private Link or tenant-wide public-access block is applied to
unrelated workspaces. SAP and Planning remain future architecture only.

References:
- https://learn.microsoft.com/en-us/fabric/security/security-workspace-level-private-links-set-up
- https://learn.microsoft.com/en-us/fabric/security/security-workspace-level-private-links-support
