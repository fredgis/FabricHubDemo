"""Pure multiset comparison for the declared legacy-to-native representation.

Only native numeric types normalize padded legacy NUMC strings. Character
identifiers are literal. Extra native metadata is excluded by an explicit
column/type contract supplied by the caller; missing fields are errors.
Contracts use lowercase SQL base type names. Native bit/datetime2 metadata
is outside this business-column contract and must be explicitly excluded.
"""
from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re


def _exact_decimal(value):
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, str)):
        raise TypeError('Exact numeric values require Decimal, int or numeric string')
    if isinstance(value, str) and not re.fullmatch(
            r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', value):
        raise ValueError('Malformed numeric string')
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError('Invalid exact numeric value') from exc
    if not number.is_finite():
        raise ValueError('Numeric values must be finite')
    return number


def compare(old, new, column_types, *, legacy_numc_widths=None):
    """Compare selected values and multiplicity, optionally validating old NUMC.

    Widths apply only to declared original legacy NUMC columns, before numeric
    conversion. Other numeric contracts retain their generic representations.
    """
    if not column_types:
        raise ValueError('An explicit nonempty business-column contract is required')
    supported = {'int', 'bigint', 'smallint', 'tinyint', 'decimal', 'numeric',
                 'float', 'real', 'date', 'char', 'varchar', 'nchar', 'nvarchar'}
    for key, kind in column_types.items():
        if not isinstance(kind, str) or kind not in supported:
            raise ValueError(f'Unsupported SQL type for {key}: {kind!r}')
    widths = {} if legacy_numc_widths is None else legacy_numc_widths
    for key, width in widths.items():
        if key not in column_types or type(width) is not int or width <= 0:
            raise ValueError(f'Invalid legacy NUMC width contract for {key}')
    def rows(values, legacy=False):
        result = []
        for row in values:
            projected = []
            for key, kind in column_types.items():
                value = row[key]
                if value is not None:
                    if legacy and key in widths:
                        if not isinstance(value, str) or len(value) != widths[key] or not re.fullmatch(r'[0-9]+', value):
                            raise ValueError(f'Invalid legacy NUMC value for {key}: expected {widths[key]} ASCII digits')
                    if kind in {'decimal', 'numeric'}:
                        value = _exact_decimal(value)
                    elif kind in {'int', 'bigint', 'smallint', 'tinyint', 'float', 'real'}:
                        # Preserve a float's actual binary value, never round an
                        # exact Decimal/int/string through float or str(float).
                        value = _exact_decimal(
                            Decimal.from_float(value) if isinstance(value, float) else value)
                        if kind not in {'float', 'real'} and value != value.to_integral_value():
                            raise ValueError('Integer values must be integral')
                    elif kind == 'date':
                        if isinstance(value, str):
                            value = date.fromisoformat(value)
                        elif isinstance(value, datetime) or not isinstance(value, date):
                            raise TypeError('Date values require a date or ISO date string')
                    elif not isinstance(value, str):
                        raise TypeError('Character values must be literal strings')
                projected.append(value)
            result.append(tuple(projected))
        return Counter(result)
    return {'equal': rows(old, legacy=True) == rows(new), 'old_rows': len(old), 'new_rows': len(new)}
