"""Pure, allowlisted one-time retirement plan for the old SAP copies.

This module cannot connect or execute SQL. The operator must qualify the native
source and replacement interfaces first, preserve a before-state, then execute
this plan in a single transaction and read back using a fresh connection.
Source BPS, non-SAP objects and sap_live are never deletion targets.
"""

TABLES = (
    'sap_company', 'sap_account', 'sap_period', 'sap_fiscal_year',
    'sap_fiscal_variant', 'sap_supplier', 'sap_product', 'sap_cost_center',
    'sap_profit_center', 'sap_gl_hierarchy', 'sap_cost_hierarchy',
    'sap_profit_hierarchy', 'sap_customer_link', 'sap_plan', 'sap_subscription',
    'sap_rights_contract', 'sap_rights_coverage', 'sap_billing_link',
    'sap_contract_charge', 'sap_invoice_item', 'sap_gl_line',
    'sap_operational_item', 'sap_publication', 'sap_writer_guard',
)
# The balances view depends on the two open-item views: drop it first.
VIEWS = (
    'sap_current_balances', 'sap_monthly_finance', 'sap_payment_journal',
    'sap_customer_invoice_item', 'sap_subscription_contract', 'sap_calendar',
    'sap_account_roles', 'sap_ar_open_item_current', 'sap_ap_open_item_current',
)


def plan(database, objects, dependencies):
    """Return exact DROP statements; no discovery, SQL or data mutation."""
    if database != 'MSFlixGold':
        raise ValueError('Retirement is approved only for MSFlixGold')
    expected = {**dict.fromkeys(TABLES, 'U'), **dict.fromkeys(VIEWS, 'V')}
    owned = [o for o in objects if o['schema_name'] == 'gold'
             and o['name'].startswith('sap_')]
    actual = {o['name']: o['type'].strip() for o in owned}
    if len(owned) != len(expected) or actual != expected:
        raise ValueError('Legacy catalog differs from exact reviewed allowlist')
    order = {name: index for index, name in enumerate(VIEWS + TABLES)}
    for dep in dependencies:
        target = dep['referenced_entity_name']
        # An unqualified reference can resolve to gold: only a known other
        # database/schema proves it unrelated to the reviewed legacy objects.
        if (dep['referenced_database_name'] not in (None, database)
                or dep['referenced_schema_name'] not in (None, 'gold')
                or target not in expected):
            continue
        consumer = dep['referencing_name']
        if (dep['referencing_schema'] != 'gold' or consumer not in order
                or order[consumer] >= order[target]):
            raise ValueError(f'Unsafe remaining dependency on gold.{target}')
    return ([f'DROP VIEW [gold].[{name}];' for name in VIEWS]
            + [f'DROP TABLE [gold].[{name}];' for name in TABLES])
