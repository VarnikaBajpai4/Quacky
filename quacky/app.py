"""Streamlit UI for Quacky. Runs on this machine only.

Start it with `quacky-ui`, which binds to localhost, turns off Streamlit's
usage statistics and applies the theme. Load files or paths, then ask
questions in plain English or run your own SQL. Each browser session gets its
own DuckDB connection.

Layout: one centred column, everything aligned to its left edge. No sidebar.
Before data is loaded, the loading form is the page. After that, the data
lives in the "Pond" popover and answers stack up newest first.
"""

import html
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
SAMPLE_QUESTIONS = [
    "Which artist has the most albums?",
    "Which 5 countries spend the most?",
    "Which genre sells the most tracks?",
]
UPLOAD_TYPES = ["csv", "xlsx", "db", "sqlite", "sqlite3"]
MODES = ["Ask", "SQL", "Schema"]
TIMEOUT_S = 10
MAX_ROWS = 1000

# Only what the theme settings in ui.py cannot do: the bundled heading font,
# browser surfaces (selection, caret, scrollbars, focus), the single column,
# typography for questions, and one moment of motion (ripples behind the
# headline when the page opens).
STYLE = """
<style>
@font-face {
  font-family: "Bricolage Grotesque";
  src: url("app/static/fonts/BricolageGrotesque-latin.woff2") format("woff2");
  font-weight: 500 800;
  font-display: swap;
}
:root {
  --qk-yellow: #FFD84D; --qk-ink: #1C1704; --qk-cream: #FFF4D6;
  --qk-line: #22363B; --qk-muted: #A3B2AB; --qk-orange: #F2A541;
  --qk-display: "Bricolage Grotesque", -apple-system, sans-serif;
}
::selection { background: rgba(255, 216, 77, 0.30); color: #FFF8E4; }
* { caret-color: var(--qk-yellow); scrollbar-width: thin; scrollbar-color: var(--qk-line) transparent; }
:focus-visible { outline: 2px solid var(--qk-yellow) !important; outline-offset: 2px; }
[data-testid="stDecoration"], [data-testid="stSidebarCollapsedControl"] { display: none; }
[data-testid="stHeader"] { background: transparent; height: 0; }

/* One column, centred on the window. Everything inside aligns to its left edge. */
.block-container { max-width: 840px; padding: 2.5rem 1.5rem 6rem; }

/* Primary buttons: dark ink on duck yellow, never white. */
button[kind="primary"], button[kind="primary"] p { color: var(--qk-ink) !important; font-weight: 600; }

[data-testid="stDataFrame"], .qk-meta { font-variant-numeric: tabular-nums; }
.qk-meta { color: var(--qk-muted); font-size: 0.82rem; margin: 0; }

/* Wordmark */
.qk-mark { display: flex; align-items: center; gap: 0.6rem; }
.qk-mark img { width: 34px; height: 34px; display: block; }
.qk-mark span { font-family: var(--qk-display); font-weight: 800; font-size: 1.45rem; letter-spacing: -0.03em; color: var(--qk-cream); }

/* Welcome: the duck drops into the pond; ripples spread once. */
.qk-hero { position: relative; padding: 2.5rem 0 1.25rem; }
.qk-lockup { position: relative; z-index: 1; display: flex; align-items: center; gap: 0.9rem; margin-bottom: 2.25rem; }
.qk-lockup img { width: 72px; height: 72px; display: block; }
.qk-lockup span { font-family: var(--qk-display); font-weight: 800; font-size: 1.6rem; letter-spacing: -0.03em; color: var(--qk-cream); }
.qk-ring {
  position: absolute; left: 36px; top: calc(2.5rem + 36px); width: 72px; height: 72px;
  margin: -36px 0 0 -36px; border-radius: 50%; border: 1.5px solid rgba(255, 216, 77, 0.35);
  opacity: 0; animation: qk-ripple 3.2s cubic-bezier(0.16, 1, 0.3, 1) both;
}
.qk-ring:nth-child(2) { animation-delay: 0.35s; }
.qk-ring:nth-child(3) { animation-delay: 0.7s; }
@keyframes qk-ripple { from { transform: scale(1); opacity: 0.9; } to { transform: scale(7); opacity: 0; } }
@media (prefers-reduced-motion: reduce) { .qk-ring { animation: none; } }
.qk-hero h1 {
  position: relative; z-index: 1; font-family: var(--qk-display); font-weight: 800;
  font-size: clamp(2.6rem, 6vw, 4rem); line-height: 0.98; letter-spacing: -0.035em;
  color: var(--qk-cream); margin: 0 0 1.1rem; padding: 0;
}
.qk-hero h1 em { font-style: normal; color: var(--qk-yellow); }
.qk-hero p { position: relative; z-index: 1; color: var(--qk-muted); font-size: 1.08rem; line-height: 1.6; max-width: 36rem; margin: 0; }

.qk-prompt {
  font-family: var(--qk-display); font-weight: 800; font-size: clamp(2rem, 4.5vw, 2.8rem);
  line-height: 1.05; letter-spacing: -0.03em; color: var(--qk-cream); margin: 2.75rem 0 0.4rem; padding: 0;
}

/* Answers: the question is the heading; hairlines between findings. */
.qk-q {
  font-family: var(--qk-display); font-weight: 700; font-size: 1.4rem; line-height: 1.25;
  letter-spacing: -0.02em; color: var(--qk-cream); margin: 0; padding: 0;
}
.qk-rule { border: 0; border-top: 1px solid var(--qk-line); margin: 0.5rem 0 0; }
.qk-note { color: #D9D2BE; line-height: 1.6; margin: 0; }
.qk-fail { color: var(--qk-orange); margin: 0; }

/* Quiet expanders for the SQL. */
[data-testid="stExpander"] details { border: 1px solid var(--qk-line); background: transparent; }
[data-testid="stExpander"] summary p { font-size: 0.88rem; color: var(--qk-muted); }
</style>
"""


