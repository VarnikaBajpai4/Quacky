"""Command-line interface: load sources, lock DuckDB, show the schema, answer questions.

Usage: python -m quacky.cli <source> [<source> ...] [--timeout S] [--max-rows N]
                              [--model M] [--provider P]

Type a question in plain English, or `.sql <query>` to run your own SQL.
The API key is read from OPENROUTER_API_KEY (a .env file in the project works).
"""

import argparse
import sys
from urllib.parse import urlparse

import duckdb
import openai
from dotenv import find_dotenv, load_dotenv

from quacky.connectors import POSTGRES_PREFIXES, load_source
from quacky.llm import MODEL, PROVIDER, Answer, ask, make_client
from quacky.runner import QueryTimeoutError, UnsafeQueryError, lock_down, run_safe
from quacky.schema import describe_schema

SHOWN_ROWS = 50
HELP = "Ask a question in plain English. Commands: .sql <query>  .schema  .help  .quit"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quacky", description="Ask Quacky about your data.")
    parser.add_argument("sources", nargs="+", help="CSV, XLSX or SQLite file, or a postgresql:// URL")
    parser.add_argument("--timeout", type=float, default=10, help="seconds per query (default 10)")
    parser.add_argument("--max-rows", type=int, default=1000, help="rows per query (default 1000)")
    parser.add_argument("--model", default=MODEL, help=f"OpenRouter model (default {MODEL})")
    parser.add_argument("--provider", default=PROVIDER, help=f"pinned provider endpoint (default {PROVIDER})")
    args = parser.parse_args(argv)
    # Read .env from the folder the user runs Quacky in (or a parent), not from
    # wherever the package is installed.
    load_dotenv(find_dotenv(usecwd=True))
    client = make_client()

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
    schema_text = describe_schema(con)
    print(schema_text)
    print()
    print(HELP)

    while True:
        try:
            line = input("quacky> ").strip()
        except (EOFError, KeyboardInterrupt):  # Ctrl+D or Ctrl+C at the prompt
            print()
            return 0

        if not line:
            continue
        if line in (".quit", ".exit"):
            return 0
        if line == ".help":
            print(HELP)
            continue
        if line == ".schema":
            print(schema_text)
            continue
        if line.startswith(".sql "):
            _run_sql(con, line[len(".sql "):], args)
            continue
        if client is None:
            print("No API key: put OPENROUTER_API_KEY=... in the .env file. Until then, use .sql <query>.")
            continue

        try:
            answer = ask(con, client, schema_text, line, model=args.model, provider=args.provider,
                         timeout_s=args.timeout, max_rows=args.max_rows)
        except openai.AuthenticationError:
            print("API error: no valid API key. Put OPENROUTER_API_KEY=... in the .env file.")
        except openai.RateLimitError:
            print("API error: rate limit reached. Wait a moment and try again.")
        except openai.APIConnectionError:
            print("API error: cannot reach the API. Check your internet connection.")
        except openai.APIStatusError as e:
            print(f"API error {e.status_code}: {e.message}")
        else:
            _print_answer(answer, args.max_rows)


def _run_sql(con, sql: str, args) -> None:
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


def _print_answer(answer: Answer, max_rows: int) -> None:
    for i, attempt in enumerate(answer.attempts, start=1):
        print(f"SQL (try {i}): {attempt.sql}")
        if attempt.error:
            print(f"  failed: {attempt.error.splitlines()[0]}")
    if answer.note:
        print(f"Note: {answer.note}")
    if answer.ok:
        _print_result(answer.df, max_rows)
    elif answer.attempts:
        print(f"No answer after {len(answer.attempts)} tries.")
    print(f"(tokens: {answer.input_tokens} in, {answer.cached_tokens} cached, "
          f"{answer.output_tokens} out; cost ${answer.cost_usd:.5f})")


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
