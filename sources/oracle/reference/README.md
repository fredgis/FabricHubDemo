<p align="center">
  <img src="docs/assets/hero.svg" alt="Oracle to Fabric private replication demo" width="100%">
</p>

<p align="center">
  <code>PRIVATE VNET</code>&nbsp;&nbsp;
  <code>0 VM PUBLIC IPS</code>&nbsp;&nbsp;
  <code>LIVE ORACLE CDC</code>&nbsp;&nbsp;
  <code>SCHEMA-ENABLED LAKEHOUSE</code>
</p>

<p align="center">
  <a href="#architecture">Architecture</a> ·
  <a href="#run-the-demo">Run the demo</a> ·
  <a href="#connect-to-oracle">Connect to Oracle</a> ·
  <a href="#deploy-from-scratch">Deploy</a>
</p>

# Oracle to Fabric Demo

This repo deploys Oracle AI Database Free on a private Azure Linux VM and mirrors five tables into Microsoft Fabric. The Windows VM beside it runs the gateway service. It is not where you work with Oracle.

## Architecture

<p align="center">
  <a href="docs/architecture/rendered/00-deployed-architecture.svg">
    <img src="docs/architecture/rendered/00-deployed-architecture.png" alt="Deployed Oracle to Fabric architecture" width="100%">
  </a>
</p>

This is the deployed environment in `FGI-ORACLE`. Both VMs are private. Bastion handles administration, the Windows gateway reads Oracle on port `1521`, and outbound NAT carries the gateway traffic to Fabric.

| Location | Role |
| --- | --- |
| `demo-oracle-vm` | Oracle Linux 9.8, Oracle AI Database Free, SQL*Plus, data files and archive logs |
| `demo-fabric-gateway-vm` | Windows Server 2022, on-premises data gateway, managed Oracle provider |
| `DemoOracleMirror` | Fabric Mirrored Database receiving the snapshot and Oracle CDC |
| `DemoLakehouse` | Schema-enabled Lakehouse with five shortcuts under `Tables/DEMO_DW` |

<details>
<summary>Open the complete architecture pack</summary>

[Overview SVG](docs/architecture/rendered/00-deployed-architecture.svg) ·
[Overview PDF](docs/architecture/rendered/00-deployed-architecture.pdf) ·
[Context view](docs/architecture/rendered/01-context.png) ·
[Network view](docs/architecture/rendered/02-network-topology.png) ·
[Security view](docs/architecture/rendered/03-security-flows.png) ·
[Data flow](docs/architecture/rendered/04-data-flows.png)

</details>

## Run the demo

From PowerShell, in the repository root:

```powershell
.\tests\Invoke-DemoInsertScenario.ps1
```

The script inserts one row into `DEMO_DW.FACT_SALES`, archives the current redo log, waits for Fabric Mirroring, then confirms that the row reached `DemoLakehouse`.

Expected output:

```text
ORACLE_INSERTED=true
SALES_KEY=<generated-key>
WAITING_FOR_FABRIC=true
FABRIC_REPLICATED=true
FABRIC_TABLE=DEMO_DW.FACT_SALES
```

Use this for the demo. It needs no SSH session or portal work. Fabric can take several minutes to expose the new row, so the script waits for it.

### SQL rendering smoke test

This one is technically a test. It checks SQL*Plus, analytic functions, hierarchical row generation, `LISTAGG`, and `DBMS_RANDOM`. It also draws a sales chart and a random galaxy.

```powershell
.\tests\Invoke-DemoSqlFunTest.ps1
```

<details>
<summary>From Oracle SQL to Fabric Python</summary>

The same mirrored sales data, first rendered inside Oracle, then in a Fabric PySpark notebook.

