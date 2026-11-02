"""No SQL connection: validate the bounded destructive migration plan."""
import unittest
from sources.sap import retirement as r


class RetirementTests(unittest.TestCase):
    def inventory(self):
        return ([{'schema_name': 'gold', 'name': n, 'type': 'U'} for n in r.TABLES]
                + [{'schema_name': 'gold', 'name': n, 'type': 'V'} for n in r.VIEWS]
                + [{'schema_name': 'gold', 'name': 'fact_order_line', 'type': 'U'},
                   {'schema_name': 'sap_live', 'name': 'gl_line', 'type': 'V'}])

    def test_exact_24_tables_and_nine_views_only(self):
        plan = r.plan('MSFlixGold', self.inventory(), [])
        self.assertEqual(33, len(plan))
        self.assertEqual(24, sum(s.startswith('DROP TABLE') for s in plan))
        self.assertTrue(all('gold].[sap_' in s for s in plan))
        self.assertTrue(all('fact_order_line' not in s and 'sap_live' not in s for s in plan))


    def test_only_exact_approved_catalog_and_database_allowed(self):
        cases = [('OtherWarehouse', self.inventory()),
                 ('MSFlixGold', self.inventory()[1:]),
                 ('MSFlixGold', self.inventory() + [{'schema_name': 'gold', 'name': 'sap_unreviewed', 'type': 'U'}]),
                 ('MSFlixGold', self.inventory() + [self.inventory()[0]]),
                 ('MSFlixGold', [{**o, 'type': 'V'} if o['name'] == 'sap_company' else o for o in self.inventory()])]
        for db, objects in cases:
            with self.subTest(db=db, objects=objects):
                with self.assertRaises(ValueError):
                    r.plan(db, objects, [])


    def test_external_dependency_or_invalid_order_is_rejected(self):
        for schema, name, target in [('gold', 'other_consumer', 'sap_gl_line'),
                                     ('other', 'sap_monthly_finance', 'sap_gl_line'),
                                     ('gold', 'sap_account_roles', 'sap_current_balances')]:
            dependency = {'referencing_schema': schema, 'referencing_name': name,
                          'referenced_database_name': None, 'referenced_schema_name': 'gold',
                          'referenced_entity_name': target}
            with self.subTest(consumer=name, target=target):
                with self.assertRaises(ValueError):
                    r.plan('MSFlixGold', self.inventory(), [dependency])

    def test_unqualified_legacy_dependencies_must_still_be_safe(self):
        consumers = [('gold', 'non_sap_consumer', 'sap_company'),
                     ('other', 'sap_monthly_finance', 'sap_company'),
                     ('gold', 'sap_account_roles', 'sap_current_balances'),
                     ('gold', 'sap_writer_guard', 'sap_company')]
        for database in (None, 'MSFlixGold'):
            for schema, name, target in consumers:
                dependency = {'referencing_schema': schema, 'referencing_name': name,
                              'referenced_database_name': database,
                              'referenced_schema_name': None,
                              'referenced_entity_name': target}
                with self.subTest(database=database, consumer=name, target=target):
                    with self.assertRaisesRegex(ValueError, 'Unsafe remaining dependency'):
                        r.plan('MSFlixGold', self.inventory(), [dependency])

    def test_proven_unrelated_dependencies_do_not_block_retirement(self):
        for database, schema in [('OtherWarehouse', None), ('OtherWarehouse', 'gold'),
                                 (None, 'other'), ('MSFlixGold', 'other')]:
            dependency = {'referencing_schema': 'gold', 'referencing_name': 'non_sap_consumer',
                          'referenced_database_name': database, 'referenced_schema_name': schema,
                          'referenced_entity_name': 'sap_company'}
            with self.subTest(database=database, schema=schema):
                self.assertEqual(r.plan('MSFlixGold', self.inventory(), []),
                                 r.plan('MSFlixGold', self.inventory(), [dependency]))

    def test_internal_dependencies_in_drop_order_are_safe(self):
        dependency = {'referencing_schema': 'gold', 'referencing_name': 'sap_current_balances',
                      'referenced_database_name': None, 'referenced_schema_name': 'gold',
                      'referenced_entity_name': 'sap_ar_open_item_current'}
        plan = r.plan('MSFlixGold', self.inventory(), [dependency])
        self.assertLess(plan.index('DROP VIEW [gold].[sap_current_balances];'),
                        plan.index('DROP VIEW [gold].[sap_ar_open_item_current];'))


if __name__ == '__main__':
    unittest.main()
