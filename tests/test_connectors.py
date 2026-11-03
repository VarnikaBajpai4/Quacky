import duckdb
import pandas as pd
import pytest

from quacky.connectors import clean_name, load_source


@pytest.mark.parametrize("text, expected", [
    ("Sales Data", "sales_data"),
    ("Q3 Sales Report!!", "q3_sales_report"),
    ("messy_Targets", "messy_targets"),
    ("2024-sales", "t_2024_sales"),
    ("it's here", "it_s_here"),
])
def test_clean_name(text, expected):
    assert clean_name(text) == expected


def test_clean_name_rejects_text_with_no_letters_or_digits():
    with pytest.raises(ValueError):
        clean_name("  --- ")


def test_each_source_type_loads(data_dir):
    con = duckdb.connect()
    assert load_source(con, str(data_dir / "shop.db")) == ["shop.main.customers", "shop.main.invoices"]
    assert load_source(con, str(data_dir / "countries.csv")) == ["countries"]
    assert load_source(con, str(data_dir / "messy.xlsx")) == ["messy_sales", "messy_targets"]


def test_sqlite_internal_tables_are_hidden(data_dir):
    con = duckdb.connect()
    tables = load_source(con, str(data_dir / "shop.db"))
    assert not any("sqlite_" in table for table in tables)


def test_join_across_sqlite_and_csv(con):
    rows = con.execute(
        'SELECT c.Name, co.Region FROM shop.main.customers c '
        'JOIN countries co ON co."Country Name" = c.Country ORDER BY 1'
    ).fetchall()
    assert rows == [("Ana", "Americas"), ("Ben", "Americas")]  # 'USA' does not match 'United States'


def test_attached_database_is_read_only(con):
    with pytest.raises(duckdb.Error):
        con.execute("DELETE FROM shop.main.invoices")


def test_loading_the_same_name_twice_is_rejected(con, data_dir):
    with pytest.raises(ValueError, match="already used"):
        load_source(con, str(data_dir / "countries.csv"))
    with pytest.raises(ValueError, match="already used"):
        load_source(con, str(data_dir / "shop.db"))


def test_unsupported_file_type_is_rejected(tmp_path):
    path = tmp_path / "data.parquet"
    path.write_text("x")
    with pytest.raises(ValueError, match="Unsupported"):
        load_source(duckdb.connect(), str(path))


def test_missing_file_is_reported(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_source(duckdb.connect(), str(tmp_path / "missing.csv"))


def test_file_name_with_a_quote_gets_a_safe_table_name(tmp_path):
    path = tmp_path / "it's here.csv"
    path.write_text("a\n1\n")
    assert load_source(duckdb.connect(), str(path)) == ["it_s_here"]


def test_empty_excel_sheet_is_skipped(tmp_path):
    path = tmp_path / "book.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"a": [1, 2]}).to_excel(writer, sheet_name="Data", index=False)
        pd.DataFrame().to_excel(writer, sheet_name="Blank", index=False)
    assert load_source(duckdb.connect(), str(path)) == ["book_data"]


def test_postgres_error_does_not_show_the_password():
    # Port 1 on localhost refuses connections, so the attach fails quickly.
    with pytest.raises(RuntimeError) as error:
        load_source(duckdb.connect(), "postgresql://alice:S3cretPw@127.0.0.1:1/shop")
    assert "S3cretPw" not in str(error.value)
    assert error.value.__cause__ is None  # the original error (with the URL) is not chained