<table>
  <tr>
    <th align="center">Oracle SQL*Plus</th>
    <th align="center">Fabric Notebook</th>
  </tr>
  <tr>
    <td align="center">
      <a href="docs/assets/oracle-sql-fun.png">
        <img src="docs/assets/oracle-sql-fun.png" alt="Oracle SQL sales chart and random galaxy output" width="360">
      </a>
    </td>
    <td align="center">
      <a href="docs/assets/fabric-notebook-fun.png">
        <img src="docs/assets/fabric-notebook-fun.png" alt="Fabric notebook rendering the mirrored sales chart and Python galaxy" width="360">
      </a>
    </td>
  </tr>
</table>

</details>

<details>
<summary>Run the two SQL statements directly</summary>

```sql
select lpad(store_key, 2, '0') || ' | ' || rpad('#', round(sum(sales_amount) / max(sum(sales_amount)) over () * 40), '#') as SALES_BY_STORE from DEMO_DW.FACT_SALES group by store_key order by store_key;
```

```sql
select listagg(case when star < 0.02 then '@' when star < 0.06 then '*' when star < 0.15 then '.' else ' ' end, '') within group (order by col_no) as GALAXY from (select ceil(level / 70) as row_no, mod(level - 1, 70) + 1 as col_no, dbms_random.value as star from dual connect by level <= 1400) group by row_no order by row_no;
```

</details>

## Connect to Oracle

For routine tests, do not open either VM. Run the insert scenario above.

When you want a real SQL*Plus session, connect **directly to `demo-oracle-vm` through Azure Bastion SSH**. The gateway VM is not a jump host. Open it through Bastion RDP only when you need to inspect the gateway service.

| Goal | Path |
| --- | --- |
| Insert a row and prove replication | Run `tests\Invoke-DemoInsertScenario.ps1` locally |
| Open an interactive Oracle shell | Bastion SSH to `demo-oracle-vm` |
| Inspect the Fabric gateway service | Bastion RDP to `demo-fabric-gateway-vm` |

### Your first Oracle session

When Bastion shows the Linux prompt:

```text
[demoadmin@demooracle ~]$
```

Run one command:

```bash
sudo demo-sqlplus
```

`ls` lists Linux files. It cannot show Oracle schemas or tables.

The helper opens Oracle as the local administrator and switches to `FREEPDB1`, where the demo data lives. Oracle calls the objects owned by one database user a schema. This demo uses the `DEMO_DW` schema.

You are inside Oracle when the prompt changes to:

```text
SQL>
```

Start with these commands:

```sql
-- Confirm the current pluggable database.
select sys_context('USERENV', 'CON_NAME') as container_name from dual;

-- List non-system schemas.
select username from dba_users where oracle_maintained = 'N' order by username;

-- List the five demo tables.
select table_name from all_tables where owner = 'DEMO_DW' order by table_name;

-- Show the columns and data types.
select column_id, column_name, data_type, data_length, nullable from all_tab_columns where owner = 'DEMO_DW' and table_name = 'FACT_SALES' order by column_id;

-- Count the sales rows.
select count(*) from DEMO_DW.FACT_SALES;

-- Read ten recent rows.
select SALES_KEY, DATE_KEY, CUSTOMER_KEY, PRODUCT_KEY, QUANTITY, SALES_AMOUNT from DEMO_DW.FACT_SALES order by SALES_KEY desc fetch first 10 rows only;
```

The table query returns `DIM_CUSTOMER`, `DIM_DATE`, `DIM_PRODUCT`, `DIM_STORE`, and `FACT_SALES`.

Every SQL statement above is on one line and ends with `;`. `exit` is a SQL*Plus command, so it is the only command below without one.

Leave Oracle with:

```sql
exit
```

<details>
<summary>Bastion login and SSH key</summary>

Export the DPAPI-protected deployment key:

```powershell
.\scripts\Export-DemoSshKey.ps1
```

Then open `demo-oracle-vm` in Azure Portal and select **Connect > Bastion**:

```text
Authentication: SSH private key from local file
Username:       demoadmin
Private key:    use the path printed by the script
```

