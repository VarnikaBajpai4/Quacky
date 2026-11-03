"""Streamlit UI for Quacky. Runs on this machine only.

Start it with `quacky-ui`, which binds to localhost and turns off Streamlit's
usage statistics. Load files or paths, then ask questions in plain English or
run your own SQL. Each browser session gets its own DuckDB connection.
"""

import tempfile
from pathlib import Path

import duckdb
import openai
import sqlglot
import streamlit as st
from dotenv import find_dotenv, load_dotenv

from quacky.connectors import display_source, load_source
from quacky.llm import MODEL, PROVIDER, Answer, api_error_message, ask, make_client
from quacky.runner import QueryTimeoutError, UnsafeQueryError, lock_down, run_safe
from quacky.schema import describe_schema

AVATAR = Path(__file__).resolve().parent.parent / "assets" / "quacky-avatar.svg"
SAMPLE = ["data/chinook.db", "data/countries.csv", "data/messy.xlsx"]
UPLOAD_TYPES = ["csv", "xlsx", "db", "sqlite", "sqlite3"]
TIMEOUT_S = 10
MAX_ROWS = 1000


def main() -> None:
    st.set_page_config(page_title="Quacky", page_icon="🦆", layout="wide")
    load_dotenv(find_dotenv(usecwd=True))
    state = st.session_state
    state.setdefault("con", None)
    state.setdefault("history", [])
    state.setdefault("loaded", [])
    state.setdefault("total_cost", 0.0)

    with st.sidebar:
        _sidebar(state)

    st.title("🦆 Quacky")
    st.caption("Ask your data questions in plain English. Runs on your machine.")
    if state.con is None:
        st.info("Load some data in the sidebar to start: upload files, or type local paths.")
        return

    ask_tab, sql_tab, schema_tab = st.tabs(["Ask", "SQL", "Schema"])
    with ask_tab:
        _ask_tab(state)
    with sql_tab:
        _sql_tab(state)
    with schema_tab:
        st.code(state.schema, language=None)


def _sidebar(state) -> None:
    if AVATAR.is_file():
        st.image(str(AVATAR), width=80)
    st.header("Data")
    uploads = st.file_uploader("Upload files", type=UPLOAD_TYPES, accept_multiple_files=True)
    paths = st.text_area("Or local paths / a Postgres URL, one per line",
                         placeholder="data/chinook.db\npostgresql://user:password@host/db")
    if st.button("Load data", type="primary"):
        _load(state, uploads, paths.splitlines())
    if all(Path(p).is_file() for p in SAMPLE) and st.button("Load sample data"):
        _load(state, [], SAMPLE)

    for name, count in state.loaded:
        st.caption(f"✓ {name}: {count} table(s)")

    with st.expander("Model"):
        st.text_input("OpenRouter model", value=MODEL, key="model")
        st.text_input("Pinned provider endpoint", value=PROVIDER, key="provider")
    st.caption(f"Spent this session: ${state.total_cost:.5f}")


def _load(state, uploads, lines: list[str]) -> None:
    """Load every source into a new locked connection. On any error, keep the old one."""
    # Uploads are saved to a temp folder that stays for the session, because a
    # SQLite file is read in place, not copied.
    folder = Path(tempfile.mkdtemp(prefix="quacky-"))
    sources = []  # (source for load_source, name to show)
    for upload in uploads:
        path = folder / Path(upload.name).name  # keep only the file name, never a path
        path.write_bytes(upload.getvalue())
        sources.append((str(path), upload.name))
    sources += [(line.strip(), display_source(line.strip())) for line in lines if line.strip()]
    if not sources:
        st.sidebar.warning("Choose at least one file or path.")
        return

    con = duckdb.connect()
    loaded = []
    for source, name in sources:
        try:
            loaded.append((name, len(load_source(con, source))))
        except (ValueError, FileNotFoundError, RuntimeError, duckdb.Error) as e:
            con.close()
            st.sidebar.error(f"Could not load {name}: {e}")
            return

    lock_down(con)  # only after every source is loaded
    if state.con is not None:
        state.con.close()
    state.con, state.loaded, state.history = con, loaded, []
    state.schema = describe_schema(con)


def _ask_tab(state) -> None:
    client = make_client()
    if client is None:
        st.warning("No API key found. Put OPENROUTER_API_KEY=... in a .env file in the folder "
                   "where you start Quacky. You can still run your own SQL in the SQL tab.")

    for answer in state.history:
        _show_answer(answer)

    question = st.chat_input("Ask a question about your data", max_chars=1000, disabled=client is None)
    if not question:
        return
    with st.spinner("Writing SQL..."):
        try:
            answer = ask(state.con, client, state.schema, question, model=state.model,
                         provider=state.provider, timeout_s=TIMEOUT_S, max_rows=MAX_ROWS)
        except openai.APIError as e:
            st.error(api_error_message(e))
            return
    state.history.append(answer)
    state.total_cost += answer.cost_usd
    st.rerun()


def _show_answer(answer: Answer) -> None:
    with st.chat_message("user"):
        st.write(answer.question)
    with st.chat_message("assistant", avatar="🦆"):
        if answer.note:
            st.write(answer.note)
        for i, attempt in enumerate(answer.attempts, start=1):
            if attempt.error:
                st.caption(f"Try {i} failed: {attempt.error.splitlines()[0]}")
        if answer.sql:
            st.code(_pretty(answer.sql), language="sql")
        if answer.ok:
            _show_table(answer.df)
        elif answer.attempts:
            st.warning(f"No answer after {len(answer.attempts)} tries.")
        st.caption(f"{answer.input_tokens} tokens in ({answer.cached_tokens} cached), "
                   f"{answer.output_tokens} out · ${answer.cost_usd:.5f}")


def _pretty(sql: str) -> str:
    """SQL split over several lines, for reading only. The query that ran is unchanged."""
    try:
        return sqlglot.transpile(sql, read="duckdb", write="duckdb", pretty=True)[0]
    except sqlglot.errors.SqlglotError:
        return sql


def _sql_tab(state) -> None:
    sql = st.text_area("Your SQL (one read-only query)", height=120, key="sql")
    if not st.button("Run"):
        return
    try:
        df = run_safe(state.con, sql, timeout_s=TIMEOUT_S, max_rows=MAX_ROWS)
    except UnsafeQueryError as e:
        st.error(f"Rejected: {e}")
    except QueryTimeoutError as e:
        st.error(f"Timeout: {e}")
    except duckdb.Error as e:
        st.error(f"SQL error: {e}")
    else:
        _show_table(df)


def _show_table(df) -> None:
    if df.empty:
        st.write("(no rows)")
        return
    st.dataframe(df, hide_index=True)
    note = f"{len(df)} row(s)"
    if df.attrs.get("truncated"):
        note += f", cut at the {MAX_ROWS}-row limit"
    st.caption(note)


main()
