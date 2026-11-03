"""The ask loop, tested with a fake client: no API key, no network, no cost."""

import json
from types import SimpleNamespace as NS

import pytest

from quacky.llm import MODEL, PROVIDER, ask, make_client
from quacky.schema import describe_schema

GOOD_SQL = "SELECT Country, COUNT(*) AS n FROM shop.main.customers GROUP BY 1 ORDER BY 1"


class FakeClient:
    """Returns scripted replies and records every request."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **request):
        self.requests.append(request)
        finish_reason, text = self.replies.pop(0)
        usage = NS(prompt_tokens=1000, completion_tokens=50, prompt_tokens_details=NS(cached_tokens=900), cost=0.0002)
        return NS(choices=[NS(finish_reason=finish_reason, message=NS(content=text))], usage=usage)


def reply(sql, note="note"):
    return ("stop", json.dumps({"sql": sql, "note": note}))


@pytest.fixture
def schema(locked):
    return describe_schema(locked)


def test_good_sql_is_run(locked, schema):
    client = FakeClient([reply(GOOD_SQL, "Counts customers per country.")])
    answer = ask(locked, client, schema, "How many customers per country?")
    assert answer.ok and len(answer.attempts) == 1
    assert answer.df.values.tolist() == [["Brazil", 1], ["Canada", 1], ["USA", 1]]
    assert answer.note == "Counts customers per country."
    assert answer.cost_usd == pytest.approx(0.0002)


def test_request_is_pinned_to_one_provider(locked, schema):
    client = FakeClient([reply(GOOD_SQL)])
    ask(locked, client, schema, "q")
    request = client.requests[0]
    assert request["model"] == MODEL
    assert request["extra_body"]["provider"] == {
        "order": [PROVIDER], "allow_fallbacks": False, "require_parameters": True,
    }
    assert request["response_format"]["type"] == "json_schema"
    assert "shop.main.customers" in request["messages"][0]["content"]  # schema is in the prompt


def test_failed_sql_is_sent_back_and_fixed(locked, schema):
    client = FakeClient([reply("SELECT Nation FROM shop.main.customers"), reply(GOOD_SQL)])
    answer = ask(locked, client, schema, "q")
    assert answer.ok and len(answer.attempts) == 2
    assert "Nation" in answer.attempts[0].error
    retry = client.requests[1]["messages"]
    assert [m["role"] for m in retry] == ["system", "user", "assistant", "user"]
    assert "failed" in retry[-1]["content"] and "Nation" in retry[-1]["content"]


def test_gives_up_after_max_attempts(locked, schema):
    client = FakeClient([reply("DROP TABLE countries")] * 3)
    answer = ask(locked, client, schema, "q")
    assert not answer.ok and len(answer.attempts) == 3
    assert all("Only SELECT" in a.error for a in answer.attempts)


def test_unanswerable_question_runs_no_sql(locked, schema):
    client = FakeClient([reply("", "There is no weather data.")])
    answer = ask(locked, client, schema, "What is the weather?")
    assert not answer.ok and answer.attempts == [] and "weather" in answer.note


@pytest.mark.parametrize("finish_reason, text, note", [
    ("stop", "SELECT 1", "valid JSON"),
    ("length", '{"sql": "SEL', "cut off"),
])
def test_bad_replies_give_a_clear_note(locked, schema, finish_reason, text, note):
    answer = ask(locked, FakeClient([(finish_reason, text)]), schema, "q")
    assert not answer.ok and note in answer.note


def test_no_key_means_no_client(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert make_client() is None
