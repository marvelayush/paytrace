"""Column-mapping suggesters: fuzzy accuracy, LLM validation and fallback, and no PII sent to the AI."""

import json
from pathlib import Path

import httpx
import pytest

from app.sample_data.formats import FORMAT_CHANGED, FORMATS
from app.services.canonical import CANONICAL_FIELDS
from app.services.mapping_ai import AI_UNAVAILABLE, FuzzySuggester, LLMSuggester, get_suggester
from app.services.parsing import headers_of, read_table, sample_rows

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data"


def _file(layout):
    folder = SAMPLE_DIR / "format_changed" if layout is FORMAT_CHANGED else SAMPLE_DIR
    frame = read_table(folder / layout.filename, max_rows=20)
    return headers_of(frame), sample_rows(frame, 20)


@pytest.mark.parametrize("layout", [*FORMATS, FORMAT_CHANGED], ids=lambda layout: layout.filename)
def test_fuzzy_suggester_finds_every_required_field(layout):
    headers, rows = _file(layout)
    suggestion = FuzzySuggester().suggest(layout.file_kind, headers, rows)
    truth = layout.mapping()["columns"]
    required = [spec.name for spec in CANONICAL_FIELDS[layout.file_kind] if spec.required]
    assert {name: suggestion.fields[name].source_column for name in required} == {name: truth[name] for name in required}


def test_fuzzy_suggester_maps_the_changed_format_completely():
    headers, rows = _file(FORMAT_CHANGED)
    suggestion = FuzzySuggester().suggest("settlement", headers, rows)
    assert suggestion.columns() == FORMAT_CHANGED.mapping()["columns"]


# ---------- LLM with a fake Gemini ----------

def _gemini_reply(fields: dict) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(fields)}]}}]}


def _llm(handler) -> LLMSuggester:
    return LLMSuggester(api_key="test-key", model="test-model", client=httpx.Client(transport=httpx.MockTransport(handler)))


def _good_answer(layout) -> dict:
    truth = layout.mapping()["columns"]
    return {
        spec.name: {"source_column": truth.get(spec.name), "confidence": 0.93, "reason": "Header matches"}
        for spec in CANONICAL_FIELDS[layout.file_kind]
    }


def test_llm_answer_is_used_when_valid():
    headers, rows = _file(FORMAT_CHANGED)
    suggester = _llm(lambda request: httpx.Response(200, json=_gemini_reply(_good_answer(FORMAT_CHANGED))))
    suggestion = suggester.suggest("settlement", headers, rows)
    assert suggestion.engine == "llm"
    assert suggestion.notice is None
    assert suggestion.columns() == FORMAT_CHANGED.mapping()["columns"]


@pytest.mark.parametrize(
    "reply",
    [
        httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "not json {"}]}}]}),
        httpx.Response(500, json={"error": "boom"}),
        httpx.Response(200, json={"unexpected": True}),
    ],
    ids=["invalid-json", "server-error", "wrong-shape"],
)
def test_llm_failures_fall_back_to_fuzzy_with_notice(reply):
    headers, rows = _file(FORMAT_CHANGED)
    suggestion = _llm(lambda request: reply).suggest("settlement", headers, rows)
    assert suggestion.engine == "fuzzy"
    assert suggestion.notice == AI_UNAVAILABLE
    assert suggestion.fields["net"].source_column == "Amount Credited"


def test_llm_timeout_falls_back():
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    headers, rows = _file(FORMAT_CHANGED)
    assert _llm(timeout).suggest("settlement", headers, rows).engine == "fuzzy"


def test_llm_naming_a_column_not_in_the_file_falls_back():
    answer = _good_answer(FORMAT_CHANGED)
    answer["net"]["source_column"] = "Invented Column"
    headers, rows = _file(FORMAT_CHANGED)
    suggestion = _llm(lambda request: httpx.Response(200, json=_gemini_reply(answer))).suggest("settlement", headers, rows)
    assert suggestion.engine == "fuzzy"


def test_llm_confidence_out_of_range_falls_back():
    answer = _good_answer(FORMAT_CHANGED)
    answer["net"]["confidence"] = 7
    headers, rows = _file(FORMAT_CHANGED)
    assert _llm(lambda request: httpx.Response(200, json=_gemini_reply(answer))).suggest("settlement", headers, rows).engine == "fuzzy"


def test_no_raw_personal_data_is_sent_to_the_ai():
    layout = next(f for f in FORMATS if f.filename == "website_orders.csv")
    headers, rows = _file(layout)
    sent: list[str] = []

    def capture(request: httpx.Request) -> httpx.Response:
        sent.append(request.content.decode("utf-8"))
        return httpx.Response(200, json=_gemini_reply(_good_answer(layout)))

    _llm(capture).suggest("orders", headers, rows)
    payload = sent[0]
    for row in rows[:5]:
        assert row["Customer Name"] not in payload
        assert row["Customer Phone"] not in payload
        assert row["Shipping Address"] not in payload
    assert rows[5]["Order Number"] not in payload  # only five sample rows go out
    assert "test-key" not in payload  # the key travels in a header, not the body


def test_without_api_key_fuzzy_is_used_and_says_so():
    headers, rows = _file(FORMAT_CHANGED)
    suggestion = get_suggester(None, "any").suggest("settlement", headers, rows)
    assert (suggestion.engine, suggestion.notice) == ("fuzzy", AI_UNAVAILABLE)
