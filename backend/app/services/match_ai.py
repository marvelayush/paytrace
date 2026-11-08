"""AI ranking of suggested orders for partner lines that arrived without an order ID.

The rules (`review_queue.shortlist`) pick at most five candidate orders per line. The ranker only orders
those candidates: it can never invent an order, and nothing it says links a line to an order. A finance
executive accepts or rejects every suggestion (brief: "never closed automatically").

Two implementations behind one interface:
- `GeminiRanker` sends the line and its candidates (amounts, dates, AWB, partner: no customer data at all)
  and asks for the best candidate with a confidence and a one-line reason. JSON-structured output, validated.
- `RuleRanker` keeps the rule order and says why the AI was not used. Any AI failure falls back to it.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Protocol

import httpx
from pydantic import BaseModel, Field

from app.services.mapping_ai import RETRY_STATUSES, _answer_text

logger = logging.getLogger(__name__)

AI_NO_KEY = "AI not configured: ranked by the rules"
AI_UNAVAILABLE = "AI unavailable: ranked by the rules"
AI_INVALID = "AI answer could not be used: ranked by the rules"
BATCH_SIZE = 8  # lines per request: one call ranks several lines, within the model's quick-answer range

# Only these fields ever leave PayTrace. Customer names and phones are not among them (DPDP Act 2023).
LINE_FIELDS = ("kind", "partner", "line_date", "gross_rupees", "amount_rupees", "awb", "reference")
CANDIDATE_FIELDS = ("order_id", "order_date", "delivered_date", "due_date", "value_rupees", "expected_net_rupees", "awb", "payment_mode",
                    "days_from_due", "amount_diff_rupees")


@dataclass
class RankItem:
    line_id: int
    line: dict  # LINE_FIELDS
    candidates: list[dict]  # CANDIDATE_FIELDS, best rule score first


@dataclass
class Ranking:
    order_id: str | None
    confidence: float
    reason: str


@dataclass
class RankOutcome:
    engine: str  # "llm" or "rules"
    rankings: dict[int, Ranking] = field(default_factory=dict)  # line_id -> AI ranking (empty for rules)
    notes: dict[int, str] = field(default_factory=dict)  # line_id -> why the AI was not used for it


class MatchRanker(Protocol):
    def rank(self, items: list[RankItem]) -> RankOutcome: ...


class RuleRanker:
    """No AI: the rule order stands. `note` tells the user why."""

    def __init__(self, note: str = AI_NO_KEY) -> None:
        self.note = note

    def rank(self, items: list[RankItem]) -> RankOutcome:
        return RankOutcome(engine="rules", notes={item.line_id: self.note for item in items})


def safe_payload(item: RankItem) -> dict:
    """The exact data sent for one line: whitelisted fields only."""
    return {
        "line_id": item.line_id,
        "line": {name: item.line.get(name) for name in LINE_FIELDS},
        "candidates": [{name: candidate.get(name) for name in CANDIDATE_FIELDS} for candidate in item.candidates],
    }


def build_prompt(items: list[RankItem]) -> str:
    payload = [safe_payload(item) for item in items]
    return (
        "You help an Indian D2C brand's finance team match partner payment lines that arrived without an order ID.\n"
        "Each line below comes with candidate orders chosen by rules (same partner, amount within tolerance, paid in a "
        "plausible window, not yet paid). Pick the single most likely candidate for each line, or null if none fits.\n"
        "Settlement lines: gross is the sale value; net is what was paid after commission, fees and taxes. "
        "COD remittance lines: amount is the cash collected, usually the full order value.\n"
        "due_date is when this partner should have paid for the order; days_from_due is the line date minus it; "
        "amount_diff_rupees is the line amount minus the order amount it is compared with.\n"
        "Payment usually arrives near the due date. Two candidates with the same value and similar dates are genuinely "
        "ambiguous: say so and keep confidence below 0.7.\n"
        "Confidence is 0 to 1. Reason: one sentence, at most 20 words, naming the deciding evidence.\n\n"
        f"Lines: {json.dumps(payload, ensure_ascii=False, default=str)}"
    )


RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "results": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "line_id": {"type": "INTEGER"},
                    "order_id": {"type": "STRING", "nullable": True},
                    "confidence": {"type": "NUMBER"},
                    "reason": {"type": "STRING"},
                },
                "required": ["line_id", "order_id", "confidence", "reason"],
            },
        }
    },
    "required": ["results"],
}


class _Answer(BaseModel):
    line_id: int
    order_id: str | None
    confidence: float = Field(ge=0, le=1)
    reason: str


class GeminiRanker:
    def __init__(self, api_key: str, model: str, thinking_level: str | None = None, timeout_seconds: float = 20.0,
                 client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self.thinking_level = thinking_level
        self.client = client or httpx.Client(timeout=timeout_seconds)

    def rank(self, items: list[RankItem]) -> RankOutcome:
        outcome = RankOutcome(engine="llm")
        for start in range(0, len(items), BATCH_SIZE):
            batch = items[start: start + BATCH_SIZE]
            try:
                answers = self._ask(batch)
            except Exception as error:  # noqa: BLE001 - every failure has the same safe answer
                # The kind of failure only: never the payload or the key.
                logger.warning("AI match ranking failed (%s); using rule order", type(error).__name__)
                outcome.notes.update({item.line_id: AI_UNAVAILABLE for item in batch})
                continue
            for item in batch:
                ranking = _validated(item, answers.get(item.line_id))
                if ranking is None:
                    outcome.notes[item.line_id] = AI_INVALID
                else:
                    outcome.rankings[item.line_id] = ranking
        if not outcome.rankings:
            outcome.engine = "rules"
        return outcome

    def _ask(self, batch: list[RankItem]) -> dict[int, _Answer]:
        generation_config: dict = {"temperature": 0, "responseMimeType": "application/json", "responseSchema": RESPONSE_SCHEMA}
        if self.thinking_level:
            generation_config["thinkingConfig"] = {"thinkingLevel": self.thinking_level}
        body = {"contents": [{"role": "user", "parts": [{"text": build_prompt(batch)}]}], "generationConfig": generation_config}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        response = self.client.post(url, json=body, headers={"x-goog-api-key": self.api_key})
        if response.status_code in RETRY_STATUSES:
            response = self.client.post(url, json=body, headers={"x-goog-api-key": self.api_key})
        response.raise_for_status()
        raw = json.loads(_answer_text(response.json()))
        answers: dict[int, _Answer] = {}
        for entry in raw.get("results", []):
            try:
                answer = _Answer.model_validate(entry)
            except ValueError:
                continue
            answers[answer.line_id] = answer
        return answers


def _validated(item: RankItem, answer: _Answer | None) -> Ranking | None:
    """Accept the AI's pick only if it is one of this line's candidates (or an explicit 'none fits')."""
    if answer is None:
        return None
    candidate_ids = {candidate["order_id"] for candidate in item.candidates}
    order_id = (answer.order_id or "").strip() or None
    if order_id is not None and order_id not in candidate_ids:
        return None
    return Ranking(order_id=order_id, confidence=round(answer.confidence, 2), reason=answer.reason.strip()[:300])


def get_ranker(api_key: str | None, model: str, thinking_level: str | None = None) -> MatchRanker:
    return GeminiRanker(api_key, model, thinking_level) if api_key else RuleRanker(AI_NO_KEY)
