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

`data/` is gitignored. Put these files there:

| File | Source |
|---|---|
| `data/chinook.db` | Chinook sample database (SQLite) |
| `data/sales.csv` | Any public CSV |
| `data/messy.xlsx` | Hand-made: 2 sheets, title row above headers, one empty column |

## Known issues

_To be filled in during Phase 1._
