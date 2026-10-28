"""Schema reader: describe every loaded table as plain text for an LLM prompt.

For each table it shows the name to use in SQL, the row count, and each column
with its type and a few example values. Names that need quotes in SQL (spaces,
symbols, reserved words) are shown with the quotes, so the model copies them
correctly.
"""

import re

import duckdb

SIMPLE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def describe_schema(con: duckdb.DuckDBPyConnection, sample_rows: int = 3, max_value_len: int = 50) -> str:
    """Return a text description of every user table in `con`."""
    default_db = con.execute("SELECT current_database()").fetchall()[0][0]
    reserved = {row[0] for row in con.execute(
        "SELECT keyword_name FROM duckdb_keywords() WHERE keyword_category = 'reserved'"
    ).fetchall()}
    tables = con.execute(
        "SELECT database_name, schema_name, table_name FROM duckdb_tables()"
        " WHERE table_name NOT LIKE 'sqlite\\_%' ESCAPE '\\'"
        " ORDER BY database_name <> ?, database_name, schema_name, table_name",
        [default_db],
    ).fetchall()

    blocks = []
    for db, schema, table in tables:
        full = f"{_quote(db)}.{_quote(schema)}.{_quote(table)}"
        if db == default_db:
            shown = _sql_name(table, reserved)
        else:
            shown = ".".join(_sql_name(part, reserved) for part in (db, schema, table))

        row_count = con.execute(f"SELECT COUNT(*) FROM {full}").fetchall()[0][0]
        columns = con.execute(
            "SELECT column_name, data_type FROM information_schema.columns"
            " WHERE table_catalog = ? AND table_schema = ? AND table_name = ?"
            " ORDER BY ordinal_position",
            [db, schema, table],
        ).fetchall()
        samples = con.execute(f"SELECT * FROM {full} LIMIT {int(sample_rows)}").fetchall()

        lines = [f"Table {shown} ({row_count} rows)"]
        for i, (column, data_type) in enumerate(columns):
            examples = ", ".join(_format_value(row[i], max_value_len) for row in samples)
            lines.append(f"  - {_sql_name(column, reserved)} {data_type}  e.g. {examples}")
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


def _quote(name: str) -> str:
    """Always-quoted SQL name, safe for any text. Used in our own queries."""
    return '"' + name.replace('"', '""') + '"'


def _sql_name(name: str, reserved: set[str]) -> str:
    """Name as the model should write it: bare if simple, quoted if needed."""
    if SIMPLE_NAME.fullmatch(name) and name.lower() not in reserved:
        return name
    return _quote(name)


def _format_value(value: object, max_len: int) -> str:
    """One short, single-line text form of a sample value."""
    if value is None:
        return "NULL"
    if isinstance(value, str) and not value.strip():
        return repr(value)  # show blank text as '' or ' ', not as nothing
    text = str(value).replace("\n", " ")
    if len(text) > max_len:
        text = text[: max_len - 3] + "..."
    return text
