<p align="center">
  <img src="assets/quacky-avatar.svg" width="140" alt="Quacky the duck">
</p>

<h1 align="center">Quacky</h1>

<p align="center"><em>Ask Quacky anything about your data.</em></p>

Plug-and-play "ask your data" tool. Connect a source (CSV, Excel, SQLite, Postgres), ask a question in plain English, and Quacky writes DuckDB SQL, runs it safely, and returns the answer.

> **Status:** Phase 1 — plug-and-play core (connectors, schema reader, safe runner, CLI). No ML yet.

## Setup

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
python -m quacky.cli data/chinook.db data/countries.csv data/messy.xlsx
```

Quacky loads every source, locks DuckDB (no file access, no config changes), prints the schema, and opens a prompt. Type one SQL query per line. Commands: `.schema`, `.help`, `.quit`. Options: `--timeout` (seconds, default 10), `--max-rows` (default 1000).

```
quacky> SELECT COUNT(*) FROM chinook.main.invoices
 count_star()
          412
(1 row(s))
quacky> DROP TABLE countries
Rejected: Only SELECT queries are allowed, got DROP.
```

## Test data

`data/` is gitignored. Rebuild it with:

```bash
curl -L -o data/chinook.zip https://www.sqlitetutorial.net/wp-content/uploads/2018/03/chinook.zip
unzip -o data/chinook.zip -d data && rm data/chinook.zip
curl -L -o data/countries.csv https://raw.githubusercontent.com/datasets/country-codes/main/data/country-codes.csv
python scripts/make_messy_xlsx.py
```

| File | Source | Tests |
|---|---|---|
| `data/chinook.db` | [sqlitetutorial.net Chinook](https://www.sqlitetutorial.net/sqlite-sample-database/) (lowercase plural table names, e.g. `invoices`) | SQLite ATTACH, multi-table schema |
| `data/countries.csv` | [datasets/country-codes](https://github.com/datasets/country-codes) | CSV loading; joins to `customers.Country` |
| `data/messy.xlsx` | `scripts/make_messy_xlsx.py` | Title row above headers, empty column; `Targets` sheet joins to `employees.EmployeeId` |

## Known issues

- **Country names differ across sources.** Chinook uses `USA`, `United Kingdom`, `Czech Republic`; the countries CSV uses other names (e.g. `Czechia`). A join on country name drops these rows.
- **Excel header detection.** `messy.xlsx` sheet `Sales` has a title row, so a default read gives headers like `Q3 Sales Report`, `Unnamed: 1`, and numbers typed as text. Planned fix: Phase 6.
- **Schema size.** Every table goes into the schema text (14 test tables ≈ 8,000 characters). Large databases will not fit in a prompt. Planned fix: table retrieval in Phase 6.
- **Sample values repeat.** Examples are the first 3 rows, not 3 distinct values (e.g. `Quarter e.g. Q3, Q3, Q3`).
- **The parse check is strict.** Some valid read-only DuckDB syntax (`SUMMARIZE`, `PIVOT`, `DESCRIBE`) is rejected, because the runner allows only plain SELECT and set operations.
- **Postgres is not tested yet.** The connector is written, but no Postgres server was available for testing.
- **One line per query.** The CLI reads one line at a time, so multi-line SQL must be typed on one line.
- **No memory limit.** The timeout stops long queries, but a query can still use a lot of memory before it is stopped.
