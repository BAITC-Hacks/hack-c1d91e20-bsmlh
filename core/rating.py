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
    "users": "Напишите, кто именно будет пользоваться решением и в какой работе: например, менеджеры, обрабатывающие заявки.",
    "business_contact": "Укажите контактную роль и формат взаимодействия или консультаций.",
}

LEVEL_LABELS = {
    "draft": "требует уточнения",
    "working": "описана достаточно для обсуждения с командами",
    "ready": "описана достаточно подробно для старта",
    "priority": "описана очень подробно",
}
SCORE_MEANING = (
    "Оценка готовности задачи: баллы показывают полноту и конкретность "
    "подтверждённого бизнесом описания. Это не оценка ценности идеи или команды."
)

_JUNK = {
    "", "-", "--", "—", "нет", "не знаю", "н/д", "н.д.", "na", "n/a", "none",
    "asdf", "qwerty", "тест", "test", "xxx", "...", "?", "неизвестно",
    "все", "всё", "все подряд", "кто угодно", "tbd", "todo",
}
_NO_INFORMATION_RE = re.compile(
    r"^(?:нет\s+(?:данных|материалов|информации|ограничений)\b|пока\s+нет\b|"
    r"не\s+(?:знаем|знаю|известно|определено|указано)\b|"
    r"отсутству\w*\b|не\s+предостав\w*\b|уточним\s+позже\b)|"
    r"\b(?:пока\s+нет|(?:данных|материалов)\s+нет|отсутству\w*|неизвест\w*|не\s+определ\w*)\s*$",
    re.IGNORECASE,
)
_ARTIFACT_RE = re.compile(
    r"\b(прототип\w*|дашборд\w*|отч[её]т\w*|бот(?:а|у|ом|е|ы|ов)?|"
    r"модел(?:ь|и|ей|ью|ям|ями|ях)|приложени\w*)\b|"
    r"\b(api|dashboard|prototype|report|bot|model|application|service)\b",
    re.IGNORECASE,
)
_DEADLINE_RE = re.compile(
    r"\b(?:до|к|срок|дедлайн|by|deadline)\s*[:—-]?\s*(?:"
    r"\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?|"
    r"\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|"
    r"сентября|октября|ноября|декабря)|\d{1,2}:\d{2})\b",
    re.IGNORECASE,
)
_MEASUREMENT_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:%|процент\w*|день|дня|дней|сут\w*|недел\w*|месяц\w*|"
    r"час\w*|минут\w*|секунд\w*|мс|ms|seconds?|minutes?|hours?|days?|"
    r"балл\w*|случа\w*|заяв\w*|вопрос\w*|ошиб\w*|раз\w*)(?=\W|$)|"
    r"\b(?:sla|f1|auc|точность|полнота|accuracy|precision|recall)\s*"
    r"(?:не\s+(?:менее|ниже|более)|[=:<>≥≤]+)?\s*\d+(?:[.,]\d+)?\b",
    re.IGNORECASE,
)
_DATA_CONTENT_RE = re.compile(
    r"\b(заказ\w*|продаж\w*|остатк\w*|заявк\w*|обращени\w*|клиент\w*|"
    r"товар\w*|faq|каталог\w*|наблюдени\w*|показател\w*|маршрут\w*|"
    r"посещени\w*|платеж\w*|датчик\w*|транзакц\w*|фотограф\w*|изображени\w*|"
    r"документ\w*|договор\w*|инструкци\w*|аудио\w*|видеозапис\w*|лог(?:и|ов)?|"
    r"crm|erp|1с|sales|orders?|images?|documents?|logs?)\b|"
    r"\b(?:столбцы|колонки|поля)\s*:",
    re.IGNORECASE,
)
_DATA_ACCESS_RE = re.compile(
    r"\b(csv|xlsx?|excel|json|api|sql|pdf|выгруз\w*|экспорт\w*|export|"
    r"скачивани\w*)\b|https?://\S+",
    re.IGNORECASE,
)
_NO_DATA_ACCESS_RE = re.compile(
    r"\b(?:нет\s+доступ\w*|без\s+доступ\w*|доступ\w*\s+(?:пока\s+)?(?:нет|не\s+"
    r"(?:предостав\w*|согласован\w*))|недоступ\w*|не\s+можем\s+передать)\b",
    re.IGNORECASE,
)
_CONSTRAINT_SPECIFIC_RE = re.compile(
    r"\b\d+\s*(?:день|дня|дней|сут\w*|недел\w*|месяц\w*|час\w*|минут\w*|"
    r"тенге|руб\w*|тг|доллар\w*|gb|гб)\b|"
    r"\b(?:python|streamlit|react|api|sql)\b|"
    r"\b(?:только\s+(?:обезличенн\w*|синтетическ\w*|тестов\w*|публичн\w*)|"
    r"без\s+персональн\w*|обезличенн\w*|синтетическ\w*|"
    r"(?:без|нет\s+доступа\s+к)\s+интернет\w*)\b",
    re.IGNORECASE,
)
_USER_ROLE_RE = re.compile(
    r"\b(клиент\w*|покупател\w*|сотрудник\w*|менеджер\w*|оператор\w*|"
    r"студент\w*|водител\w*|фермер\w*|кассир\w*|поставщик\w*|учител\w*|"
    r"преподавател\w*|врач\w*|пациент\w*|бухгалтер\w*|аналитик\w*|"
    r"диспетчер\w*|инженер\w*|администратор\w*|customers?|managers?|operators?)\b",
    re.IGNORECASE,
)
_CONTACT_RE = re.compile(
    r"[\w.+-]+@[\w.-]+\.[a-z]{2,}|(?<!\w)@[\w]{3,}|"
    r"(?<!\w)\+?\d[\d ()-]{5,}\d(?!\w)|"
    r"\b(представител\w*|менеджер\w*|координатор\w*|руководител\w*|"
    r"директор\w*|куратор\w*|manager|coordinator)\b",
    re.IGNORECASE,
)
_INTERACTION_RE = re.compile(
    r"\b(встреч\w*|консультац\w*|"
    r"созвон\w*|почт\w*|чат\w*|обратн\w* связ\w*|по запросу|демо)\b",
    re.IGNORECASE,
)
_CONTACT_NAME_RE = re.compile(r"\b[А-ЯЁA-Z][а-яёa-z]{2,}\s+[А-ЯЁA-Z][а-яёa-z]{2,}\b")
_CURRENT_STATE_RE = re.compile(
    r"\b(сейчас|сегодня|вручную|обрабатыва\w*|использу\w*|храня\w*|"
    r"занима\w*|теря\w*|трат\w*|жд\w*|ожида\w*|ежеднев\w*|currently|manual\w*)\b",
    re.IGNORECASE,
)
_DESIRED_CHANGE_RE = re.compile(
    r"\b(сократ\w*|сниз\w*|автоматиз\w*|увелич\w*|ускор\w*|уменьш\w*|"
    r"замен\w*|созда\w*|разработ\w*|внедр\w*|улучш\w*|нужно|нужен|нужна|"
    r"хотим|требуется|reduce|automate|increase)\b",
    re.IGNORECASE,
)
_GENERIC_WORDS = {
    "все", "всё", "это", "мы", "у", "нас", "и", "а", "для", "с", "на", "в", "по",
    "нужно", "нужен", "нужна", "надо", "хотим", "чтобы", "будет", "было", "есть",
    "сделать", "делать", "работает", "работало", "хорошо", "плохо", "лучше", "быстро",
    "качественно", "что", "то", "как", "нибудь", "просто", "очень",
    "работу", "процессы", "ситуацию", "бизнес",
}


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE)


