"""The Streamlit app, driven in memory by Streamlit's own test harness."""

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from conftest import ROOT  # noqa: E402

APP = str(ROOT / "quacky" / "app.py")


@pytest.fixture
def app(monkeypatch, tmp_path):
    # Run from an empty folder with no key, so the real .env is never loaded.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    return AppTest.from_file(APP, default_timeout=30).run()


def click(app, label):
    next(b for b in app.button if b.label == label).click().run()


def page_html(app):
    return " ".join(h.value for h in app.get("html"))


def load(app, sources):
    app.text_area[0].set_value("\n".join(sources))
    click(app, "Load data")


def test_starts_with_an_empty_state(app):
    assert not app.exception
    assert "The pond is quiet" in page_html(app)
    assert not app.tabs


def test_loads_sources_and_shows_the_schema(app, sources):
    load(app, sources)
    assert not app.exception
    loaded = [m.value for m in app.sidebar.markdown]
    assert any("shop.db" in m and "2 tables" in m for m in loaded)
    assert any("countries.csv" in m and "1 table<" in m for m in loaded)
    assert "Table shop.main.invoices (4 rows)" in app.code[0].value


def test_bad_source_shows_an_error_and_loads_nothing(app, tmp_path):
    load(app, [str(tmp_path / "missing.csv")])
    assert "File not found" in app.sidebar.error[0].value
    assert "The pond is quiet" in page_html(app)


def test_no_key_warns_and_disables_questions(app, sources):
    load(app, sources)
    assert "No API key" in app.warning[0].value
    assert app.chat_input[0].disabled


def test_sql_tab_runs_safe_queries_and_rejects_unsafe_ones(app, sources):
    load(app, sources)
    app.text_area(key="sql").set_value("SELECT COUNT(*) AS n FROM shop.main.invoices")
    click(app, "Run")
    assert app.dataframe[0].value.values.tolist() == [[4]]

    app.text_area(key="sql").set_value("DROP TABLE countries")
    click(app, "Run")
    assert "Rejected: Only SELECT queries are allowed" in app.error[0].value

    app.text_area(key="sql").set_value("SELECT * FROM read_csv('/etc/passwd')")
    click(app, "Run")
    assert "disabled by configuration" in app.error[0].value