After Bastion opens the Linux shell:

```bash
sudo demo-sqlplus
```

</details>

<details>
<summary>Insert one row manually and send it to Fabric</summary>

From the `SQL>` prompt:

```sql
insert into DEMO_DW.FACT_SALES (SALES_KEY, DATE_KEY, CUSTOMER_KEY, PRODUCT_KEY, STORE_KEY, QUANTITY, UNIT_PRICE, SALES_AMOUNT, UPDATED_AT) select to_number(to_char(systimestamp, 'YYYYMMDDHH24MISSFF3')), 20250102, 2, 2, 2, 1, 19.95, 19.95, sysdate from dual;
commit;
alter session set container=CDB$ROOT;
alter system archive log current;
alter session set container=FREEPDB1;
select SALES_KEY, SALES_AMOUNT, UPDATED_AT from DEMO_DW.FACT_SALES order by SALES_KEY desc fetch first 1 row only;
```

Fabric Mirroring picks up the archived redo log. You can query the same row in `DemoLakehouse` under `DEMO_DW.FACT_SALES`.

</details>

Delete the exported SSH key after the Bastion session starts:

```powershell
Remove-Item "$env:TEMP\demo-oracle-ssh.key"
```

## Deploy from scratch

Prerequisites:

- Azure CLI authenticated on the target tenant
- Azure Owner on the subscription
- Fabric Administrator or Power BI Administrator
- Cloud Application Administrator or Application Administrator when directory changes are required
- an existing `FGI-ORACLE` resource group
- an existing `FGI-ORACLE` Fabric workspace on active capacity
- Bicep and `sqlcmd` installed locally

Run the read-only preflight on its own when preparing a new workstation:

```powershell
.\scripts\Test-DemoPrerequisites.ps1 `
  -SubscriptionId $env:AZURE_SUBSCRIPTION_ID `
  -TenantId $env:AZURE_TENANT_ID
```

The full deployment runs the same preflight before creating infrastructure.

```powershell
$env:AZURE_SUBSCRIPTION_ID = '<subscription-id>'
$env:AZURE_TENANT_ID = '<tenant-id>'

.\scripts\Deploy-Demo.ps1 `
  -SubscriptionId $env:AZURE_SUBSCRIPTION_ID `
  -TenantId $env:AZURE_TENANT_ID `
  -RunCdcValidation
