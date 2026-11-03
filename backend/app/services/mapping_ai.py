"""Column-mapping suggestions: which column in a partner's file holds each canonical field.

Two implementations behind one interface:
- `LLMSuggester` asks Google Gemini, with JSON-structured output, given only the headers and five
  sample rows with personal data masked. The answer is validated; on a missing key, timeout, HTTP
  error, invalid JSON or a column name that is not in the file it falls back to the fuzzy suggester
  and says so ("AI unavailable, showing best guesses").
- `FuzzySuggester` compares header names with known synonyms (rapidfuzz) and checks that the sample
  values look like the right type (dates parse, amounts are numeric).

Suggestions are never applied directly: the user previews them on 20 rows and approves (A2, brief).
"""

import json
import logging
from typing import Literal, Protocol

import httpx
import polars as pl
from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from app.services.canonical import CANONICAL_FIELDS, FieldSpec
from app.services.fingerprint import normalise_header
from app.services.parsing import (
    date_series,
    datetime_series,
    delivery_status_expr,
    leg_expr,
    money_expr,
    order_id_expr,
    payment_mode_expr,
)
from app.services.pii import mask_sample_rows

logger = logging.getLogger(__name__)

SAMPLE_ROWS_FOR_AI = 5
LOW_CONFIDENCE = 0.7
AI_UNAVAILABLE = "AI unavailable, showing best guesses"


class FieldSuggestion(BaseModel):
    source_column: str | None
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(max_length=300)


class MappingSuggestion(BaseModel):
    engine: Literal["llm", "fuzzy", "saved"]
    fields: dict[str, FieldSuggestion]
    notice: str | None = None  # e.g. why the AI was not used

    def columns(self) -> dict[str, str | None]:
        return {name: suggestion.source_column for name, suggestion in self.fields.items()}


class MappingSuggester(Protocol):
    def suggest(self, file_kind: str, headers: list[str], rows: list[dict[str, str | None]]) -> MappingSuggestion: ...


# ---------- fuzzy ----------

SYNONYMS: dict[str, list[str]] = {
    "order_id": ["order id", "order no", "order number", "order ref", "order reference", "merchant order id", "sub order no", "suborder no", "order"],
    "order_date": ["order date", "purchase date", "created at", "order placed", "date"],
    "value": ["order value", "order total", "item price", "selling price", "bill amount", "amount", "total", "price"],
    "payment_mode": ["payment method", "payment mode", "payment type", "payment", "mode"],
    "delivery_status": ["shipment status", "order status", "delivery status", "fulfilment status", "status"],
    "delivered_date": ["delivered on", "delivery date", "delivered at", "delivered date"],
    "returned_date": ["returned on", "return date", "returned at", "rto date"],
    "awb": ["awb", "awb no", "awb number", "tracking number", "tracking id", "waybill", "airway bill"],
    "courier": ["courier", "courier partner", "carrier", "logistics partner", "shipping partner"],
    "dead_weight": ["weight", "dead weight", "actual weight", "weight g"],
    "volumetric_weight": ["volumetric weight", "vol weight", "dimensional weight"],
    "customer_name": ["customer name", "buyer name", "recipient name", "name"],
    "customer_phone": ["customer phone", "phone", "mobile", "contact number"],
    "customer_address": ["shipping address", "delivery address", "address"],
    "pincode": ["pincode", "pin", "pin code", "postal code", "ship postal code", "zip"],
    "settlement_date": ["settlement date", "payment date", "payout date", "remittance date", "txn date", "credited on", "date"],
    "gross": ["gross", "gross amount", "gross sales", "sale amount", "order value", "bill amount", "amount"],
    "commission": ["commission", "commission fee", "marketplace commission", "platform commission", "platform fee"],
    "fees": ["fees", "other fees", "other charges", "charges", "fixed fee", "platform charges", "mdr fee", "fees charges"],
    "tcs": ["tcs", "gst tcs", "tcs withheld", "tcs gst", "tcs u s 52"],
    "tds": ["tds", "income tax tds", "tds withheld", "tds 194 o", "tds u s 194 o"],
    "net": ["net", "net payout", "net amount", "final settlement", "settled amount", "payout amount", "amount credited", "net payable"],
    "reference": ["reference", "reference no", "txn ref", "settlement id", "payment ref", "payout id", "remittance ref", "payout ref"],
    "remittance_date": ["remittance date", "remit date", "credited on", "date"],
    "amount": ["cod amount", "collected amount", "remitted amount", "amount"],
    "utr": ["utr", "utr no", "bank ref", "bank reference"],
    "invoice_no": ["invoice", "invoice no", "invoice number"],
    "charged_weight": ["charged weight", "billed weight", "charged wt", "weight"],
    "leg": ["leg", "direction", "shipment type", "type"],
    "freight": ["freight", "freight charges", "shipping charges"],
    "cod_fee": ["cod fee", "cod charges", "cod charge"],
    "received_at": ["scan time", "received at", "received on", "scanned at", "date"],
}


