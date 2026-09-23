from copy import deepcopy

import pytest

from core.models import RATING_FIELD_MAP, RATING_WEIGHTS
from core.rating import calculate_rating, get_level


def complete_card():
    return {
        "context": "Сейчас заявки обрабатываются вручную.",
        "need": "Нужно сократить время обработки заявок.",
        "data": "История заказов доступна в CSV-выгрузке из CRM.",
        "expected_result": "Нужен прототип дашборда для менеджеров.",
        "success_criteria": "Снизить время обработки на 20% за 2 месяца.",
        "constraints": "Срок 3 недели, использовать Python, доступ к тестовой CRM.",
        "users": "Менеджеры отдела продаж.",
        "contact": "Контакт — менеджер проекта.",
        "interaction_format": "Еженедельные встречи и обратная связь в чате.",
    }


def statuses(card, value="confirmed"):
    return {field: value for field in (
        "context", "need", "data", "expected_result", "success_criteria",
        "constraints", "users", "contact", "interaction_format",
    )}


def test_complete_confirmed_card_gets_100_and_priority_level():
    card = complete_card()
    result = calculate_rating(card, statuses(card))

    assert sum(RATING_WEIGHTS.values()) == 100
    assert result["score"] == 100
    assert result["level"] == "priority"
    assert result["missing_fields"] == []
    assert result["recommendations"] == []
    assert all(item["score"] == item["max_score"] for item in result["breakdown"].values())


def test_unconfirmed_content_earns_zero_and_explains_pending_points():
    card = complete_card()
    result = calculate_rating(card, statuses(card, "ai_draft"))

    assert result["score"] == 0
    assert result["potential_gain"] == 100
    assert all(item["status"] == "unconfirmed" for item in result["breakdown"].values())
    assert "не подтверждено" in result["breakdown"]["context_need"]["reason"]


def test_vague_but_confirmed_values_get_half_credit():
    card = {"expected_result": "Сделать лучше для компании"}
    result = calculate_rating(card, {"expected_result": "confirmed"})
    item = result["breakdown"]["expected_result"]

    assert item["score"] == 7
    assert item["status"] == "partial"
    assert result["score"] == 7


def test_garbage_answers_never_score():
    for junk in ("asdf", "-", "нет", "тест", "123", "слово слово"):
        result = calculate_rating(
            {"expected_result": junk}, {"expected_result": "confirmed"}
        )
        item = result["breakdown"]["expected_result"]
        assert item["score"] == 0, junk
        assert item["status"] == "empty", junk


def test_readiness_level_boundaries():
    assert get_level(0) == "draft"
    assert get_level(39) == "draft"
    assert get_level(40) == "working"
    assert get_level(69) == "working"
    assert get_level(70) == "ready"
    assert get_level(89) == "ready"
    assert get_level(90) == "priority"
    assert get_level(100) == "priority"


def test_empty_card_has_explanations_for_all_seven_dimensions():
    result = calculate_rating({}, {})

    assert result["score"] == 0
    assert len(result["breakdown"]) == 7
    assert len(result["missing_fields"]) == 7
    assert len(result["recommendations"]) == 7
    assert all(item["reason"] for item in result["breakdown"].values())


def test_absent_data_and_unknown_deadline_do_not_score():
    card = {"data": "Нет данных в CSV", "constraints": "Срок неизвестен"}
    result = calculate_rating(card, {"data": "confirmed", "constraints": "confirmed"})

    assert result["score"] == 0
    assert result["breakdown"]["data"]["score"] == 0
    assert result["breakdown"]["constraints"]["score"] == 0


def test_vague_data_and_constraints_get_only_partial_credit():
    card = {"data": "Есть CSV-файл", "constraints": "Есть ограничения"}
    result = calculate_rating(card, {"data": "confirmed", "constraints": "confirmed"})

    assert result["breakdown"]["data"]["score"] == 10
    assert result["breakdown"]["constraints"]["score"] == 5


