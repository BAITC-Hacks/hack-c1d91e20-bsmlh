from core.models import RATING_WEIGHTS
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
    assert result["level"] == "приоритетная"
    assert result["missing"] == []
    assert all(item["score"] == item["max_score"] for item in result["breakdown"])


def test_unconfirmed_content_earns_zero_and_explains_pending_points():
    card = complete_card()
    result = calculate_rating(card, statuses(card, "ai_draft"))

    assert result["score"] == 0
    assert result["potential_gain"] == 100
    assert all(item["status"] == "unconfirmed" for item in result["breakdown"])
    assert "не подтверждено" in result["breakdown"][0]["reason"]


def test_vague_but_confirmed_values_get_half_credit():
    card = {"expected_result": "Сделать лучше для компании"}
    result = calculate_rating(card, {"expected_result": "confirmed"})
    item = next(row for row in result["breakdown"] if row["field"] == "expected_result")

    assert item["score"] == 7
    assert item["status"] == "partial"
    assert result["score"] == 7


def test_garbage_answers_never_score():
    for junk in ("asdf", "-", "нет", "тест", "123", "слово слово"):
        result = calculate_rating(
            {"expected_result": junk}, {"expected_result": "confirmed"}
        )
        item = next(row for row in result["breakdown"] if row["field"] == "expected_result")
        assert item["score"] == 0, junk
        assert item["status"] == "empty", junk


def test_readiness_level_boundaries():
    assert get_level(0) == "черновик"
    assert get_level(39) == "черновик"
    assert get_level(40) == "рабочая"
    assert get_level(69) == "рабочая"
    assert get_level(70) == "готовая"
    assert get_level(89) == "готовая"
    assert get_level(90) == "приоритетная"
    assert get_level(100) == "приоритетная"


def test_empty_card_has_explanations_for_all_seven_dimensions():
    result = calculate_rating({}, {})

    assert result["score"] == 0
    assert len(result["breakdown"]) == 7
    assert len(result["missing"]) == 7
    assert all(item["reason"] for item in result["breakdown"])
