"""Pure cutover guards; no connection, authentication or SQL execution."""
import re


def normalize_definition(sql):
    """Canonicalize only the leading CREATE [OR ALTER] VIEW/FUNCTION header.

    Preserve every byte after the header, including identifiers, comments,
    quoted literals, line endings and trailing whitespace/semicolons.
    """
    return re.sub(r'\A\s*CREATE\s+(?:OR\s+ALTER\s+)?(VIEW|FUNCTION)\s+',
                  lambda match: 'CREATE ' + match[1].upper() + ' ',
                  sql, count=1, flags=re.IGNORECASE)


def validate_binding(preflight, approved_sha, *, workspace_id, warehouse_id,
                     source_id, database_name):
    """Fail closed unless approval, successful preflight and live target agree."""
    if preflight.get('status') != 'preflight_passed':
        raise ValueError('A passed preflight is required')
    current = dict(sql_sha256=approved_sha, workspace_id=workspace_id,
                   warehouse_id=warehouse_id, source_id=source_id,
                   database_name=database_name)
    for key, value in current.items():
        if not isinstance(value, str) or not value or preflight.get(key) != value:
            raise ValueError(f'Preflight binding mismatch: {key}')
