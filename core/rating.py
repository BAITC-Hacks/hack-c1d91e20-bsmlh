"""Transparent, deterministic readiness score for business task cards."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from core.models import RATING_FIELD_MAP, RATING_WEIGHTS


FIELD_LABELS = {
    "context_need": "Контекст и потребность",
    "data": "Данные и материалы",
    "expected_result": "Ожидаемый результат",
    "success_criteria": "Критерии успеха",
    "constraints": "Ограничения",
    "users": "Пользователи",
    "business_contact": "Связь с бизнесом",
}

FIELD_SUGGESTIONS = {
    "context_need": "Опишите отдельно, как задачу решают сейчас и что должно измениться.",
    "data": "Укажите вид данных или пример, а также источник и способ доступа (например, CSV или API).",
    "expected_result": "Назовите конкретный результат: прототип, отчёт, дашборд, бот или другой артефакт.",
    "success_criteria": "Добавьте измеримый показатель, число, процент или срок, по которому примете результат.",
    "constraints": "Укажите срок, обязательную технологию, доступы или другое ограничение.",
    "users": "Уточните конкретную группу или роль пользователей.",
    "business_contact": "Укажите контактную роль и формат взаимодействия или консультаций.",
}

_JUNK = {
    "", "-", "--", "—", "нет", "не знаю", "н/д", "н.д.", "na", "n/a", "none",
    "asdf", "qwerty", "тест", "test", "xxx", "...", "?",
}
_ARTIFACT_RE = re.compile(
    r"\b(прототип\w*|дашборд\w*|отч[её]т\w*|бот\w*|модел\w*|приложен\w*|"
    r"сервис\w*|систем\w*|алгоритм\w*|панел\w*|инструмент\w*)\b|"
    r"\b(api|dashboard|prototype|report|bot|model|application|service)\b",
    re.IGNORECASE,
)
_MEASUREMENT_RE = re.compile(
    r"\d|%|процент\w*|не более|не менее|снизить|увеличить|рост\w*|сократить|"
    r"точност\w*|врем\w*|доля\w*|уров\w*",
    re.IGNORECASE,
)
_ACCESS_RE = re.compile(
    r"\b(csv|xlsx?|excel|json|api|sql|crm|выгруз\w*|файл\w*|таблиц\w*|"
    r"доступ\w*|ссылка|баз\w* данных|формат\w*)\b",
    re.IGNORECASE,
)
_CONSTRAINT_RE = re.compile(
    r"\b(до \d|к \d|срок\w*|дедлайн\w*|недел\w*|месяц\w*|дн\w*|час\w*|"
    r"технолог\w*|python|streamlit|react|огранич\w*|доступ\w*|бюджет\w*)\b",
    re.IGNORECASE,
)
_USER_ROLE_RE = re.compile(
    r"\b(клиент\w*|покупател\w*|сотрудник\w*|менеджер\w*|оператор\w*|"
    r"студент\w*|водител\w*|фермер\w*|кассир\w*|поставщик\w*|учител\w*|"
    r"преподавател\w*|врач\w*|пациент\w*|бухгалтер\w*|аналитик\w*|"
    r"пользовател\w* [а-яё-]+)\b",
    re.IGNORECASE,
)
_CONTACT_RE = re.compile(
    r"@|\b(контакт\w*|представител\w*|менеджер\w*|координатор\w*|"
    r"руководител\w*|тел\.?|email|почт\w*|имя|ответственн\w*)\b",
    re.IGNORECASE,
)
_INTERACTION_RE = re.compile(
    r"\b(ежеднев\w*|еженедел\w*|раз в неделю|встреч\w*|консультац\w*|"
    r"созвон\w*|почт\w*|чат\w*|обратн\w* связ\w*|по запросу|демо)\b",
    re.IGNORECASE,
)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def is_meaningful(value: Any, *, min_chars: int = 4) -> bool:
    """Reject blank, placeholder, punctuation-only, and repeated-word answers."""
    text = _clean_text(value)
    folded = text.casefold().strip(" .,!?:;\t\n\r")
    if folded in _JUNK or len(folded) < min_chars:
        return False
    words = re.findall(r"[\w@.+-]+", folded, flags=re.UNICODE)
    if not words:
        return False
    if len(words) >= 2 and len(set(words)) == 1:
        return False
    if len(words) == 1 and len(words[0]) < min_chars:
        return False
    return True


def _status_is_confirmed(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"confirmed", "approved", "подтверждено", "да"}


def _confirmation_map(
    card: Mapping[str, Any], field_status: Mapping[str, Any] | None
) -> tuple[dict[str, bool], bool]:
    """Return field flags and whether explicit statuses were supplied.

    For backwards compatibility with `calculate_rating(card)`, omitted statuses
    mean the caller is passing a card already confirmed by a human. UI code
    should pass `field_status` to ensure AI drafts earn zero points.
    """
    if field_status is None and isinstance(card.get("field_status"), Mapping):
        field_status = card["field_status"]
    explicit = field_status is not None
    if not explicit:
        return {key: True for parts in RATING_FIELD_MAP.values() for key in parts}, False
    statuses = field_status or {}
    return {key: _status_is_confirmed(statuses.get(key)) for parts in RATING_FIELD_MAP.values() for key in parts}, True


def _dimension_text(card: Mapping[str, Any], field: str) -> dict[str, str]:
    # Also accept the aggregate names for callers holding a compact score card.
    result: dict[str, str] = {}
    for key in RATING_FIELD_MAP[field]:
        value = card.get(key)
        if not value and key == "context":
            value = card.get("context_need")
        elif not value and key == "contact":
            value = card.get("business_contact")
        elif not value and key == "interaction_format":
            value = card.get("business_contact") if card.get("contact") else None
        result[key] = _clean_text(value)
    if field == "context_need" and not any(result.values()) and card.get("context_need"):
        result["context_need"] = _clean_text(card.get("context_need"))
    if field == "business_contact" and not any(result.values()) and card.get("business_contact"):
        result["business_contact"] = _clean_text(card.get("business_contact"))
    return result


def _assess(field: str, card: Mapping[str, Any]) -> tuple[int, str]:
    parts = _dimension_text(card, field)
    values = [value for value in parts.values() if is_meaningful(value)]
    if not values:
        return 0, "Поле пустое или содержит заглушку; такие ответы баллов не дают."

    joined = " ".join(values)
    if field == "context_need":
        has_context = is_meaningful(parts.get("context"))
        has_need = is_meaningful(parts.get("need"))
        if has_context and has_need:
            return RATING_WEIGHTS[field], "Заполнены и текущая ситуация, и требуемое изменение."
        if has_context or has_need:
            return RATING_WEIGHTS[field] // 2, "Есть часть описания, но не разделены текущая ситуация и нужное изменение."
        return 0, "Для контекста и потребности недостаточно содержательных сведений."

    if field == "data":
        if _ACCESS_RE.search(joined):
            return RATING_WEIGHTS[field], "Указаны данные или источник и понятный формат/способ доступа."
        return RATING_WEIGHTS[field] // 2, "Данные упомянуты, но источник или способ доступа неясен."

    if field == "expected_result":
        if _ARTIFACT_RE.search(joined):
            return RATING_WEIGHTS[field], "Назван конкретный артефакт или результат работы."
        return RATING_WEIGHTS[field] // 2, "Результат описан общо; назовите конкретный артефакт."

    if field == "success_criteria":
        if _MEASUREMENT_RE.search(joined):
            return RATING_WEIGHTS[field], "Есть измеримый показатель, число, порог или срок."
        return RATING_WEIGHTS[field] // 2, "Критерий есть, но его пока нельзя измерить."

    if field == "constraints":
        if _CONSTRAINT_RE.search(joined):
            return RATING_WEIGHTS[field], "Указано конкретное ограничение, срок, технология или доступ."
        return RATING_WEIGHTS[field] // 2, "Ограничения описаны расплывчато; добавьте срок, технологию или доступ."

    if field == "users":
        if _USER_ROLE_RE.search(joined):
            return RATING_WEIGHTS[field], "Названа конкретная группа или роль пользователей."
        return RATING_WEIGHTS[field] // 2, "Пользователи упомянуты слишком общо; уточните их роль или группу."

    if field == "business_contact":
        contact = parts.get("contact", "") or parts.get("business_contact", "")
        interaction = parts.get("interaction_format", "")
        has_contact = is_meaningful(contact) and bool(_CONTACT_RE.search(contact))
        has_interaction = is_meaningful(interaction) and bool(_INTERACTION_RE.search(interaction))
        if has_contact and has_interaction:
            return RATING_WEIGHTS[field], "Есть контактная роль и описан формат обратной связи."
        return RATING_WEIGHTS[field] // 2, "Связь с бизнесом указана частично; нужны контактная роль и формат консультаций."

    return 0, "Неизвестное направление рейтинга."


def get_level(score: int) -> str:
    """Map the 0–100 score to the case's four readiness levels."""
    value = max(0, min(100, int(score)))
    if value < 40:
        return "черновик"
    if value < 70:
        return "рабочая"
    if value < 90:
        return "готовая"
    return "приоритетная"


