# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Two groups, equally: people who have data in spreadsheets or databases but cannot write SQL, and developers or analysts who know SQL and want answers faster. Both run Quacky on their own machine, often late in the evening, to answer questions about their own data.

## Product Purpose
Quacky lets you ask questions about your data in plain English. It loads CSV, Excel, SQLite and Postgres into one DuckDB workspace, has an LLM write one read-only SQL query, checks and runs that query safely, and shows the answer. Success: the right answer table, fast, with the SQL visible and easy to check or copy.

## Positioning
Local-first and safety-first: the data stays on the user's machine, every query passes four safety layers (parse check, DuckDB lock, timeout, row limit), and the user pays only their own small API costs. The roadmap replaces the API model with a small fine-tuned model that runs fully offline.

## Operating Context
Started with `quacky-ui` (Streamlit, localhost only) or the `quacky` CLI. A session: load files or paths, ask several questions, read the answer table, check the SQL, sometimes run SQL by hand, glance at the schema. Each answer shows its token use and cost.

## Capabilities and Constraints
- Must stay a Streamlit app, simple to maintain; no custom frontend framework.
- Local-only: no hosting, no accounts, no telemetry.
- Sources: .csv, .xlsx, .db/.sqlite/.sqlite3, postgresql:// URLs. Read-only SELECT queries only.
- Model: OpenRouter, pinned to one provider endpoint; cost per question is shown.

## Brand Commitments
- Name: Quacky ("quack" → query; DuckDB has a duck logo). Tagline: "Ask Quacky anything about your data."
- Avatar: `assets/quacky-avatar.svg`, a yellow duck (#FFD84D body, #F5C22E wing, #FFF4D6 background disc).
- Personality: warm and playful in copy, empty states and colour; the work area stays clean and precise.

## Evidence on Hand
Sample data (local, gitignored): Chinook music store SQLite, a countries CSV, a generated messy Excel file. No users, testimonials or benchmarks yet; do not invent them. Phase 3 will produce real accuracy numbers.

## Product Principles
1. The answer comes first; the SQL is always one glance away, never hidden.
2. Show what happened: the SQL, failed tries, cost. No magic.
3. Safe by default; safety messages are plain, never alarming.
4. Playful voice, serious results.