def _simplify(text: str) -> str:
    return " ".join("".join(char if char.isalnum() else " " for char in normalise_header(text)).split())


def _values_fit(spec: FieldSpec, values: list[str | None]) -> float | None:
    """Share of non-empty sample values that parse as the field's type (None if there is nothing to check)."""
    present = [value for value in values if value not in (None, "")]
    if not present or spec.type == "text":
        return None
    series = pl.Series(present, dtype=pl.String)
    if spec.type == "date":
        parsed = date_series(series)
    elif spec.type == "datetime":
        parsed = datetime_series(series)
    else:
        expression = {
            "money": money_expr,
            "weight": money_expr,
            "order_id": order_id_expr,
            "payment_mode": payment_mode_expr,
            "delivery_status": delivery_status_expr,
            "leg": leg_expr,
        }[spec.type]
        parsed = pl.select(expression(pl.lit(series))).to_series()
    return parsed.drop_nulls().len() / len(present)


class FuzzySuggester:
    """Header-name similarity plus a check that the values look right. No network, always available."""

    def suggest(self, file_kind: str, headers: list[str], rows: list[dict[str, str | None]]) -> MappingSuggestion:
        specs = CANONICAL_FIELDS[file_kind]
        candidates: list[tuple[float, str, str, str]] = []  # score, field, header, reason
        for spec in specs:
            synonyms = SYNONYMS.get(spec.name, [spec.label.lower()])
            for header in headers:
                simple = _simplify(header)
                name_score = max(
                    max(fuzz.ratio(simple, synonym), fuzz.token_set_ratio(simple, synonym) * 0.9) for synonym in synonyms
                ) / 100
                fit = _values_fit(spec, [row.get(header) for row in rows])
                score = name_score
                if fit is not None:
                    score = name_score * (0.6 + 0.4 * fit)
                reason = f"Header '{header}' resembles '{spec.label.lower()}'"
                if fit is not None:
                    reason += "; sample values fit" if fit >= 0.8 else "; some sample values do not fit"
                candidates.append((score, spec.name, header, reason))

        chosen: dict[str, FieldSuggestion] = {}
        used_headers: set[str] = set()
        for score, field, header, reason in sorted(candidates, key=lambda item: item[0], reverse=True):
            if field in chosen or header in used_headers or score < 0.55:
                continue
            chosen[field] = FieldSuggestion(source_column=header, confidence=round(min(score, 0.95), 2), reason=reason)
            used_headers.add(header)

        fields = {
            spec.name: chosen.get(spec.name)
            or FieldSuggestion(source_column=None, confidence=0.0, reason="No column looks like this field")
            for spec in specs
        }
        return MappingSuggestion(engine="fuzzy", fields=fields)


# ---------- LLM (Gemini) ----------

class _LLMField(BaseModel):
    source_column: str | None
    confidence: float = Field(ge=0, le=1)
    reason: str