def calculate_rating(
    card: Mapping[str, Any] | None,
    field_status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Score a task card and explain every earned or pending point.

    A confirmed, meaningful field earns half credit when its content is vague,
    and full credit when it passes the field-specific quality rule. A non-empty
    but unconfirmed field earns 0 and shows its possible gain. With no explicit
    `field_status`, values are treated as confirmed for simple integration.
    """
    if not isinstance(card, Mapping):
        card = {}
    # Accept a Task dictionary as a convenience, while preserving the promised
    # calculate_rating(card) call used by the Streamlit layer.
    if isinstance(card.get("card"), Mapping):
        if field_status is None and isinstance(card.get("field_status"), Mapping):
            field_status = card["field_status"]
        card = card["card"]

    confirmed, explicit_status = _confirmation_map(card, field_status)
    breakdown: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    score = 0

    for field, weight in RATING_WEIGHTS.items():
        parts = _dimension_text(card, field)
        present_parts = {key: value for key, value in parts.items() if is_meaningful(value)}
        credited_parts = {
            key: value for key, value in present_parts.items()
            if confirmed.get(key, False)
        }
        full_points, quality_reason = _assess(field, card)

        if not present_parts:
            points = 0
            status = "empty"
            reason = "Не заполнено; пока баллов нет."
        elif explicit_status and not credited_parts:
            points = 0
            status = "unconfirmed"
            reason = "Заполнено, но ещё не подтверждено бизнесом; баллы начислятся после подтверждения."
        elif full_points == 0:
            points = 0
            status = "invalid"
            reason = quality_reason
        elif field in {"context_need", "business_contact"} and len(credited_parts) < len(parts):
            points = weight // 2
            status = "partial"
            reason = "Часть карточки заполнена, но не все составляющие поля подтверждены. " + quality_reason
        elif field in {"context_need", "business_contact"} and len(present_parts) < len(parts):
            points = weight // 2
            status = "partial"
            reason = quality_reason
        else:
            # A quality rule may award half weight for a meaningful but vague
            # confirmed value, otherwise it awards the full weight.
            points = full_points if all(confirmed.get(key, False) for key in present_parts) else 0
            if points == 0:
                status = "unconfirmed"
                reason = "Поле ожидает подтверждения бизнеса."
            elif points == weight:
                status = "complete"
                reason = quality_reason
            else:
                status = "partial"
                reason = quality_reason

        score += points
        gain = weight - points
        item = {
            "field": field,
            "label": FIELD_LABELS[field],
            "score": points,
            "max_score": weight,
            "status": status,
            "reason": reason,
            "suggestion": FIELD_SUGGESTIONS[field] if gain else "",
            "potential_gain": gain,
        }
        breakdown.append(item)
        if gain:
            missing.append({
                "field": field,
                "label": FIELD_LABELS[field],
                "points": gain,
                "reason": reason,
                "suggestion": FIELD_SUGGESTIONS[field],
            })

    score = min(100, score)
    return {
        "score": score,
        "level": get_level(score),
        "breakdown": breakdown,
        "missing": missing,
        "potential_gain": 100 - score,
    }


__all__ = ["calculate_rating", "get_level", "is_meaningful"]
