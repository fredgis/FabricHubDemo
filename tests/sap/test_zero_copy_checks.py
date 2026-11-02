"""Parities use declared native SQL types, never guess identifier padding."""
import unittest
from decimal import Decimal
from datetime import date, datetime
from sources.sap import zero_copy_checks as checks


class CheckTests(unittest.TestCase):
    def test_parity_native_numeric_representation_and_extra_metadata(self):
        old = [{'FISCALYEAR': '2026', 'ITEM': '000010', 'code': '001', 'amount': Decimal('12.00'), 'day': date(2026,11,30)}]
        new = [{'FISCALYEAR': 2026, 'ITEM': 10, 'code': '001', 'amount': Decimal('12.0'), 'day': '2026-11-30', '_key_native': 9}]
        types = {'FISCALYEAR': 'int', 'ITEM': 'int', 'code': 'varchar', 'amount': 'decimal', 'day': 'date'}
        self.assertEqual(checks.compare(old, new, types), {'equal': True, 'old_rows': 1, 'new_rows': 1})


    def test_empty_comparison_contract_is_rejected(self):
        with self.assertRaises(ValueError):
            checks.compare([{'amount': 1}], [{'amount': 999}], {})

    def test_unknown_contract_is_rejected_even_without_nonnull_rows(self):
        for kind in ('decimla', '', None, 1):
            for old, new in [([], []), ([{'x': None}], [{'x': None}]),
                             ([{'x': 1}], [{'x': True}])]:
                with self.subTest(kind=kind, old=old):
                    with self.assertRaises((ValueError, TypeError)):
                        checks.compare(old, new, {'x': kind})

    def test_exact_decimal_rejects_inexact_nonfinite_or_malformed_values(self):
        invalid = [0.1, 1.0, True, False, float('inf'), float('nan'),
                   Decimal('Infinity'), Decimal('-Infinity'), Decimal('NaN'), Decimal('sNaN'),
                   'Infinity', 'NaN', '1_0', ' 1', '1 ', '', '1,0', '\u0661']
        for kind in ('decimal', 'numeric'):
            for value in invalid:
                for old, new in [(value, Decimal('0.1')), (Decimal('0.1'), value)]:
                    with self.subTest(kind=kind, value=value, old=old):
                        with self.assertRaises((ValueError, TypeError)):
                            checks.compare([{'x': old}], [{'x': new}], {'x': kind})

    def test_exact_decimal_preserves_precision_and_legacy_numeric_strings(self):
        for kind in ('decimal', 'numeric'):
            for old, new in [('000012.00', Decimal('12')), ('+.125', Decimal('0.125')),
                             ('-12.5e-2', Decimal('-0.125')), (12, Decimal('12.00')),
                             ('999999999999999999999999999999999999.01',
                              Decimal('999999999999999999999999999999999999.01'))]:
                with self.subTest(kind=kind, old=old):
                    self.assertTrue(checks.compare([{'x': old}], [{'x': new}], {'x': kind})['equal'])
            self.assertFalse(checks.compare(
                [{'x': Decimal('999999999999999999999999999999999999.01')}],
                [{'x': Decimal('999999999999999999999999999999999999.02')}], {'x': kind})['equal'])

    def test_integer_contract_requires_finite_integral_nonboolean_values(self):
        for kind in ('int', 'bigint', 'smallint', 'tinyint'):
            for value in ('1.5', Decimal('1.5'), 1.5, float('inf'), float('nan'),
                          Decimal('Infinity'), Decimal('NaN'), 'NaN', True, False):
                for old, new in [(value, 1), (1, value)]:
                    with self.subTest(kind=kind, value=value, old=old):
                        with self.assertRaises((ValueError, TypeError)):
                            checks.compare([{'x': old}], [{'x': new}], {'x': kind})
            for value in ('000010', '10.00', Decimal('10.0'), 10, 10.0):
                with self.subTest(kind=kind, value=value):
                    self.assertTrue(checks.compare([{'x': value}], [{'x': 10}], {'x': kind})['equal'])

    def test_float_contract_rejects_nonfinite_or_non_numeric_values(self):
        for kind in ('float', 'real'):
            for value in (float('inf'), float('-inf'), float('nan'), Decimal('Infinity'),
                          Decimal('NaN'), 'NaN', 'Infinity', True, '1_0'):
                for old, new in [(value, 1.0), (1.0, value)]:
                    with self.subTest(kind=kind, value=value, old=old):
                        with self.assertRaises((ValueError, TypeError)):
                            checks.compare([{'x': old}], [{'x': new}], {'x': kind})

    def test_float_contract_preserves_actual_binary_value_without_rounding_exact_values(self):
        for kind in ('float', 'real'):
            self.assertTrue(checks.compare([{'x': '001.5'}], [{'x': 1.5}], {'x': kind})['equal'])
            self.assertTrue(checks.compare([{'x': Decimal.from_float(0.1)}], [{'x': 0.1}],
                                           {'x': kind})['equal'])
            self.assertFalse(checks.compare([{'x': Decimal('0.1')}], [{'x': 0.1}], {'x': kind})['equal'])
            self.assertFalse(checks.compare([{'x': 9007199254740993}],
                                            [{'x': 9007199254740992.0}], {'x': kind})['equal'])

    def test_character_contracts_require_literal_strings(self):
        for kind in ('char', 'varchar', 'nchar', 'nvarchar'):
            for value in (1, True, False, 1.0, Decimal('1'), b'1', date(2026, 11, 30)):
                for old, new in [(value, '1'), ('1', value)]:
                    with self.subTest(kind=kind, value=value, old=old):
                        with self.assertRaises((ValueError, TypeError)):
                            checks.compare([{'x': old}], [{'x': new}], {'x': kind})
            with self.assertRaises((ValueError, TypeError)):
                checks.compare([{'x': 1}], [{'x': True}], {'x': kind})
            for old, new in [('001', '1'), ('A', 'a'), ('A ', 'A'), ('12.0', '12')]:
                with self.subTest(kind=kind, old=old, new=new):
                    self.assertFalse(checks.compare([{'x': old}], [{'x': new}], {'x': kind})['equal'])
            self.assertTrue(checks.compare([{'x': ' 001 '}], [{'x': ' 001 '}], {'x': kind})['equal'])

    def test_date_contract_parses_iso_dates_without_accepting_datetimes(self):
        for value in (datetime(2026, 11, 30), '2026-11-30T00:00:00', '2026-02-30',
                      '30/11/2026', '2026-11-30 ', '', 20261130, True):
            for old, new in [(value, date(2026, 11, 30)), (date(2026, 11, 30), value)]:
                with self.subTest(value=value, old=old):
                    with self.assertRaises((ValueError, TypeError)):
                        checks.compare([{'x': old}], [{'x': new}], {'x': 'date'})
        for value in ('2026-11-30', '20261130', date(2026, 11, 30)):
            with self.subTest(value=value):
                self.assertTrue(checks.compare([{'x': value}], [{'x': date(2026, 11, 30)}],
                                               {'x': 'date'})['equal'])
        self.assertFalse(checks.compare([{'x': '2026-11-30'}], [{'x': date(2026, 12, 1)}],
                                        {'x': 'date'})['equal'])

    def test_duplicates_nulls_characters_and_missing_columns_are_not_hidden(self):
        contract = {'code': 'varchar', 'amount': 'decimal'}
        row = {'code': '001', 'amount': None}
        self.assertFalse(checks.compare([row], [row, row], contract)['equal'])
        self.assertFalse(checks.compare([row], [{'code': '1', 'amount': None}], contract)['equal'])
        self.assertFalse(checks.compare([row], [{'code': '001', 'amount': 0}], contract)['equal'])
        with self.assertRaises(KeyError):
            checks.compare([row], [{'code': '001'}], contract)
        self.assertTrue(checks.compare([row, {'code': 'Z', 'amount': 1}],
                                       [{'code': 'Z', 'amount': 1}, row], contract)['equal'])


    def test_legacy_numc_contract_is_optional_but_strict_when_declared(self):
        import inspect
        self.assertIn('legacy_numc_widths', inspect.signature(checks.compare).parameters,
                      'Missing opt-in legacy NUMC domain validation')
        for invalid in ('2026e0', '1.0', '+1', '202', '02026', '\u0662\u0660\u0662\u0666',
                        ' 026', '2026 ', '', 2026, True):
            with self.subTest(invalid=invalid):
                with self.assertRaises((ValueError, TypeError)):
                    checks.compare([{'year': invalid}], [{'year': 2026}], {'year': 'int'},
                                   legacy_numc_widths={'year': 4})
        self.assertTrue(checks.compare(
            [{'year': '2026', 'item': '000010', 'literal': '001'}],
            [{'year': 2026, 'item': 10, 'literal': '001'}],
            {'year': 'int', 'item': 'int', 'literal': 'varchar'},
            legacy_numc_widths={'year': 4, 'item': 6})['equal'])
        self.assertTrue(checks.compare([{'year': None}], [{'year': None}], {'year':'int'},
                                       legacy_numc_widths={'year':4})['equal'])
        for token, number in [('2026e0', 2026), ('1.0', 1), ('+1', 1)]:
            self.assertTrue(checks.compare([{'n': token}], [{'n': number}], {'n': 'int'})['equal'])
        self.assertFalse(checks.compare([{'code':'001'}], [{'code':'1'}], {'code':'varchar'},
                                       legacy_numc_widths={'code':3})['equal'])
        for contract in ({'missing':4}, {'year':0}, {'year':-1}, {'year':True},
                         {'year':4.0}, {'year':'4'}):
            with self.subTest(contract=contract):
                with self.assertRaises((ValueError, TypeError)):
                    checks.compare([], [], {'year':'int'}, legacy_numc_widths=contract)


if __name__ == '__main__':
    unittest.main()