def _has_detail(text: str, marker: re.Pattern[str]) -> bool:
    words = _words(text)
    return bool(marker.search(text)) and len(words) >= 3 and any(
        word not in _GENERIC_WORDS and not marker.fullmatch(word) for word in words
    )


def _clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def is_meaningful(value: Any, *, min_chars: int = 3) -> bool:
    """Reject placeholders and repeated words/phrases regardless of punctuation."""
    text = _clean_text(value)
    folded = text.casefold().strip(" .,!?:;\t\n\r")
    if folded in _JUNK or len(folded) < min_chars or _NO_INFORMATION_RE.search(folded):
        return False
    words = _words(folded)
    if not words or all(word in _JUNK for word in words):
        return False
    if not re.search(r"[a-zа-яё]", folded) and not re.fullmatch(r"\+?\d[\d\s()-]{6,}", folded):
        return False
    for width in range(1, len(words) // 2 + 1):
        if len(words) % width == 0 and words == words[:width] * (len(words) // width):
            return False
    if len(words) == 1 and len(words[0]) < min_chars:
        return False
    if len(words) == 1 and len(set(words[0])) <= 2:
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
    explicit = field_status is not None or "field_status" in card
    if field_status is None and "field_status" in card:
        field_status = card["field_status"]
    if not explicit:
        return {key: True for parts in RATING_FIELD_MAP.values() for key in parts}, False
    statuses = field_status if isinstance(field_status, Mapping) else {}
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
            if _words(parts["context"]) == _words(parts["need"]):
                return RATING_WEIGHTS[field] // 2, "Один ответ повторён в двух полях; отдельно опишите текущую ситуацию и изменение."
            if _has_detail(parts["context"], _CURRENT_STATE_RE) and _has_detail(parts["need"], _DESIRED_CHANGE_RE):
                return RATING_WEIGHTS[field], "Описаны текущая ситуация и конкретное требуемое изменение."
            return RATING_WEIGHTS[field] // 2, "Описание слишком общее: нужны текущий процесс или проблема и конкретное изменение."
        if has_context or has_need:
            return RATING_WEIGHTS[field] // 2, "Есть часть описания, но не разделены текущая ситуация и нужное изменение."
        return 0, "Для контекста и потребности недостаточно содержательных сведений."

    if field == "data":
        if _NO_DATA_ACCESS_RE.search(joined):
            return RATING_WEIGHTS[field] // 2, "Доступ к данным не подтверждён; уточните, как команда сможет их получить."
        if _DATA_CONTENT_RE.search(joined) and _DATA_ACCESS_RE.search(joined):
            return RATING_WEIGHTS[field], "Названы конкретные данные и способ их получения."
        return RATING_WEIGHTS[field] // 2, "Нужно уточнить, какие именно данные доступны и как команда их получит."

    if field == "expected_result":
        if _ARTIFACT_RE.search(joined):
            return RATING_WEIGHTS[field], "Назван конкретный артефакт или результат работы."
        return RATING_WEIGHTS[field] // 2, "Результат описан общо; назовите конкретный артефакт."

    if field == "success_criteria":
        if _MEASUREMENT_RE.search(joined) or _DEADLINE_RE.search(joined):
            return RATING_WEIGHTS[field], "Указан измеримый порог, число или срок."
        return RATING_WEIGHTS[field] // 2, "Критерий сформулирован общо; добавьте измеримый порог или срок."

    if field == "constraints":
        if _CONSTRAINT_SPECIFIC_RE.search(joined) or _DEADLINE_RE.search(joined):
            return RATING_WEIGHTS[field], "Указано конкретное ограничение, срок, технология или доступ."
        return RATING_WEIGHTS[field] // 2, "Ограничения описаны общо; добавьте точный срок, технологию или границу доступа."

    if field == "users":
        if _USER_ROLE_RE.search(joined):
            return RATING_WEIGHTS[field], "Названа конкретная группа или роль пользователей."
        return RATING_WEIGHTS[field] // 2, "Пользователи упомянуты слишком общо; уточните их роль или группу."

    if field == "business_contact":
        contact = parts.get("contact", "") or parts.get("business_contact", "")
        interaction = parts.get("interaction_format", "")
        has_contact = is_meaningful(contact) and bool(
            _CONTACT_RE.search(contact) or _CONTACT_NAME_RE.search(contact)
        )
        has_interaction = is_meaningful(interaction) and bool(_INTERACTION_RE.search(interaction))
        if has_contact and has_interaction:
            if _words(contact) == _words(interaction):
                return RATING_WEIGHTS[field] // 2, "Один ответ повторён: укажите контакт и формат обратной связи отдельно."
            return RATING_WEIGHTS[field], "Есть контактная роль и описан формат обратной связи."
        return RATING_WEIGHTS[field] // 2, "Связь с бизнесом указана частично; нужны контактная роль и формат консультаций."

    return 0, "Неизвестное направление рейтинга."


def get_level(score: int) -> str:
    """Return the stable UI/API level code for a 0–100 score."""
    value = max(0, min(100, int(score)))
    if value < 40:
        return "draft"
    if value < 70:
        return "working"
    if value < 90:
        return "ready"
    return "priority"


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
        if field_status is None and "field_status" in card:
            outer_status = card["field_status"]
            field_status = outer_status if isinstance(outer_status, Mapping) else {}
        card = card["card"]

    confirmed, explicit_status = _confirmation_map(card, field_status)
    if explicit_status:
        # Aggregate aliases cannot supply text on behalf of an unconfirmed field.
        card = {key: card.get(key) for parts in RATING_FIELD_MAP.values() for key in parts}
    breakdown: dict[str, dict[str, Any]] = {}
    missing_fields: list[str] = []
    recommendations: list[str] = []
    score = 0

    for field, weight in RATING_WEIGHTS.items():
        parts = _dimension_text(card, field)
        present_parts = {key: value for key, value in parts.items() if is_meaningful(value)}
        credited_parts = {
            key: value for key, value in present_parts.items()
            if confirmed.get(key, False)
        }
        # In a compound dimension, drafts must not improve even partial credit.
        full_points, quality_reason = _assess(field, credited_parts)
        pending = any(key not in credited_parts for key in present_parts)

        if not present_parts:
            points = 0
            status = "empty"
            reason = "Поле пустое, содержит заглушку или повторяющийся текст; пока баллов нет."
        elif explicit_status and not credited_parts:
            points = 0
            status = "unconfirmed"
            reason = "Заполнено, но ещё не подтверждено бизнесом; баллы начислятся после подтверждения."
        elif full_points == 0:
            points = 0
            status = "invalid"
            reason = quality_reason
        else:
            points = full_points
            status = "complete" if points == weight else "partial"
            reason = quality_reason
            if pending:
                reason += " Неподтверждённые части ответа не учитываются."

        score += points
        gain = weight - points
        suggestion = FIELD_SUGGESTIONS[field] if gain else ""
        if pending:
            suggestion = f"Проверьте и подтвердите поле «{FIELD_LABELS[field]}»."
            if _assess(field, card)[0] < weight:
                suggestion += " " + FIELD_SUGGESTIONS[field]
        breakdown[field] = {
            "label": FIELD_LABELS[field],
            "score": points,
            "max_score": weight,
            "status": status,
            "reason": reason,
            "suggestion": suggestion,
            "potential_gain": gain,
        }
        if gain:
            missing_fields.append(field)
            recommendations.append(suggestion)

    score = min(100, score)
    level = get_level(score)
    top_gap = max(
        (field for field in missing_fields),
        key=lambda field: (
            breakdown[field]["potential_gain"],
            breakdown[field]["status"] == "unconfirmed",
        ),
        default=None,
    )
    if top_gap:
        next_step = (
            f"Чтобы поднять оценку (возможный прирост — до {breakdown[top_gap]['potential_gain']} баллов): "
            f"{breakdown[top_gap]['suggestion']}"
        )
    else:
        next_step = "Описание получило максимум баллов по текущим правилам."
    return {
        "score": score,
        "level": level,
        "score_meaning": SCORE_MEANING,
        "score_explanation": f"{score}/100 — задача {LEVEL_LABELS[level]}.",
        "next_step": next_step,
        "breakdown": breakdown,
        "missing_fields": missing_fields,
        "recommendations": recommendations,
        "potential_gain": 100 - score,
    }


__all__ = ["calculate_rating", "get_level", "is_meaningful"]
