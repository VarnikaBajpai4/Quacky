"""Connectors: load data sources into one DuckDB connection.

Every source becomes one or more tables that a single DuckDB SQL query can
read. File-based sources (CSV, Excel) are copied into DuckDB's in-memory
database. Databases (SQLite, Postgres) are attached read-only, so DuckDB reads
them in place and can never change them.
"""

import re
from pathlib import Path
from urllib.parse import urlparse

import duckdb
import pandas as pd

SQLITE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
EXCEL_SUFFIXES = {".xlsx"}
POSTGRES_PREFIXES = ("postgresql://", "postgres://")
SUPPORTED = ".csv, .xlsx, .db/.sqlite/.sqlite3, postgresql://"


def clean_name(text: str) -> str:
    """Turn any text into a safe SQL name: only a-z, 0-9 and _."""
    name = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    if not name:
        raise ValueError(f"Cannot make a table name from {text!r}")
    if name[0].isdigit():
        name = f"t_{name}"
    return name


def load_source(con: duckdb.DuckDBPyConnection, source: str) -> list[str]:
    """Load one source into `con`. Return the names of the tables it made."""
    if source.startswith(POSTGRES_PREFIXES):
        return _load_postgres(con, source)

    path = Path(source)
    suffix = path.suffix.lower()
    if suffix not in {".csv"} | EXCEL_SUFFIXES | SQLITE_SUFFIXES:
        raise ValueError(f"Unsupported source {source!r}. Supported: {SUPPORTED}")
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {source}")

    if suffix == ".csv":
        return _load_csv(con, path)
    if suffix in EXCEL_SUFFIXES:
        return _load_excel(con, path)
    return _attach(con, str(path), clean_name(path.stem), "sqlite")


def _ensure_unused(con: duckdb.DuckDBPyConnection, names: list[str]) -> None:
    """Fail if a name is used twice or already taken by a table or database."""
    taken = {row[0] for row in con.execute(
        "SELECT table_name FROM duckdb_tables() WHERE database_name = current_database()"
        " UNION SELECT database_name FROM duckdb_databases()"
    ).fetchall()}
    seen = set()
    for name in names:
        if name in taken or name in seen:
            raise ValueError(f"Name {name!r} is already used. Rename the file or sheet.")
        seen.add(name)


def _load_csv(con: duckdb.DuckDBPyConnection, path: Path) -> list[str]:
    name = clean_name(path.stem)
    _ensure_unused(con, [name])
    con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM read_csv_auto(?)', [str(path)])
    return [name]


def _load_excel(con: duckdb.DuckDBPyConnection, path: Path) -> list[str]:
    sheets = pd.read_excel(path, sheet_name=None)
    # DuckDB cannot make a table from a sheet with no columns, so skip empty sheets.
    sheets = {sheet: df for sheet, df in sheets.items() if len(df.columns) > 0}
    names = [clean_name(f"{path.stem}_{sheet}") for sheet in sheets]
    _ensure_unused(con, names)  # check all names first, so we never load half a file

    for name, df in zip(names, sheets.values()):
        con.register("_quacky_tmp", df)
        try:
            con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM _quacky_tmp')
        finally:
            con.unregister("_quacky_tmp")
    return names


def _load_postgres(con: duckdb.DuckDBPyConnection, url: str) -> list[str]:
    # Extensions must be loaded now: after the config is locked, they cannot be.
    con.execute("INSTALL postgres")
    con.execute("LOAD postgres")
    alias = clean_name(urlparse(url).path.lstrip("/") or "postgres")
    try:
        return _attach(con, url, alias, "postgres")
    except duckdb.Error as e:
        # The URL holds the password, so never show it in an error.
        message = str(e).replace(url, "<postgres url>")
        password = urlparse(url).password
        if password:
            message = message.replace(password, "***")
        raise RuntimeError(f"Could not attach Postgres database {alias!r}: {message}") from None


def _attach(con: duckdb.DuckDBPyConnection, target: str, alias: str, db_type: str) -> list[str]:
    _ensure_unused(con, [alias])
    con.execute(f'ATTACH ? AS "{alias}" (TYPE {db_type}, READ_ONLY)', [target])
    rows = con.execute(
        "SELECT schema_name, table_name FROM duckdb_tables()"
        " WHERE database_name = ? AND table_name NOT LIKE 'sqlite\\_%' ESCAPE '\\'"
        " ORDER BY schema_name, table_name",
        [alias],
    ).fetchall()
    return [f"{alias}.{schema}.{table}" for schema, table in rows]