```

The script deploys Azure, installs Oracle, registers the gateway, creates the Fabric items, and validates the initial snapshot plus live CDC. You can run it again without creating a second environment.

No tenant ID, subscription ID, account, token, password, certificate, recovery key, or private key is stored in Git.

<details>
<summary>Issue 1 checks and recovery commands</summary>

| Check | Behavior |
| --- | --- |
| Azure CLI, Bicep, SSH and `sqlcmd` | The preflight stops immediately and prints the install command. For `sqlcmd`: `winget install --id Microsoft.Sqlcmd --exact --accept-source-agreements --accept-package-agreements --silent` |
| Azure subscription feature | Requires `Microsoft.Network/AllowBringYourOwnPublicIpAddress` to be `Registered` and prints the `az feature register`, `az feature show`, and `az provider register` commands when it is not |
| Fabric tenant settings | Checks both service principal settings and links directly to the Fabric admin portal when one is disabled |
| Microsoft Entra role | Requires Cloud Application Administrator or Application Administrator only when directory writes are still needed |
| PIM token refresh | The error prints `az logout`, `az login --tenant $env:AZURE_TENANT_ID --use-device-code`, and `az account set --subscription $env:AZURE_SUBSCRIPTION_ID` |
| Bastion reruns | Lists Bastion resources, checks the Azure CLI exit code, then creates or updates exactly one matching resource |
| Fabric gateway identity | The automation service principal registers, discovers, and administers the gateway and Fabric connection, with a bounded three-minute retry |
| Oracle network | Applies runtime and permanent `firewalld` rules, then tests Gateway VM to Oracle VM TCP `1521` before Fabric connection creation |
| CDC validation | Remains independently runnable with `.\tests\Invoke-DemoCdcValidation.ps1` and gives the exact `sqlcmd` install command when needed |

</details>

## Current deployment

| Area | Result |
| --- | --- |
| Azure | Private VNet, Bastion Developer, NAT egress, private Key Vault |
| Compute | Oracle Linux VM and Windows gateway VM, both without public IPs |
| Oracle | `DEMO_DW` star schema with four dimensions and `FACT_SALES` |
| Fabric | Connection, Mirrored Database, schema-enabled Lakehouse, five shortcuts |
| Validation | Initial snapshot, insert, update, delete, and repeatable live CDC |

<details>
<summary>Security and network details</summary>

- SSH, RDP, and Oracle Net have no inbound Internet path.
- Bastion Developer provides browser-based administration and still requires Azure authorization plus the VM credential.
- Oracle Net is allowed only from the gateway subnet.
- Key Vault public network access is disabled.
- The NAT public IP accepts no unsolicited inbound connection.
- The gateway and connection automation uses a dedicated service principal.
- The recorded deploying user receives `Admin` on `Demo Oracle Gateway` and `Owner` on `Demo Oracle Connection` for portal access.
- The local state stores only that user's Entra object ID. It does not store the user's name, UPN, token, or credentials.
- A rerun under a different user stops instead of replacing the recorded identity silently.
- Credentials are generated during deployment and stored in Key Vault plus local DPAPI-protected state.

</details>

<details>
<summary>Cost and Oracle Free limits</summary>

Persistent infrastructure costs about 71 EUR per month while the NAT Gateway, NAT public IP, Key Vault Private Endpoint, and managed disks remain deployed. VM compute and Fabric capacity can be stopped.

Oracle AI Database Free has no license fee under the [Oracle Free Use Terms](https://www.oracle.com/downloads/licenses/oracle-free-license.html). Its main limits are 2 CPUs, 2 GB of Oracle memory, 12 GB of user data, one installation per VM, no support, and no security patches.

</details>

<details>
<summary>More validation commands</summary>

```powershell
# Insert, update, and delete through live CDC
.\tests\Invoke-DemoCdcValidation.ps1

# Validate Azure isolation
.\tests\Validate-AzureDemo.ps1 `
  -SubscriptionId $env:AZURE_SUBSCRIPTION_ID
```

Expected CDC result:

```text
CDC_VALID=true
CDC_BASELINE=0|Consumer|1|25000
CDC_RESULT=1|CDC_LIVE|0|25000
```

</details>

<details>
<summary>Repository map</summary>

```text
infra/        Azure Bicep
scripts/      deployment, identity, and connection helpers
oracle/       Oracle installation, validation, and CDC scripts
fabric/       gateway and Fabric configuration
tests/        simple insert, SQL smoke test, and full end-to-end validation
docs/         architecture sources and rendered diagrams
```

</details>

<details>
<summary>Official documentation</summary>

- [Oracle AI Database Free](https://www.oracle.com/database/free/)
- [Oracle Free Use Terms](https://www.oracle.com/downloads/licenses/oracle-free-license.html)
- [Oracle Mirroring in Microsoft Fabric](https://learn.microsoft.com/en-us/fabric/mirroring/oracle)
- [Oracle Mirroring limitations](https://learn.microsoft.com/en-us/fabric/mirroring/oracle-limitations)
- [On-premises data gateway communication](https://learn.microsoft.com/en-us/data-integration/gateway/service-gateway-communication)
- [Create a schema-enabled Lakehouse](https://learn.microsoft.com/en-us/rest/api/fabric/lakehouse/items/create-lakehouse)
- [OneLake shortcuts](https://learn.microsoft.com/en-us/rest/api/fabric/core/onelake-shortcuts/create-shortcut)

</details>
