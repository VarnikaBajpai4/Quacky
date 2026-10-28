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