def main() -> None:
    st.set_page_config(page_title="Quacky", page_icon=str(AVATAR), layout="centered")
    st.html(STYLE)
    load_dotenv(find_dotenv(usecwd=True))
    state = st.session_state
    state.setdefault("con", None)
    state.setdefault("history", [])
    state.setdefault("loaded", [])
    state.setdefault("total_cost", 0.0)
    state.setdefault("pending", None)

    if state.con is None:
        _welcome(state)
        return

    mode = _top_bar(state)
    if mode == "SQL":
        _sql_view(state)
    elif mode == "Schema":
        st.html("<p class='qk-meta'>This is exactly what the model reads before it writes SQL.</p>")
        st.code(state.schema, language=None)
    else:
        _ask_view(state)


def _wordmark() -> None:
    st.html(f"<div class='qk-mark'><img src='{AVATAR_URL}' alt=''><span>Quacky</span></div>")


def _welcome(state) -> None:
    st.html(f"""
    <div class="qk-hero">
      <div class="qk-ring"></div><div class="qk-ring"></div><div class="qk-ring"></div>
      <div class="qk-lockup"><img src="{AVATAR_URL}" alt=""><span>Quacky</span></div>
      <h1>Ask your data<br><em>anything.</em></h1>
      <p>Drop in a spreadsheet or a database and ask in plain English. Quacky writes the SQL,
      checks it, runs it on this machine, and shows you the answer.</p>
    </div>
    """)
    _data_form(state, compact=False)
    st.html("<p class='qk-meta'>Read-only queries. Your data stays on this machine; "
            "only your question and a few sample values go to the model.</p>")


def _data_form(state, compact: bool) -> None:
    """Upload files or type paths, then load. Used on the welcome page and in the Pond."""
    uploads = st.file_uploader("Files: CSV, Excel or SQLite", type=UPLOAD_TYPES,
                               accept_multiple_files=True)
    paths = st.text_area("Or local paths and Postgres URLs, one per line", key="paths",
                         height=68 if compact else 80,
                         placeholder="data/sales.csv\npostgresql://user@host/db")
    with st.container(horizontal=True, vertical_alignment="center"):
        if st.button("Load data", type="primary", icon=":material/arrow_downward:"):
            _load(state, uploads, paths.splitlines())
        if _sample_available() and st.button("Try the sample data", icon=":material/water_drop:"):
            _load(state, [], SAMPLE)


def _top_bar(state) -> str:
    left, right = st.columns([1, 2], vertical_alignment="center")
    with left:
        _wordmark()
    with right, st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center"):
        mode = st.segmented_control("View", MODES, default="Ask", required=True,
                                    key="mode", label_visibility="collapsed")
        files = len(state.loaded)
        with st.popover(f"Pond · {files} file{'s' if files != 1 else ''}", icon=":material/water_drop:"):
            _pond(state)

    names = " · ".join(Path(name).name for name, _ in state.loaded)
    tables = sum(count for _, count in state.loaded)
    st.html(f"<hr class='qk-rule'><p class='qk-meta'>In the pond: {html.escape(names)} "
            f"({tables} table{'s' if tables != 1 else ''})</p>")
    return mode


