# Quacky 🦆

> Ask Quacky anything about your data.

Plug-and-play "ask your data" tool. Hook it onto any source (Excel, CSV, SQLite, Postgres), ask questions in plain language, get answers. Name: quack → query, and DuckDB (the engine) has a duck logo. Avatar: `quacky-avatar.svg`.

## Why this project

Learning project to grow as an MLE. My earlier project already covers classic ML on security (a detector). Quacky covers the gap: LLM fine-tuning, RL, LLM evals, and serving.

## Architecture

1. **Connectors** — load every source into DuckDB.
2. **Schema reader** — tables, columns, types, sample rows → text for the model.
3. **Model** — question + schema → DuckDB SQL.
4. **Safe runner** — read-only, SELECT only, timeout, row limit.

## Roadmap (~2–3 months part-time)

| Phase | What | Time | Learn |
|---|---|---|---|
| 0 | Setup, get Spider + BIRD datasets, make messy Excel files | 2–3 days | Datasets |
| 1 | Plug-and-play core (no ML): connectors, schema reader, safe runner, CLI | 1 week | Data engineering |
| 2 | First version with an API LLM, error-retry loop, Streamlit UI | 1 week | Prompting, agent loops |
| 3 | Eval: execution accuracy, split train/test **by database**, failure groups | 1 week | Eval design |
| 4 | Fine-tune small open coder model (1.5B–3B) with LoRA (TRL + PEFT / Unsloth), W&B | 1–2 weeks | LLM fine-tuning |
| 5 | RL with GRPO (TRL `GRPOTrainer`), reward = correct result, watch reward hacking | 2 weeks | RL for LLMs |
| 6 | Messy Excel, table retrieval for large DBs, ask follow-up on unclear questions | 1–2 weeks | Retrieval, dirty data |
| 7 | Serve with vLLM + FastAPI, quantize, speed/cost vs API, strong README | 1 week | Serving, MLOps |

## Phase 1 — exact steps

**Goal:** load CSV, Excel, SQLite, Postgres into DuckDB, show schema, run SQL safely.

### Structure
```
quacky/
├── quacky/
│   ├── __init__.py
│   ├── connectors.py
│   ├── schema.py
│   ├── runner.py
│   └── cli.py
├── data/
├── requirements.txt
└── README.md
```
Python 3.11+, venv, `requirements.txt`: duckdb, pandas, openpyxl, sqlglot. `.gitignore`: `.venv/`, `data/`.

### Step 2 — Test data
- Chinook SQLite DB
- A public CSV (e.g. Kaggle sales)
- A messy Excel I make: 2 sheets, title row above headers, one empty column

### Step 3 — `load_source(con, source) -> list[str]`
| Source | How |
|---|---|
| `.csv` | `CREATE TABLE t AS SELECT * FROM read_csv_auto('path')` |
| `.xlsx` | `pd.read_excel(path, sheet_name=None)` → `con.register` → `CREATE TABLE` per sheet |
| `.db`/`.sqlite` | `ATTACH 'path' AS name (TYPE sqlite, READ_ONLY)` |
| `postgresql://` | `INSTALL postgres; LOAD postgres;` then `ATTACH 'url' AS name (TYPE postgres, READ_ONLY)` |

Clean table names. Messy Excel headers (`Unnamed: 1`) are expected → note as known issue, fix in Phase 6.
**Done:** `SHOW ALL TABLES` lists everything.

### Step 4 — `describe_schema(con, sample_rows=3) -> str`
Use `information_schema.columns` + `LIMIT 3` samples + row count. Cut long values to ~50 chars.

### Step 5 — `run_safe(con, sql, timeout_s=10, max_rows=1000)`
1. Parse with `sqlglot.parse(sql, read="duckdb")`: exactly one statement, SELECT/UNION only. No regex.
2. After loading: `SET enable_external_access = false` and `SET lock_configuration = true` (else `SELECT * FROM read_csv('/etc/passwd')` works).
3. Timeout: `threading.Timer` → `con.interrupt()`.
4. Row limit: `fetchmany(max_rows)`.

**Safety tests:**
| Query | Expected |
|---|---|
| `SELECT COUNT(*) FROM chinook.main.invoices` | works |
| `DROP TABLE sales` | rejected |
| `SELECT 1; DROP TABLE sales` | rejected |
| `SELECT * FROM read_csv('/etc/passwd')` | rejected/fails |
| `SET enable_external_access = true` | rejected |
| slow triple self cross join | stops at timeout |

### Step 6 — CLI
`python -m quacky.cli data/chinook.db data/sales.csv data/messy.xlsx` → load, lock, print schema, SQL loop.
**Done:** a join across two different sources works.

### Phase 1 checklist
- [ ] All source types load (Postgres via free Neon/Supabase, or skip)
- [ ] Schema printout is clear
- [ ] All 6 safety tests pass
- [ ] Cross-source join works
- [ ] README lists known issues
- [ ] Committed to Git

## Later project ideas
- **Potion Lab** — RL on an original multi-turn deduction game.
- **Certificate watchtower** — CT log stream anomaly + phishing domain detection (eMudhra incident, Oct 2026).
- **Scam Shield** — on-device scam message detector (distillation, drift).
