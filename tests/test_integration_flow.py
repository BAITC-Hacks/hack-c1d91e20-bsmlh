"""Offline smoke test for one complete AI SANA backend flow."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from core.ai import analyze_task, build_card
from core.rating import calculate_rating
from core.storage import (
    init_db,
    list_proposals,
    list_tasks,
    save_proposal,
    save_task,
    set_proposal_status,
)


def test_published_task_and_proposal_flow(tmp_path, monkeypatch):
    # Make the test deterministic and guarantee it cannot call the live API,
    # even when a developer has OPENAI_API_KEY set in their environment.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    raw_text = "Хотим чат-бота для клиентов"
    analysis = analyze_task(raw_text)
    assert len(analysis["questions"]) >= 3

    answers = {
        "context_need": (
            "Сейчас клиенты ждут ответа оператора; нужен чат-бот для частых вопросов."
        ),
        "data": "Доступны FAQ в CSV и каталог услуг через внутренний API.",
        "expected_result": "Рабочий чат-бот для ответов на частые вопросы клиентов.",
        "success_criteria": "Не менее 80% типовых вопросов получают верный ответ.",
        "constraints": "Пилот за 8 недель; персональные данные не передавать.",
        "users": "Клиенты компании, обращающиеся в службу поддержки.",
        "business_contact": (
            "Контакт: менеджер поддержки; еженедельные встречи и обратная связь."
        ),
    }
    card = build_card(raw_text, answers)

    rating = calculate_rating(card)
    assert 0 <= rating["score"] <= 100
    assert rating["level"]
    assert rating["breakdown"]

    task_id = str(uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    task = {
        "id": task_id,
        "created_at": created_at,
        "status": "published",
        "raw_text": raw_text,
        "card": card,
        "score": rating["score"],
        "level": rating["level"],
        "score_history": [rating],
    }
    temp_db = tmp_path / "integration.sqlite3"
    init_db(path=temp_db)
    save_task(task, path=temp_db)

    saved_tasks = list_tasks(status="published", path=temp_db)
    assert any(saved["id"] == task_id for saved in saved_tasks)

    proposal_id = str(uuid4())
    proposal = {
        "id": proposal_id,
        "task_id": task_id,
        "team_name": "Команда Диалог",
        "idea": "Создать чат-бота на основе FAQ и каталога услуг.",
        "plan": "Подготовить базу ответов, собрать прототип и проверить его с клиентами.",
        "timeline": "8 недель",
        "link": "https://example.org/demo",
        "status": "new",
        "created_at": created_at,
    }
    save_proposal(proposal, path=temp_db)

    saved_proposals = list_proposals(task_id, path=temp_db)
    assert any(saved["id"] == proposal_id for saved in saved_proposals)

    set_proposal_status(proposal_id, "selected", path=temp_db)
    selected = next(
        saved for saved in list_proposals(task_id, path=temp_db)
        if saved["id"] == proposal_id
    )
    assert selected["status"] == "selected"