def _pond(state) -> None:
    for name, count in state.loaded:
        st.markdown(f":green[:material/check_circle:] {Path(name).name} "
                    f"<span class='qk-meta'>· {count} table{'s' if count != 1 else ''}</span>",
                    unsafe_allow_html=True)
    st.divider()
    st.html("<p class='qk-meta'>Loading new data replaces what is in the pond.</p>")
    _data_form(state, compact=True)
    st.divider()
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
        st.warning("Choose at least one file or path.", icon=":material/info:")
        return

    con = duckdb.connect()
    loaded = []
    for source, name in sources:
        try:
            loaded.append((name, len(load_source(con, source))))
        except (ValueError, FileNotFoundError, RuntimeError, duckdb.Error) as e:
            con.close()
            st.error(f"Could not load {name}: {e}", icon=":material/error:")
            return

    lock_down(con)  # only after every source is loaded
    if state.con is not None:
        state.con.close()
    state.con, state.loaded, state.history = con, loaded, []
    state.schema = describe_schema(con)
    st.rerun()


def _ask_view(state) -> None:
    client = make_client()
    if client is None:
        st.warning("No API key found. Put OPENROUTER_API_KEY=... in a .env file in the folder "
                   "where you start Quacky. Your own SQL still works in the SQL view.",
                   icon=":material/key:")

    if not state.history:
        st.html("<h2 class='qk-prompt'>What do you want to know?</h2>")
    with st.container():  # inside a container, the input stays here instead of the page bottom
        question = st.chat_input("Ask a question about your data", max_chars=1000,
                                 disabled=client is None)

    if not state.history and _sample_available() and client is not None:
        st.pills("Try one", SAMPLE_QUESTIONS, key="example", label_visibility="collapsed",
                 on_change=_use_example)

    question = question or state.pending
    if question and client is not None:
        state.pending = None
        with st.spinner("Quacking up some SQL..."):
            try:
                answer = ask(state.con, client, state.schema, question, model=state.get("model", MODEL),
                             provider=state.get("provider", PROVIDER), timeout_s=TIMEOUT_S, max_rows=MAX_ROWS)
            except openai.APIError as e:
                st.error(api_error_message(e), icon=":material/cloud_off:")
                return
        state.history.insert(0, answer)
        state.total_cost += answer.cost_usd
        st.rerun()

    for answer in state.history:
        _show_answer(answer)


def _use_example() -> None:
    state = st.session_state
    state.pending, state.example = state.example, None


def _show_answer(answer: Answer) -> None:
    with st.container(gap="small"):
        st.html(f"<div style='height:1.25rem'></div><h3 class='qk-q'>{html.escape(answer.question)}</h3>")
        if answer.ok:
            _show_table(answer.df)
        elif answer.attempts:
            st.html(f"<p class='qk-fail'>No answer after {len(answer.attempts)} tries. "
                    f"Try asking another way.</p>")
        if answer.note:
            st.html(f"<p class='qk-note'>{html.escape(answer.note)}</p>")
        if answer.attempts:
            tries = len(answer.attempts)
            with st.expander("SQL" if tries == 1 else f"SQL · {tries} tries", icon=":material/code:"):
                for i, attempt in enumerate(answer.attempts, start=1):
                    if attempt.error:
                        st.caption(f"Try {i} failed: {attempt.error.splitlines()[0]}")
                st.code(_pretty(answer.sql), language="sql")
        st.html(f"<p class='qk-meta'>{answer.input_tokens:,} tokens in "
                f"({answer.cached_tokens:,} cached) · {answer.output_tokens:,} out · "
                f"${answer.cost_usd:.5f}</p><hr class='qk-rule'>")


def _pretty(sql: str) -> str:
    """SQL split over several lines, for reading only. The query that ran is unchanged."""
    try:
        return sqlglot.transpile(sql, read="duckdb", write="duckdb", pretty=True)[0]
    except sqlglot.errors.SqlglotError:
        return sql


def _sql_view(state) -> None:
    sql = st.text_area("One read-only query", height=140, key="sql",
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
        st.html("<p class='qk-note'>No rows match.</p>")
        return
    st.dataframe(df, hide_index=True)
    note = f"{len(df):,} row{'s' if len(df) != 1 else ''}"
    if df.attrs.get("truncated"):
        note += f", cut at the {MAX_ROWS:,}-row limit"
    st.html(f"<p class='qk-meta'>{note}</p>")


main()
