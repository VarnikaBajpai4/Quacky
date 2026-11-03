"""Streamlit UI for Quacky. Runs on this machine only.

Start it with `quacky-ui`, which binds to localhost, turns off Streamlit's
usage statistics and applies the theme. Load files or paths, then ask
questions in plain English or run your own SQL. Each browser session gets its
own DuckDB connection.
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

AVATAR = Path(__file__).resolve().parent / "static" / "quacky-avatar.svg"
AVATAR_URL = "app/static/quacky-avatar.svg"  # served by Streamlit's static file serving
SAMPLE = ["data/chinook.db", "data/countries.csv", "data/messy.xlsx"]
UPLOAD_TYPES = ["csv", "xlsx", "db", "sqlite", "sqlite3"]
TIMEOUT_S = 10
MAX_ROWS = 1000

# Only what the theme settings in ui.py cannot do: the bundled heading font,
# browser surfaces (selection, caret, scrollbars, focus), the header, and one
# moment of motion (ripples spreading from the duck when the page opens).
STYLE = """
<style>
@font-face {
  font-family: "Bricolage Grotesque";
  src: url("app/static/fonts/BricolageGrotesque-latin.woff2") format("woff2");
  font-weight: 500 800;
  font-display: swap;
}
:root { --qk-yellow: #FFD84D; --qk-ink: #1C1704; --qk-line: #24393F; --qk-muted: #A9B7B0; }
::selection { background: rgba(255, 216, 77, 0.30); color: #FFF8E4; }
* { caret-color: var(--qk-yellow); scrollbar-width: thin; scrollbar-color: var(--qk-line) transparent; }
:focus-visible { outline: 2px solid var(--qk-yellow) !important; outline-offset: 2px; }
[data-testid="stDecoration"] { display: none; }
[data-testid="stHeader"] { background: transparent; }
.block-container { max-width: 980px; padding-top: 2.5rem; }
[data-testid="stSidebar"] { border-right: 1px solid var(--qk-line); }

/* Primary buttons: dark text on duck yellow, not white. */
button[kind="primary"], button[kind="primary"] p { color: var(--qk-ink) !important; font-weight: 600; }

/* Numbers in tables and meta lines line up. */
[data-testid="stDataFrame"], .qk-meta { font-variant-numeric: tabular-nums; }

.qk-hero { display: flex; align-items: center; gap: 1.1rem; margin: 0 0 1.6rem; }
.qk-duck { position: relative; width: 64px; height: 64px; flex: none; }
.qk-duck img { position: relative; width: 64px; height: 64px; z-index: 1; display: block; }
.qk-duck::before, .qk-duck::after {
  content: ""; position: absolute; inset: 0; border-radius: 50%;
  border: 1.5px solid rgba(255, 216, 77, 0.45); opacity: 0;
  animation: qk-ripple 2.4s cubic-bezier(0.16, 1, 0.3, 1) 0.2s 1 both;
}
.qk-duck::after { animation-delay: 0.65s; }
@keyframes qk-ripple { from { transform: scale(1); opacity: 0.9; } to { transform: scale(2.3); opacity: 0; } }
@media (prefers-reduced-motion: reduce) { .qk-duck::before, .qk-duck::after { animation: none; } }
.qk-hero h1 {
  font-family: "Bricolage Grotesque", sans-serif; font-weight: 800; font-size: 2.6rem;
  letter-spacing: -0.03em; line-height: 1; margin: 0; padding: 0; color: #FFF4D6;
}
.qk-hero p { margin: 0.35rem 0 0; color: var(--qk-muted); font-size: 1rem; }

.qk-empty { padding: 2.5rem 0 0.75rem; }
.qk-empty h2 {
  font-family: "Bricolage Grotesque", sans-serif; font-weight: 700; font-size: 1.9rem;
  letter-spacing: -0.02em; margin: 0 0 0.5rem; color: #FFF4D6;
}
.qk-empty p { color: var(--qk-muted); max-width: 34rem; margin: 0; line-height: 1.6; }
.qk-meta { color: var(--qk-muted); font-size: 0.82rem; }
</style>
"""


def main() -> None:
    st.set_page_config(page_title="Quacky", page_icon=str(AVATAR), layout="wide",
                       initial_sidebar_state="expanded")
    st.html(STYLE)
    load_dotenv(find_dotenv(usecwd=True))
    state = st.session_state
    state.setdefault("con", None)
    state.setdefault("history", [])
    state.setdefault("loaded", [])
    state.setdefault("total_cost", 0.0)

    with st.sidebar:
        _sidebar(state)

    _hero()
    if state.con is None:
        _empty_state(state)
        return

    ask_tab, sql_tab, schema_tab = st.tabs([":material/forum: Ask", ":material/terminal: SQL",
                                            ":material/table_chart: Schema"])
    with ask_tab:
        _ask_tab(state)
    with sql_tab:
        _sql_tab(state)
    with schema_tab:
        st.caption("This is exactly what the model reads before it writes SQL.")
        st.code(state.schema, language=None)


def _hero() -> None:
    st.html(f"""
    <div class="qk-hero">
      <div class="qk-duck"><img src="{AVATAR_URL}" alt=""></div>
      <div>
        <h1>Quacky</h1>
        <p>Ask anything about your data. You quack, it queries.</p>
      </div>
    </div>
    """)


def _empty_state(state) -> None:
    st.html("""
    <div class="qk-empty">
      <h2>The pond is quiet</h2>
      <p>Drop a CSV, Excel or SQLite file in the sidebar, or type a local path or a Postgres URL.
      Everything stays on this machine. Only your question and a few sample values go to the model.</p>
    </div>
    """)
    if _sample_available():
        if st.button("Try the sample data", icon=":material/water_drop:"):
            _load(state, [], SAMPLE)
            st.rerun()


def _sidebar(state) -> None:
    st.subheader("Your data")
    uploads = st.file_uploader("Files", type=UPLOAD_TYPES, accept_multiple_files=True)
    paths = st.text_area("Local paths or a Postgres URL, one per line", height=90,
                         placeholder="data/sales.csv\npostgresql://user@host/db")
    if st.button("Load data", type="primary", icon=":material/add:", use_container_width=True):
        _load(state, uploads, paths.splitlines())
    if _sample_available() and st.button("Use sample data", icon=":material/water_drop:",
                                         use_container_width=True):
        _load(state, [], SAMPLE)

    if state.loaded:
        st.markdown("**In the pond**")
        for name, count in state.loaded:
            st.markdown(f":green[:material/check_circle:] {Path(name).name} "
                        f"<span class='qk-meta'>· {count} table{'s' if count != 1 else ''}</span>",
                        unsafe_allow_html=True)

    st.divider()
    with st.expander("Model", icon=":material/tune:"):
        st.text_input("OpenRouter model", value=MODEL, key="model")
        st.text_input("Pinned provider endpoint", value=PROVIDER, key="provider")
    st.html(f"<p class='qk-meta'>Spent this session: ${state.total_cost:.5f}</p>")


def _sample_available() -> bool:
    return all(Path(p).is_file() for p in SAMPLE)


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
            st.sidebar.error(f"Could not load {name}: {e}", icon=":material/error:")
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
                   "where you start Quacky. Your own SQL still works in the SQL tab.",
                   icon=":material/key:")
    elif not state.history:
        st.caption("Ask in plain English. Quacky writes the SQL, checks it, runs it, "
                   "and shows the answer.")

    for answer in state.history:
        _show_answer(answer)

    question = st.chat_input("Ask the duck, e.g. which artist has the most albums?",
                             max_chars=1000, disabled=client is None)
    if not question:
        return
    with st.spinner("Quacking up some SQL..."):
        try:
            answer = ask(state.con, client, state.schema, question, model=state.model,
                         provider=state.provider, timeout_s=TIMEOUT_S, max_rows=MAX_ROWS)
        except openai.APIError as e:
            st.error(api_error_message(e), icon=":material/cloud_off:")
            return
    state.history.append(answer)
    state.total_cost += answer.cost_usd
    st.rerun()


def _show_answer(answer: Answer) -> None:
    with st.chat_message("user", avatar=":material/person:"):
        st.markdown(answer.question)
    with st.chat_message("assistant", avatar=str(AVATAR)):
        if answer.ok:
            _show_table(answer.df)
        elif answer.attempts:
            st.warning(f"No answer after {len(answer.attempts)} tries. Try asking another way.",
                       icon=":material/help:")
        if answer.note:
            st.markdown(answer.note)

        if answer.attempts:
            tries = len(answer.attempts)
            label = "SQL" if tries == 1 else f"SQL · {tries} tries"
            with st.expander(label, icon=":material/code:"):
                for i, attempt in enumerate(answer.attempts, start=1):
                    if attempt.error:
                        st.caption(f"Try {i} failed: {attempt.error.splitlines()[0]}")
                st.code(_pretty(answer.sql), language="sql")
        st.html(f"<p class='qk-meta'>{answer.input_tokens:,} tokens in "
                f"({answer.cached_tokens:,} cached) · {answer.output_tokens:,} out · "
                f"${answer.cost_usd:.5f}</p>")


def _pretty(sql: str) -> str:
    """SQL split over several lines, for reading only. The query that ran is unchanged."""
    try:
        return sqlglot.transpile(sql, read="duckdb", write="duckdb", pretty=True)[0]
    except sqlglot.errors.SqlglotError:
        return sql


def _sql_tab(state) -> None:
    sql = st.text_area("Your SQL: one read-only query", height=130, key="sql",
                       placeholder="SELECT * FROM countries LIMIT 10")
    if not st.button("Run", type="primary", icon=":material/play_arrow:"):
        return
    try:
        df = run_safe(state.con, sql, timeout_s=TIMEOUT_S, max_rows=MAX_ROWS)
    except UnsafeQueryError as e:
        st.error(f"Rejected: {e}", icon=":material/block:")
    except QueryTimeoutError as e:
        st.error(f"Timeout: {e}", icon=":material/timer_off:")
    except duckdb.Error as e:
        st.error(f"SQL error: {e}", icon=":material/error:")
    else:
        _show_table(df)


def _show_table(df) -> None:
    if df.empty:
        st.markdown("No rows match.")
        return
    st.dataframe(df, hide_index=True)
    note = f"{len(df):,} row{'s' if len(df) != 1 else ''}"
    if df.attrs.get("truncated"):
        note += f", cut at the {MAX_ROWS:,}-row limit"
    st.html(f"<p class='qk-meta'>{note}</p>")


main()
