"""End-to-end: run the real CLI as a separate process, the way a user does."""

import os
import subprocess
import sys

import pytest


def run_cli(args, cwd, stdin="", key=None):
    env = {k: v for k, v in os.environ.items() if k not in ("OPENROUTER_API_KEY", "PYTHONPATH")}
    if key:
        env["OPENROUTER_API_KEY"] = key
    # Run from an empty temp folder outside the project, so a developer's real
    # .env (and API key) is never found and no test can spend money.
    return subprocess.run(
        [sys.executable, "-m", "quacky.cli", *args], input=stdin, capture_output=True,
        text=True, env=env, cwd=cwd, timeout=120,
    )


@pytest.fixture
def session(sources, tmp_path):
    """Run one CLI session with the test sources and the given input lines."""
    def run(*lines, key=None):
        return run_cli(sources + ["--timeout", "2"], tmp_path, "\n".join([*lines, ".quit"]) + "\n", key)
    return run


def test_loads_sources_and_prints_the_schema(session):
    result = session()
    assert result.returncode == 0
    assert "Loaded" in result.stdout and "Table shop.main.invoices (4 rows)" in result.stdout


def test_phase_1_safety_checks_through_the_cli(session):
    out = session(
        ".sql SELECT COUNT(*) FROM shop.main.invoices",
        ".sql DROP TABLE countries",
        ".sql SELECT 1; DROP TABLE countries",
        ".sql SELECT * FROM read_csv('/etc/passwd')",
        ".sql SET enable_external_access = true",
    ).stdout
    assert "(1 row(s))" in out
    assert "Rejected: Only SELECT queries are allowed, got DROP." in out
    assert "Rejected: Expected exactly one statement, got 2." in out
    assert "disabled by configuration" in out
    assert "Rejected: Only SELECT queries are allowed, got SET." in out


def test_cross_source_join_through_the_cli(session):
    out = session('.sql SELECT c.Name, co.Region FROM shop.main.customers c JOIN countries co ON co."Country Name" = c.Country ORDER BY 1').stdout
    assert "Ana Americas" in out and "(2 row(s))" in out


def test_question_without_a_key_explains_what_to_do(session):
    assert "No API key" in session("How many invoices are there?").stdout


def test_question_with_a_bad_key_gives_a_clean_api_error(session):
    out = session("How many invoices are there?", key="sk-or-not-a-real-key").stdout
    assert "API error" in out and "Traceback" not in out


def test_missing_source_stops_with_exit_code_1(tmp_path):
    result = run_cli([str(tmp_path / "missing.csv")], tmp_path)
    assert result.returncode == 1 and "File not found" in result.stderr


def test_postgres_password_is_never_printed(tmp_path):
    result = run_cli(["postgresql://alice:S3cretPw@127.0.0.1:1/shop"], tmp_path)
    assert result.returncode == 1
    assert "S3cretPw" not in result.stdout + result.stderr
    assert "alice:***@" in result.stderr
