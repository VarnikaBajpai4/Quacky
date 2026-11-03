"""Safe runner: run one read-only query with a time limit and a row limit.

Four layers. Each one stops attacks that another layer could miss:
1. Parse check: exactly one statement, a query (SELECT or UNION/INTERSECT/
   EXCEPT of SELECTs), with no write or admin command hidden inside it.
2. Lock: DuckDB itself refuses file access and config changes (lock_down).
3. Timeout: a timer interrupts the query if it runs too long.
4. Row limit: read at most max_rows rows.
"""

import threading

import duckdb
import pandas as pd
import sqlglot
from sqlglot import exp

# Statement types that must not appear anywhere in the query tree, not even
# nested (for example a DELETE inside a WITH clause).
FORBIDDEN = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Into,
    exp.Create, exp.Drop, exp.Alter,
    exp.Set, exp.Pragma, exp.Command, exp.Use,
    exp.Copy, exp.Attach, exp.Detach, exp.Install,
    exp.Transaction, exp.Commit, exp.Rollback,
)


class UnsafeQueryError(ValueError):
    """The SQL was rejected before it ran."""


class QueryTimeoutError(RuntimeError):
    """The query ran longer than the time limit and was stopped."""


def lock_down(con: duckdb.DuckDBPyConnection) -> None:
    """Block file access and freeze the config. Call once, after all sources load."""
    con.execute("SET enable_external_access = false")
    con.execute("SET lock_configuration = true")


def check_sql(con: duckdb.DuckDBPyConnection, sql: str) -> duckdb.Statement:
    """Reject anything but one read-only query. Return DuckDB's parsed statement."""
    try:
        trees = [tree for tree in sqlglot.parse(sql, read="duckdb") if tree is not None]
    except sqlglot.errors.ParseError as e:
        raise UnsafeQueryError(f"Could not parse SQL: {str(e).splitlines()[0]}") from None
    if len(trees) != 1:
        raise UnsafeQueryError(f"Expected exactly one statement, got {len(trees)}.")

    tree = trees[0]
    if not isinstance(tree, (exp.Select, exp.SetOperation)):
        raise UnsafeQueryError(f"Only SELECT queries are allowed, got {tree.key.upper()}.")
    bad = tree.find(*FORBIDDEN)
    if bad is not None:
        raise UnsafeQueryError(f"Query contains a forbidden {bad.key.upper()} part.")

    # Ask DuckDB's own parser too, so sqlglot and DuckDB cannot disagree on
    # where one statement ends. We run DuckDB's parsed statement, not the text.
    statements = con.extract_statements(sql)
    if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
        raise UnsafeQueryError("DuckDB does not read this as one SELECT statement.")
    return statements[0]


def run_safe(
    con: duckdb.DuckDBPyConnection, sql: str, timeout_s: float = 10, max_rows: int = 1000
) -> pd.DataFrame:
    """Run one safe query. df.attrs["truncated"] is True if rows were cut."""
    locked = con.execute("SELECT current_setting('lock_configuration')").fetchall()[0][0]
    if not locked:
        raise RuntimeError("Connection is not locked. Call lock_down(con) first.")
    statement = check_sql(con, sql)

    timer = threading.Timer(timeout_s, con.interrupt)
    timer.start()
    result = None
    try:
        result = con.execute(statement)
        rows = result.fetchmany(max_rows + 1)  # one extra row tells us if there are more
        columns = [column[0] for column in result.description]
    except duckdb.InterruptException:
        raise QueryTimeoutError(f"Query stopped: it ran longer than {timeout_s} s.") from None
    finally:
        timer.cancel()
        if result is not None:
            result.abort()  # free the connection for the next query (DuckDB 2.0)

    df = pd.DataFrame(rows[:max_rows], columns=columns)
    df.attrs["truncated"] = len(rows) > max_rows
    return df
