import duckdb
import pytest

from quacky.runner import QueryTimeoutError, UnsafeQueryError, lock_down, run_safe


@pytest.mark.parametrize("sql", [
    "DROP TABLE countries",
    "SELECT 1; DROP TABLE countries",
    "SET enable_external_access = true",
    "RESET lock_configuration",
    "WITH d AS (DELETE FROM countries RETURNING *) SELECT * FROM d",  # DELETE hidden inside a SELECT
    "SELECT * INTO copy FROM countries",
    "CREATE TABLE z AS SELECT 1",
    "INSERT INTO countries VALUES ('x', 'y', 'z')",
    "UPDATE countries SET Region = 'x'",
    "ATTACH ':memory:' AS other",
    "DETACH shop",
    "COPY countries TO 'out.csv'",
    "PRAGMA version",
    "INSTALL httpfs",
    "CALL pragma_version()",
    "SUMMARIZE countries",
    "",
    "SELEC 1",
])
def test_unsafe_or_invalid_sql_is_rejected(locked, sql):
    with pytest.raises(UnsafeQueryError):
        run_safe(locked, sql)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM read_text('/etc/passwd')",
])
def test_lock_blocks_file_access(locked, sql):
    with pytest.raises(duckdb.Error, match="disabled by configuration"):
        run_safe(locked, sql)


@pytest.mark.parametrize("sql, expected", [
    ("SELECT COUNT(*) FROM shop.main.invoices", [[4]]),
    ("SELECT 1 -- ; DROP TABLE countries", [[1]]),  # the DROP is only a comment
    ("SELECT 'a;b' AS s", [["a;b"]]),  # the semicolon is inside a string
    ("WITH a AS (SELECT 1 AS x) SELECT x FROM a UNION ALL SELECT 2", [[1], [2]]),
])
def test_read_only_queries_run(locked, sql, expected):
    assert run_safe(locked, sql).values.tolist() == expected


def test_unlocked_connection_is_refused(con):
    with pytest.raises(RuntimeError, match="not locked"):
        run_safe(con, "SELECT 1")


def test_slow_query_is_stopped_by_the_timeout():
    con = duckdb.connect()
    con.execute("CREATE TABLE big AS SELECT range AS i FROM range(3000)")
    lock_down(con)
    # COUNT(*) over a cross join is computed without building the rows, so a
    # SUM is needed to force real work (3000^3 = 27 billion rows).
    with pytest.raises(QueryTimeoutError):
        run_safe(con, "SELECT SUM(a.i * b.i * c.i) FROM big a, big b, big c", timeout_s=1)
    assert run_safe(con, "SELECT 42").values.tolist() == [[42]]  # still usable afterwards


def test_row_limit_cuts_and_flags_the_result():
    con = duckdb.connect()
    con.execute("CREATE TABLE nums AS SELECT range AS i FROM range(50)")
    lock_down(con)
    cut = run_safe(con, "SELECT * FROM nums", max_rows=10)
    assert len(cut) == 10 and cut.attrs["truncated"] is True
    exact = run_safe(con, "SELECT * FROM nums", max_rows=50)
    assert len(exact) == 50 and exact.attrs["truncated"] is False


def test_connection_still_works_after_an_sql_error(locked):
    with pytest.raises(duckdb.Error):
        run_safe(locked, "SELECT nope FROM countries")
    assert run_safe(locked, "SELECT 43").values.tolist() == [[43]]
