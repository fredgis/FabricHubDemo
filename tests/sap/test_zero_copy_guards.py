"""Offline guards must not conceal SQL body or identifier drift."""
import importlib.util
import unittest


class DefinitionTests(unittest.TestCase):
    def normalize(self, sql):
        self.assertIsNotNone(importlib.util.find_spec('sources.sap.zero_copy_guards'),
                             'Missing pure cutover definition guard')
        from sources.sap.zero_copy_guards import normalize_definition
        return normalize_definition(sql)

    def test_only_leading_ddl_header_is_equivalent(self):
        for kind in ('VIEW', 'FUNCTION'):
            tail = "[sap_live].[Case  ID] AS\nSELECT 'CREATE OR ALTER VIEW  -- literal' AS [x];"
            expected = 'CREATE ' + kind + ' ' + tail
            for header in ('CREATE ' + kind + ' ', 'CREATE   ' + kind + '\n',
                           '\n create\t or\nALTER  ' + kind.lower() + '\t'):
                with self.subTest(kind=kind, header=header):
                    self.assertEqual(self.normalize(header + tail), expected)

    def test_body_literals_comments_identifiers_and_trailing_bytes_are_preserved(self):
        sql = "CREATE OR ALTER VIEW [s].[CREATE OR ALTER  VIEW] AS\nSELECT 'a\r\nb  c; -- no trim' AS [x];\n"
        canonical = "CREATE VIEW " + sql.split('VIEW ', 1)[1]
        self.assertEqual(self.normalize(sql), canonical)
        for changed in (sql.replace('b  c', 'b c'), sql.replace('[x]', '[X]'),
                        sql.replace('\r\n', '\n'), sql.rstrip(),
                        sql.replace('AS\nSELECT', 'AS\n-- body comment\nSELECT')):
            with self.subTest(changed=changed):
                self.assertNotEqual(self.normalize(sql), self.normalize(changed))
        not_header = "SELECT 'CREATE OR ALTER VIEW [s].[v]'"
        self.assertEqual(self.normalize(not_header), not_header)


class BindingTests(unittest.TestCase):
    def test_approval_and_every_coordinate_must_match_passed_preflight(self):
        from sources.sap import zero_copy_guards as guards
        self.assertTrue(hasattr(guards, 'validate_binding'), 'Missing pure binding guard')
        saved = dict(status='preflight_passed', sql_sha256='a'*64,
                     workspace_id='workspace', warehouse_id='warehouse', source_id='bps',
                     database_name='MSFlixGold')
        actual = {k: saved[k] for k in ('workspace_id','warehouse_id','source_id','database_name')}
        guards.validate_binding(saved, 'a'*64, **actual)
        with self.assertRaises(ValueError):
            guards.validate_binding(saved, 'b'*64, **actual)
        with self.assertRaises(ValueError):
            guards.validate_binding(dict(saved, status='failed'), 'a'*64, **actual)
        for key in actual:
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    guards.validate_binding(saved, 'a'*64, **dict(actual, **{key: 'wrong'}))
                for missing in ('', None):
                    with self.assertRaises(ValueError):
                        guards.validate_binding(dict(saved, **{key: missing}), 'a'*64,
                                                **dict(actual, **{key: missing}))


if __name__ == '__main__':
    unittest.main()