def test_repeated_answer_cannot_fill_two_distinct_requirements():
    combined = "Сейчас заявки обрабатывают вручную, нужен бот для клиентов."
    contact = "Контакт — менеджер; еженедельная встреча."
    card = {"context": combined, "need": combined,
            "contact": contact, "interaction_format": contact}
    confirmed = {field: "confirmed" for field in card}
    result = calculate_rating(card, confirmed)

    assert result["breakdown"]["context_need"]["score"] == 10
    assert result["breakdown"]["business_contact"]["score"] == 5


def test_score_explanation_and_next_step_are_available_for_ui():
    result = calculate_rating({"users": "Студенты колледжа."}, {"users": "confirmed"})

    assert result["score"] == 10
    assert "готовности задачи" in result["score_meaning"].lower()
    assert "10/100" in result["score_explanation"]
    assert "Чтобы поднять оценку" in result["next_step"]


def test_next_step_requests_confirmation_for_ai_draft():
    result = calculate_rating(
        {"data": "История заказов в CSV-файле."},
        {"data": "ai_draft"},
    )

    assert result["score"] == 0
    assert "подтвердите поле" in result["next_step"]
    assert "Данные и материалы" in result["next_step"]


@pytest.mark.parametrize(("field", "dimension", "value"), [
    ("users", "users", "все"),
    ("users", "users", "пользователи вообще"),
    ("data", "data", "есть данные"),
    ("success_criteria", "success_criteria", "чтобы работало"),
    ("constraints", "constraints", "быстро"),
    ("context", "context_need", "нужно улучшить"),
])
def test_vague_answers_cannot_earn_more_than_half(field, dimension, value):
    result = calculate_rating({field: value}, {field: "confirmed"})
    item = result["breakdown"][dimension]

    assert 0 <= item["score"] <= RATING_WEIGHTS[dimension] // 2
    assert item["reason"]
    assert item["suggestion"]
    assert dimension in result["missing_fields"]


