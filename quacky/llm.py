"""LLM step: turn an English question into DuckDB SQL, run it, and fix errors.

The model gets the schema text (from schema.py) and the question, and returns
one SQL query as structured JSON. The query always goes through the safe
runner. If it fails, the error goes back to the model, which tries again, up
to MAX_ATTEMPTS times.

The model is called through OpenRouter (OpenAI-compatible API). The request is
pinned to one provider endpoint with no fallbacks, so every run uses the same
model weights and precision, and results stay comparable between runs.
"""

import json
import os
from dataclasses import dataclass, field

import duckdb
import openai
import pandas as pd

from quacky.runner import QueryTimeoutError, UnsafeQueryError, run_safe

OPENROUTER_URL = "https://openrouter.ai/api/v1"
MODEL = "deepseek/deepseek-v4.1-flash"
PROVIDER = "deepinfra/fp8"  # full endpoint slug: one provider, one precision
MAX_ATTEMPTS = 3

INSTRUCTIONS = """You write DuckDB SQL that answers a question about the user's data.

Rules:
- Write exactly one read-only SELECT query. WITH and UNION are fine. Never write anything that changes data or settings.
- Use only the tables and columns listed below. Copy each name exactly as shown, including any double quotes.
- Tables listed without a dot are in the default database. Write the others with their full name, for example chinook.main.invoices.
- The data can be messy. Check the example values before you assume a format, a spelling or a unit.
- If the tables cannot answer the question, return an empty string as "sql" and say why in "note".
- In "note", write one short plain sentence about what the result shows, plus any assumption a reader must know. Do not describe your reasoning steps.

Tables:

"""

# Structured output: the reply must be JSON with exactly these keys.
SQL_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "sql_answer",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["sql", "note"],
            "additionalProperties": False,
        },
    },
}


@dataclass
class Attempt:
    sql: str
    error: str | None = None


@dataclass
class Answer:
    question: str
    attempts: list[Attempt] = field(default_factory=list)
    df: pd.DataFrame | None = None
    note: str = ""
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def sql(self) -> str | None:
        return self.attempts[-1].sql if self.attempts else None

    @property
    def ok(self) -> bool:
        return self.df is not None


def make_client(api_key: str | None = None) -> openai.OpenAI | None:
    """OpenRouter client, or None if there is no key (OPENROUTER_API_KEY)."""
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    return openai.OpenAI(base_url=OPENROUTER_URL, api_key=key) if key else None


def api_error_message(error: openai.APIError) -> str:
    """A short, clear message for an API error, for the CLI and the UI."""
    if isinstance(error, openai.AuthenticationError):
        return "API error: no valid API key. Put OPENROUTER_API_KEY=... in the .env file."
    if isinstance(error, openai.RateLimitError):
        return "API error: rate limit reached. Wait a moment and try again."
    if isinstance(error, openai.APIConnectionError):
        return "API error: cannot reach the API. Check your internet connection."
    if isinstance(error, openai.APIStatusError):
        return f"API error {error.status_code}: {error.message}"
    return f"API error: {error}"


def ask(
    con: duckdb.DuckDBPyConnection,
    client: openai.OpenAI,
    schema_text: str,
    question: str,
    model: str = MODEL,
    provider: str = PROVIDER,
    max_attempts: int = MAX_ATTEMPTS,
    timeout_s: float = 10,
    max_rows: int = 1000,
) -> Answer:
    """Answer one question. API errors (auth, network, rate limit) are raised."""
    messages = [
        {"role": "system", "content": INSTRUCTIONS + schema_text},
        {"role": "user", "content": question},
    ]
    routing = {
        "order": [provider],
        "allow_fallbacks": False,  # fail instead of silently using another provider
        "require_parameters": True,  # the endpoint must support response_format
    }
    answer = Answer(question=question)

    for _ in range(max_attempts):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format=SQL_FORMAT,
            max_tokens=4000,
            extra_body={"provider": routing},
        )
        _add_usage(answer, response.usage)

        choice = response.choices[0]
        if choice.finish_reason == "length":
            answer.note = "The model's reply was cut off before it finished."
            return answer
        try:
            reply = json.loads(choice.message.content or "")
            sql, answer.note = reply["sql"].strip(), reply["note"]
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
            answer.note = "The model did not return valid JSON."
            return answer
        if not sql:  # the model says the tables cannot answer this
            return answer

        try:
            answer.df = run_safe(con, sql, timeout_s=timeout_s, max_rows=max_rows)
        except (UnsafeQueryError, QueryTimeoutError, duckdb.Error) as e:
            answer.attempts.append(Attempt(sql=sql, error=str(e)))
            messages.append({"role": "assistant", "content": choice.message.content})
            messages.append({"role": "user", "content": f"That SQL failed:\n{e}\n\nFix it and return the corrected query."})
            continue

        answer.attempts.append(Attempt(sql=sql))
        return answer

    return answer


def _add_usage(answer: Answer, usage) -> None:
    if usage is None:
        return
    answer.input_tokens += usage.prompt_tokens or 0
    answer.output_tokens += usage.completion_tokens or 0
    details = usage.prompt_tokens_details
    answer.cached_tokens += (details.cached_tokens or 0) if details else 0
    answer.cost_usd += getattr(usage, "cost", None) or 0.0  # OpenRouter adds the real cost