def _response_schema(specs: list[FieldSpec]) -> dict:
    field_schema = {
        "type": "OBJECT",
        "properties": {
            "source_column": {"type": "STRING", "nullable": True},
            "confidence": {"type": "NUMBER"},
            "reason": {"type": "STRING"},
        },
        "required": ["source_column", "confidence", "reason"],
    }
    return {"type": "OBJECT", "properties": {spec.name: field_schema for spec in specs}, "required": [spec.name for spec in specs]}


def build_prompt(file_kind: str, headers: list[str], masked_rows: list[dict[str, str | None]]) -> str:
    specs = CANONICAL_FIELDS[file_kind]
    field_lines = "\n".join(
        f"- {spec.name} ({spec.type}{', required' if spec.required else ''}): {spec.label}. {spec.description}".rstrip(". ") + "."
        for spec in specs
    )
    return (
        "You map columns of an Indian e-commerce partner report onto a fixed set of fields.\n"
        f"Report kind: {file_kind.replace('_', ' ')}.\n\n"
        f"Fields:\n{field_lines}\n\n"
        f"Columns in the file (use these names exactly): {json.dumps(headers, ensure_ascii=False)}\n\n"
        f"First rows (personal data masked): {json.dumps(masked_rows, ensure_ascii=False, default=str)}\n\n"
        "For every field give the single best source column, or null if the file has none. "
        "Confidence is 0 to 1: use below 0.7 when unsure. Reason: at most 20 words, based on the header and the values."
    )


class LLMSuggester:
    """Gemini with structured JSON output. Any failure -> fuzzy suggestions with a notice."""

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: float = 15.0,
        fallback: MappingSuggester | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.fallback = fallback or FuzzySuggester()
        self.client = client or httpx.Client(timeout=timeout_seconds)

    def suggest(self, file_kind: str, headers: list[str], rows: list[dict[str, str | None]]) -> MappingSuggestion:
        try:
            return self._ask_model(file_kind, headers, rows)
        except Exception as error:  # noqa: BLE001 - every failure has the same safe answer
            # Log the kind of failure only: never the payload (it could echo file contents) or the key.
            logger.warning("AI column mapping failed (%s); using fuzzy suggestions", type(error).__name__)
            fallback = self.fallback.suggest(file_kind, headers, rows)
            fallback.notice = AI_UNAVAILABLE
            return fallback

    def _ask_model(self, file_kind: str, headers: list[str], rows: list[dict[str, str | None]]) -> MappingSuggestion:
        specs = CANONICAL_FIELDS[file_kind]
        masked = mask_sample_rows(headers, rows[:SAMPLE_ROWS_FOR_AI])
        body = {
            "contents": [{"role": "user", "parts": [{"text": build_prompt(file_kind, headers, masked)}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": _response_schema(specs),
            },
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        response = self.client.post(url, json=body, headers={"x-goog-api-key": self.api_key})
        response.raise_for_status()
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        raw = json.loads(text)

        header_lookup = {header.strip().lower(): header for header in headers}
        fields: dict[str, FieldSuggestion] = {}
        for spec in specs:
            item = _LLMField.model_validate(raw[spec.name])
            column = item.source_column
            if column is not None and column.strip() != "":
                if column.strip().lower() not in header_lookup:
                    raise ValueError("model named a column that is not in the file")
                column = header_lookup[column.strip().lower()]
            else:
                column = None
            fields[spec.name] = FieldSuggestion(source_column=column, confidence=round(item.confidence, 2), reason=item.reason[:300])
        return MappingSuggestion(engine="llm", fields=fields)


def get_suggester(api_key: str | None, model: str) -> MappingSuggester:
    """Gemini when a key is configured, otherwise fuzzy matching (with a notice so the UI can say so)."""
    if api_key:
        return LLMSuggester(api_key=api_key, model=model)
    return _NoKeySuggester()


class _NoKeySuggester(FuzzySuggester):
    def suggest(self, file_kind: str, headers: list[str], rows: list[dict[str, str | None]]) -> MappingSuggestion:
        suggestion = super().suggest(file_kind, headers, rows)
        suggestion.notice = AI_UNAVAILABLE
        return suggestion

