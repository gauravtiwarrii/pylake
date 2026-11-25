import re

import sqlglot
from sqlglot import exp


FORBIDDEN_TABLE_FUNCTIONS = {
    "READ_CSV",
    "READ_CSV_AUTO",
    "READ_PARQUET",
    "READ_JSON",
    "READ_JSON_AUTO",
    "READ_NDJSON",
    "PARQUET_SCAN",
    "CSV_SCAN",
    "GLOB",
    "HTTPFS",
    "READ_TEXT",
    "SQLITE_SCAN",
    "POSTGRES_SCAN",
    "MYSQL_SCAN",
    "DELTA_SCAN",
    "ICEBERG_SCAN",
    "EXCEL_SCAN",
    "ARROW_SCAN",
}

FORBIDDEN_STATEMENTS = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.Merge,
    exp.Copy,
)

FORBIDDEN_EXPRESSIONS = (
    exp.Attach,
    exp.Detach,
)


class SQLValidationError(ValueError):
    pass


def validate_read_only_sql(sql: str) -> tuple[list[str], list[str]]:
    if not isinstance(sql, str) or not sql.strip():
        raise SQLValidationError("SQL query cannot be empty")
    if len(sql) > 100_000:
        raise SQLValidationError("SQL query is too large")
    stripped = sql.strip()
    statement_text = stripped[:-1].rstrip() if stripped.endswith(";") else stripped
    if ";" in statement_text:
        raise SQLValidationError("Multiple SQL statements are not allowed")

    try:
        expressions = sqlglot.parse(sql, dialect="duckdb")
    except Exception as error:
        raise SQLValidationError("Invalid SQL syntax") from error
    expressions = [expression for expression in expressions if expression is not None]
    if len(expressions) != 1:
        raise SQLValidationError("Exactly one SQL statement is allowed")

    statement = expressions[0]
    if not isinstance(statement, exp.Select) and not isinstance(statement, exp.Union):
        raise SQLValidationError("Only read-only SELECT queries are allowed")
    if isinstance(statement, FORBIDDEN_STATEMENTS) or statement.find(exp.Attach) or statement.find(exp.Detach):
        raise SQLValidationError("This SQL operation is not allowed")

    table_names: list[str] = []
    for table in statement.find_all(exp.Table):
        name = table.name
        if name:
            table_names.append(name)
        catalog = table.catalog
        db = table.db
        if catalog or db:
            raise SQLValidationError("Database and schema-qualified file access is not allowed")

    for function in statement.find_all(exp.Func):
        name = (function.name or function.sql_name()).upper()
        if name in FORBIDDEN_TABLE_FUNCTIONS:
            raise SQLValidationError("Arbitrary file or network table functions are not allowed")

    forbidden_text = re.compile(
        r"\b(attach|detach|install|load|copy|read_(?:csv|parquet|json|text|ndjson)|httpfs|sqlite_scan|postgres(?:ql)?_scan|mysql_scan|delta_scan|iceberg_scan|excel_scan|arrow_scan)\b",
        re.I,
    )
    if forbidden_text.search(sql):
        raise SQLValidationError("External file access or extension loading is not allowed")

    return table_names, [column.name for column in statement.find_all(exp.Column) if column.name]
