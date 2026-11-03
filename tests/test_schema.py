import duckdb

from quacky.schema import describe_schema


def test_lists_every_table_with_its_row_count(con):
    text = describe_schema(con)
    assert "Table countries (3 rows)" in text
    assert "Table messy_targets (6 rows)" in text
    assert "Table shop.main.invoices (4 rows)" in text


def test_own_files_come_before_attached_databases(con):
    tables = [line for line in describe_schema(con).splitlines() if line.startswith("Table ")]
    assert tables[0].startswith("Table countries")
    assert tables[-1].startswith("Table shop.")


def test_names_that_need_quotes_are_quoted(con):
    text = describe_schema(con)
    assert '"Country Name" VARCHAR' in text
    assert '"Employee Name" VARCHAR' in text
    assert "  - Region VARCHAR" in text  # simple names stay bare


def test_sqlite_internal_tables_are_hidden(con):
    assert "sqlite_" not in describe_schema(con)


def test_example_values_show_nulls_and_blank_text(con):
    text = describe_schema(con)
    assert "e.g. NULL" in text  # messy_sales has empty cells
    assert "' '" in text  # the blank Code value is visible, not invisible


def test_long_values_are_cut():
    con = duckdb.connect()
    con.execute("CREATE TABLE t AS SELECT repeat('x', 200) AS long_text")
    line = next(l for l in describe_schema(con, max_value_len=50).splitlines() if "long_text" in l)
    assert line.endswith("x" * 47 + "...")


def test_empty_connection_gives_empty_text():
    assert describe_schema(duckdb.connect()) == ""
