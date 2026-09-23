"""AI task analysis with strict structured output and a no-key local fallback.

Public contracts:
    analyze_task(raw_text, card=None) -> {missing, questions, provider}
    build_card(raw_text, answers=None) -> normalized editable card

The OpenAI Responses API is optional and accessed with the standard library so
the project can still be installed/run without an API dependency or API key.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from core.models import CARD_FIELDS, Card, RATING_FIELD_MAP, RATING_WEIGHTS, normalize_card


FIELD_LABELS = {
    "context_need": "Контекст и потребность",
    "data": "Данные и материалы",
    "expected_result": "Ожидаемый результат",
    "success_criteria": "Критерии успеха",
    "constraints": "Ограничения",
    "users": "Пользователи",
    "business_contact": "Связь с бизнесом",
}
FIELD_QUESTIONS = {
    "context_need": "Как сейчас решается эта задача и что именно нужно изменить?",
    "data": "Какие данные или материалы доступны команде и в каком виде их можно получить?",
    "expected_result": "Какой конкретный результат вы хотите получить от студенческой команды?",
    "success_criteria": "По каким измеримым признакам вы поймёте, что результат вас устраивает?",
    "constraints": "Какие есть сроки, технологические ограничения или ограничения доступа?",
    "users": "Кто будет пользоваться решением или получит от него пользу?",
    "business_contact": "Кто будет контактным лицом и как часто команда сможет получать обратную связь?",
}
WEIGHTS = RATING_WEIGHTS

_PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
_API_URL = "https://api.openai.com/v1/responses"
_ANALYZE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "missing": {"type": "array", "items": {"type": "string", "enum": list(FIELD_LABELS)}},
        "questions": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"field": {"type": "string", "enum": list(FIELD_LABELS)},
                           "question": {"type": "string"}},
            "required": ["field", "question"],
        }},
    },
    "required": ["missing", "questions"],
}
_CARD_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        **{field: {"type": "string"} for field in CARD_FIELDS},
        "sources": {"type": "object", "additionalProperties": False,
                    "properties": {field: {"type": "string"} for field in CARD_FIELDS},
                    "required": list(CARD_FIELDS)},
    },
    "required": [*CARD_FIELDS, "sources"],
}


def _has_key() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def _prompt(name: str) -> str:
    try:
        return (_PROMPT_DIR / name).read_text(encoding="utf-8")
    except OSError:
        return ""


def _extract_output_text(response: dict[str, Any]) -> str:
    # The REST response has output items; collect only message output_text parts.
    chunks: list[str] = []
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                chunks.append(str(content.get("text", "")))
    if not chunks:
        raise ValueError("Responses API returned no output_text")
    return "".join(chunks)


def _responses_json(instructions: str, payload: dict[str, Any], schema_name: str,
                    schema: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    body = {
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "instructions": instructions,
        "input": json.dumps(payload, ensure_ascii=False),
        "text": {"format": {"type": "json_schema", "name": schema_name,
                             "strict": True, "schema": schema}},
        "store": False,
        "max_output_tokens": 1200,
    }
    request = urllib.request.Request(
        _API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"OpenAI request failed: {exc}") from exc
    if result.get("status") != "completed":
        raise RuntimeError(f"OpenAI response status: {result.get('status', 'unknown')}")
    return json.loads(_extract_output_text(result))


def _meaningful(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if len(text) < 4 or text in {"нет", "не знаю", "-", "n/a", "asdf"}:
        return False
    words = re.findall(r"[\w-]+", text, flags=re.UNICODE)
    return bool(words) and not (len(words) >= 2 and len(set(words)) == 1)


def _rating_field_value(card: dict[str, Any], rating_field: str) -> str:
    return " ".join(str(card.get(field, "") or "").strip()
                    for field in RATING_FIELD_MAP[rating_field]).strip()


def _local_analyze(raw_text: str, card: dict[str, Any] | None) -> dict[str, Any]:
    current = normalize_card(card)
    # For an untouched draft, use light keyword detection to avoid treating the
    # whole free-text paragraph as evidence for every card section.
    text = raw_text.casefold()
    indicators = {
        "context_need": r"\b(сейчас|сегодня|проблем|нужно|необходимо|улучш|автоматиз|уменьш|увелич|сниз|повыс)\b",
        "data": r"\b(данн|таблиц|файл|выгруз|api|баз[аы]|отч[её]т|crm|excel)\w*",
        "expected_result": r"\b(прототип|дашборд|бот|отч[её]т|модель|приложен|сервис|систем)\w*",
        "success_criteria": r"\b(\d+\s*%|\d+\s*(раз|дн|недел|месяц|час|минут)|критери|метрик|показател)\w*",
        "constraints": r"\b(срок|до \d|технолог|огранич|доступ|бюджет|обязательно)\w*",
        "users": r"\b(клиент|сотрудник|менеджер|оператор|студент|пользовател|покупател|водител|фермер)\w*",
        "business_contact": r"\b(контакт|связ|встреч|консультац|обратн\w* связ|представител)\w*",
    }
    missing = []
    for field in FIELD_LABELS:
        supplied = _rating_field_value(current, field)
        present = _meaningful(supplied) if supplied else bool(re.search(indicators[field], text))
        if not present:
            missing.append(field)
    missing.sort(key=lambda field: (-WEIGHTS[field], list(FIELD_LABELS).index(field)))
    questions = [{"field": field, "question": FIELD_QUESTIONS[field]} for field in missing[:6]]
    while len(questions) < min(3, len(FIELD_LABELS)):
        field = list(FIELD_LABELS)[len(questions)]
        if field not in {item["field"] for item in questions}:
            questions.append({"field": field, "question": FIELD_QUESTIONS[field]})
    return {"missing": missing, "questions": questions[:6], "provider": "local"}


def analyze_task(raw_text: str, card: dict[str, Any] | None = None) -> dict[str, Any]:
    """Find missing task details and produce 3–6 prioritized questions.

    Returns `missing` rating-field keys and question objects with `field` and
    `question`. If the API is unset or fails, returns deterministic local output.
    """
    raw_text = str(raw_text or "").strip()
    if _has_key():
        try:
            result = _responses_json(
                _prompt("analyze_task.md"),
                {"raw_text": raw_text, "card": normalize_card(card)},
                "task_analysis", _ANALYZE_SCHEMA,
            )
            result["missing"] = [key for key in result["missing"] if key in FIELD_LABELS]
            result["questions"] = [
                {"field": item["field"], "question": item["question"]}
                for item in result["questions"]
                if item.get("field") in FIELD_LABELS and str(item.get("question", "")).strip()
            ][:6]
            for field in result["missing"]:
                if not any(q["field"] == field for q in result["questions"]):
                    result["questions"].append({"field": field, "question": FIELD_QUESTIONS[field]})
            while len(result["questions"]) < 3:
                field = next((f for f in FIELD_LABELS if f not in {q["field"] for q in result["questions"]}), None)
                if field is None:
                    break
                result["questions"].append({"field": field, "question": FIELD_QUESTIONS[field]})
            result["provider"] = "openai"
            return result
        except Exception:
            # API/JSON/schema failures degrade to a usable local result.
            pass
    return _local_analyze(raw_text, card)


def _evidence(raw_text: str, answers: dict[str, Any] | None) -> list[str]:
    evidence = [raw_text.strip()] if raw_text.strip() else []
    for value in (answers or {}).values():
        if isinstance(value, str) and value.strip():
            evidence.append(value.strip())
    return evidence


def _source_is_verbatim(source: str, evidence: list[str]) -> bool:
    if not source.strip():
        return False
    normalized = source.casefold().strip()
    return any(normalized in item.casefold() for item in evidence)


def _local_build_card(raw_text: str, answers: dict[str, Any] | None) -> Card:
    card = normalize_card(None)
    sources: dict[str, str] = {}
    if _meaningful(raw_text):
        card["need"] = raw_text.strip()
        sources["need"] = raw_text.strip()
        # A title may be proposed from the user text, but remains editable.
        words = raw_text.strip().split()
        card["title"] = " ".join(words[:8]).rstrip(".,!?;:")
        sources["title"] = raw_text.strip()
    aliases = {
        "context_need": ("context", "need"),
        "business_contact": ("contact", "interaction_format"),
    }
    for key, value in (answers or {}).items():
        if not isinstance(value, str) or not _meaningful(value):
            continue
        targets = aliases.get(key, (key,))
        for target in targets:
            if target in CARD_FIELDS:
                card[target] = value.strip()
                sources[target] = value.strip()
    card["sources"] = sources
    return card


def build_card(raw_text: str, answers: dict[str, Any] | None = None) -> Card:
    """Draft the editable card only from user-provided text/answers.

    Every proposed field must cite a verbatim source substring. Unverified AI
    fields are blanked, so generated details cannot be published accidentally.
    """
    raw_text = str(raw_text or "").strip()
    answers = answers or {}
    evidence = _evidence(raw_text, answers)
    candidate: dict[str, Any] | None = None
    if _has_key():
        try:
            candidate = _responses_json(
                _prompt("build_card.md"),
                {"raw_text": raw_text, "answers": answers},
                "task_card", _CARD_SCHEMA,
            )
        except Exception:
            candidate = None
    if candidate is None:
        return _local_build_card(raw_text, answers)

    card = normalize_card(candidate)
    candidate_sources = candidate.get("sources", {}) if isinstance(candidate.get("sources"), dict) else {}
    valid_sources: dict[str, str] = {}
    for field in CARD_FIELDS:
        value = card.get(field, "")
        source = str(candidate_sources.get(field, "")).strip()
        if value and _source_is_verbatim(source, evidence):
            valid_sources[field] = source
        else:
            card[field] = ""
    card["sources"] = valid_sources
    return card


__all__ = ["analyze_task", "build_card"]
