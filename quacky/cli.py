"""Command-line interface: load sources, lock DuckDB, show the schema, run SQL.

Usage: python -m quacky.cli <source> [<source> ...] [--timeout S] [--max-rows N]

Phase 1 has no model yet, so you type the SQL yourself.
"""

import argparse
import sys
from urllib.parse import urlparse

import duckdb

from quacky.connectors import POSTGRES_PREFIXES, load_source
from quacky.runner import QueryTimeoutError, UnsafeQueryError, lock_down, run_safe
from quacky.schema import describe_schema

SHOWN_ROWS = 50
HELP = "Type one SQL query per line. Commands: .schema  .help  .quit"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quacky", description="Ask Quacky about your data.")
    parser.add_argument("sources", nargs="+", help="CSV, XLSX or SQLite file, or a postgresql:// URL")
    parser.add_argument("--timeout", type=float, default=10, help="seconds per query (default 10)")
    parser.add_argument("--max-rows", type=int, default=1000, help="rows per query (default 1000)")
    args = parser.parse_args(argv)

    con = duckdb.connect()
    for source in args.sources:
        try:
            tables = load_source(con, source)
        except (ValueError, FileNotFoundError, RuntimeError, duckdb.Error) as e:
            print(f"Could not load {_display(source)}: {e}", file=sys.stderr)
            return 1
        print(f"Loaded {_display(source)}: {len(tables)} table(s)")

    # Lock only after every source is loaded: after this, no file can be read.
    lock_down(con)

    print()
    print(describe_schema(con))
    print()
    print(HELP)

    while True:
        try:
            sql = input("quacky> ").strip()
        except (EOFError, KeyboardInterrupt):  # Ctrl+D or Ctrl+C at the prompt
            print()
            return 0

        if not sql:
            continue
        if sql in (".quit", ".exit"):
            return 0
        if sql == ".help":
            print(HELP)
            continue
        if sql == ".schema":
            print(describe_schema(con))
            continue

        try:
            df = run_safe(con, sql, timeout_s=args.timeout, max_rows=args.max_rows)
        except UnsafeQueryError as e:
            print(f"Rejected: {e}")
        except QueryTimeoutError as e:
            print(f"Timeout: {e}")
        except duckdb.Error as e:
            print(f"SQL error: {e}")
        else:
            _print_result(df, args.max_rows)


def _print_result(df, max_rows: int) -> None:
    if df.empty:
        print("(no rows)")
        return
    print(df.to_string(index=False, max_rows=SHOWN_ROWS))
    note = f"{len(df)} row(s)"
    if df.attrs.get("truncated"):
        note += f", cut at the {max_rows}-row limit"
    print(f"({note})")


def _display(source: str) -> str:
    """Source text that is safe to print: a Postgres URL loses its password."""
    if not source.startswith(POSTGRES_PREFIXES):
        return source
    url = urlparse(source)
    if url.password:
        return source.replace(f":{url.password}@", ":***@")
    return source


if __name__ == "__main__":
    sys.exit(main())