def test_all_vague_answers_together_cannot_look_ready():
    card = {
        "context": "нужно улучшить", "need": "чтобы всё было хорошо",
        "users": "все", "data": "есть данные", "constraints": "быстро",
        "success_criteria": "чтобы работало", "expected_result": "полезная система",
        "contact": "есть контакт", "interaction_format": "как-нибудь свяжемся",
    }
    result = calculate_rating(card, statuses(card))

    assert result["score"] <= sum(weight // 2 for weight in RATING_WEIGHTS.values())
    assert result["level"] in {"draft", "working"}
    assert all(item["status"] != "complete" for item in result["breakdown"].values())


@pytest.mark.parametrize("junk", [
    "-", "asdf", "ASDF!", "asdf qwerty", "слово слово", "Слово, слово!",
    "CSV, CSV; CSV", "заказы CSV; заказы CSV", "123", "аааааа", "...", None,
    {"data": "История заказов в CSV"}, ["менеджеры", "продаж"], True,
])
def test_junk_in_every_field_earns_zero(junk):
    card = {field: junk for parts in RATING_FIELD_MAP.values() for field in parts}
    result = calculate_rating(card, statuses(card))

    assert result["score"] == 0
    assert all(item["score"] == 0 for item in result["breakdown"].values())


@pytest.mark.parametrize(("value", "score"), [
    ("История заказов из CRM в CSV-выгрузке.", 20),
    ("Фотографии товаров доступны через API.", 20),
    ("Выгрузка из CRM.", 20),
    ("PDF-документы с инструкциями.", 20),
    ("CSV: поля: дата, сумма, категория.", 20),
    ("Есть данные", 10),
    ("CSV", 10),
    ("История заказов в CRM.", 10),
    ("Полезный CSV", 10),
    ("CSV с заказами есть, но доступа нет.", 10),
    ("CSV с заказами недоступен.", 10),
    ("Нет данных в CSV", 0),
    ("Данных нет", 0),
])
def test_data_needs_both_content_or_source_and_delivery_format(value, score):
    result = calculate_rating({"data": value}, {"data": "confirmed"})
    assert result["breakdown"]["data"]["score"] == score


@pytest.mark.parametrize("artifact", [
    "Прототип", "бот", "Дашборд", "Модель прогноза спроса", "Отчёт о продажах",
])
def test_concrete_artifacts_earn_full_credit(artifact):
    assert calculate_rating({"expected_result": artifact})["score"] == 15


@pytest.mark.parametrize("vague", ["Полезная система", "Инструмент", "Ботинки"])
def test_generic_result_or_accidental_keyword_is_not_a_concrete_artifact(vague):
    assert calculate_rating({"expected_result": vague})["score"] <= 7


@pytest.mark.parametrize("criterion", [
    "Не менее 80% ответов верны.", "Точность 0.95", "F1 >= 0.85",
    "Ответ за 2 секунды.", "Обработать 100 заявок.", "SLA 99,9%.",
    "Готовый прототип до 01.10.2026.", "Дедлайн: 2026-10-01.",
    "Завершить к 1 октября.", "Демонстрация до 18:00.", "Пилот за 1 день.",
])
def test_measurable_success_criteria_earn_full_credit(criterion):
    assert calculate_rating({"success_criteria": criterion})["score"] == 15


@pytest.mark.parametrize("criterion", [
    "чтобы работало", "высокий SLA", "повысить точность", "результат 2026",
    "чтобы работало до 2026 года", "100", "процент ответов",
])
def test_numbers_or_metric_names_without_a_target_are_not_enough(criterion):
    assert calculate_rating({"success_criteria": criterion})["score"] <= 7


@pytest.mark.parametrize("constraint", [
    "За 1 день", "Срок 3 недели", "Только Python", "До 01.10.2026",
    "Бюджет 100000 тенге", "Без персональных данных", "Нет доступа к интернету",
])
def test_concrete_constraints_earn_full_credit(constraint):
    assert calculate_rating({"constraints": constraint})["score"] == 10


@pytest.mark.parametrize("users", [
    "Менеджеры отдела продаж", "Студенты колледжа", "Диспетчеры такси",
])
def test_specific_user_groups_earn_full_credit(users):
    assert calculate_rating({"users": users})["score"] == 10


@pytest.mark.parametrize(("context", "need", "score"), [
    ("Сейчас заявки обрабатываются вручную.", "Сократить время обработки заявок.", 20),
    ("Операторы сейчас отвечают вручную.", "Нужен бот для ответов клиентам.", 20),
    ("Сейчас всё плохо", "Нужно всё улучшить", 10),
    ("нужно улучшить", "Хотим сделать лучше", 10),
    ("Сейчас заявки обрабатываются вручную.", "", 10),
    ("", "Сократить время обработки заявок.", 10),
])
def test_context_needs_current_situation_and_desired_change(context, need, score):
    card = {"context": context, "need": need}
    assert calculate_rating(card)["breakdown"]["context_need"]["score"] == score


def test_punctuation_changes_do_not_hide_duplicate_context():
    text = "Сейчас заявки обрабатываются вручную, нужно сократить время."
    card = {"context": text, "need": text.upper().replace(",", ";").replace(".", "!")}
    assert calculate_rating(card)["score"] == 10


@pytest.mark.parametrize(("contact", "interaction", "score"), [
    ("Менеджер проекта", "Еженедельный созвон", 10),
    ("owner@example.org", "Ответы по почте", 10),
    ("Иван Петров", "Встречи по вторникам", 10),
    ("+7 777 123 45 67", "Обратная связь в чате", 10),
    ("Менеджер проекта", "", 5),
    ("", "Еженедельный созвон", 5),
    ("есть контакт", "Еженедельный созвон", 5),
    ("Менеджер проекта", "Еженедельно", 5),
    ("не знаю", "-", 0),
])
def test_business_contact_requires_contact_and_interaction(contact, interaction, score):
    card = {"contact": contact, "interaction_format": interaction}
    assert calculate_rating(card)["score"] == score


@pytest.mark.parametrize("status", ["ai_draft", "draft", "unconfirmed", "pending", "false", "", False, None])
def test_every_unconfirmed_status_scores_zero_even_with_concrete_content(status):
    card = complete_card()
    assert calculate_rating(card, statuses(card, status))["score"] == 0


def test_explicit_empty_status_map_does_not_assume_confirmation():
    assert calculate_rating(complete_card(), {})["score"] == 0


@pytest.mark.parametrize("dimension", list(RATING_FIELD_MAP))
def test_unconfirmed_dimension_contributes_nothing_to_an_otherwise_complete_card(dimension):
    card = complete_card()
    confirmed = statuses(card)
    for field in RATING_FIELD_MAP[dimension]:
        confirmed[field] = "ai_draft"
    result = calculate_rating(card, confirmed)

    assert result["breakdown"][dimension]["score"] == 0
    assert result["score"] == 100 - RATING_WEIGHTS[dimension]


@pytest.mark.parametrize("confirmed_field", ["context", "need", "contact", "interaction_format"])
def test_draft_text_cannot_improve_a_partly_confirmed_compound_dimension(confirmed_field):
    card = complete_card()
    confirmed = {confirmed_field: "confirmed"}
    before = calculate_rating(card, confirmed)
    confirmed_only = {confirmed_field: card[confirmed_field]}
    after = calculate_rating(confirmed_only, confirmed)

    assert before["score"] == after["score"]
    assert before["score"] in {5, 10}


@pytest.mark.parametrize("wrapped", [False, True])
def test_embedded_statuses_and_explicit_override_are_respected(wrapped):
    card = complete_card()
    payload = {"card": card} if wrapped else dict(card)
    payload["field_status"] = statuses(card, "ai_draft")

    assert calculate_rating(payload)["score"] == 0
    assert calculate_rating(payload, statuses(card))["score"] == 100
    payload["field_status"] = statuses(card)
    assert calculate_rating(payload, {})["score"] == 0


@pytest.mark.parametrize("malformed", ["ai_draft", [], None])
def test_malformed_embedded_statuses_fail_closed(malformed):
    card = complete_card()
    card["field_status"] = malformed
    assert calculate_rating(card)["score"] == 0
    assert calculate_rating({"card": complete_card(), "field_status": malformed})["score"] == 0


def test_unconfirmed_aggregate_alias_cannot_supply_confirmed_field_content():
    card = {
        "context_need": "Сейчас заявки вручную; нужно автоматизировать обработку.",
        "business_contact": "Менеджер проекта, еженедельный созвон.",
    }
    assert calculate_rating(card, {"context": "confirmed", "contact": "confirmed"})["score"] == 0


def test_rating_is_deterministic_does_not_mutate_input_and_totals_match():
    card = complete_card()
    card["data"] = "есть данные"
    task = {"card": card, "field_status": statuses(card)}
    original = deepcopy(task)
    result = calculate_rating(task)

    assert task == original
    assert result == calculate_rating(task)
    assert result["score"] == sum(item["score"] for item in result["breakdown"].values())
    assert result["potential_gain"] == 100 - result["score"]
    assert result["potential_gain"] == sum(item["potential_gain"] for item in result["breakdown"].values())


def test_confirming_vague_draft_does_not_promise_full_score():
    card = complete_card()
    card["data"] = "есть данные"
    confirmed = statuses(card)
    confirmed["data"] = "ai_draft"
    result = calculate_rating(card, confirmed)

    assert result["score"] == 80
    assert "подтвердите" in result["breakdown"]["data"]["suggestion"]
    assert "вид данных" in result["breakdown"]["data"]["suggestion"]
    confirmed["data"] = "confirmed"
    assert calculate_rating(card, confirmed)["score"] == 90
