"""Shared test data. Every test run builds its own small files, so the tests
need no downloads and do not depend on the gitignored data/ folder."""

import importlib.util
import sqlite3
from pathlib import Path

import duckdb
import pytest

from quacky.connectors import load_source
from quacky.runner import lock_down

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("data")

    # SQLite: AUTOINCREMENT makes SQLite add its internal sqlite_sequence table.
    db = sqlite3.connect(folder / "shop.db")
    db.executescript("""
        CREATE TABLE customers (CustomerId INTEGER PRIMARY KEY AUTOINCREMENT, Name TEXT, Country TEXT);
        CREATE TABLE invoices (InvoiceId INTEGER PRIMARY KEY AUTOINCREMENT, CustomerId INTEGER, Total REAL);
        INSERT INTO customers (Name, Country) VALUES ('Ana', 'Brazil'), ('Ben', 'Canada'), ('Cleo', 'USA');
        INSERT INTO invoices (CustomerId, Total) VALUES (1, 10.0), (1, 5.5), (2, 8.0), (3, 20.0);
    """)
    db.commit()
    db.close()

    # CSV: a header with spaces, and a blank (space-only) value.
    (folder / "countries.csv").write_text(
        "Country Name,Region,Code\nBrazil,Americas,BR\nCanada,Americas,CA\nUnited States,Americas, \n"
    )

    # Excel: the same generator as scripts/make_messy_xlsx.py.
    spec = importlib.util.spec_from_file_location("make_messy_xlsx", ROOT / "scripts" / "make_messy_xlsx.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.build(folder / "messy.xlsx")

    return folder


@pytest.fixture
def sources(data_dir) -> list[str]:
    return [str(data_dir / name) for name in ("shop.db", "countries.csv", "messy.xlsx")]


@pytest.fixture
def con(sources) -> duckdb.DuckDBPyConnection:
    """A connection with all test sources loaded, not locked."""
    connection = duckdb.connect()
    for source in sources:
        load_source(connection, source)
    yield connection
    connection.close()


@pytest.fixture
def locked(con) -> duckdb.DuckDBPyConnection:
    """The same connection, locked the way the CLI locks it."""
    lock_down(con)
    return con
