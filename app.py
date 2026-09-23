"""Streamlit MVP: business draft to a manually selected student proposal."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3

import streamlit as st
from dotenv import load_dotenv

from core.ai import analyze_task, build_card
from core.models import CARD_FIELDS, new_task, new_proposal
from core.rating import calculate_rating
from core.storage import (init_db, list_tasks, save_task, list_proposals,
                          save_proposal, set_proposal_status)

load_dotenv()
st.set_page_config(page_title="AI SANA", page_icon="💡", layout="wide")
LABELS = {
    "title": "Название", "context": "Как задача решается сейчас",
    "need": "Что нужно изменить", "users": "Пользователи",
    "data": "Данные и способ доступа", "constraints": "Сроки и ограничения",
    "expected_result": "Ожидаемый результат", "success_criteria": "Критерии успеха",
    "contact": "Контакт бизнеса", "interaction_format": "Формат обратной связи",
}


def show_rating(rating):
    st.metric("Score", f"{rating['score']} / 100")
    st.progress(rating["score"] / 100)
    st.write(f"Уровень: **{rating['level']}**")
    with st.expander("Из чего складывается рейтинг и как его повысить"):
        for item in rating["breakdown"].values():
            st.write(f"**{item['label']}: {item['score']} / {item['max_score']}**")
            st.caption(item["reason"])
            if item["potential_gain"]:
                st.write(f"+{item['potential_gain']} баллов: {item['suggestion']}")


def constructor():
    st.header("Конструктор задачи")
    if st.session_state.role != "Я бизнес":
        st.info("Для создания задачи выберите роль «Я бизнес».")
        return
    st.session_state.setdefault("raw_input", st.session_state.get("raw_task", ""))
    with st.form("raw_form"):
        raw = st.text_area("Опишите задачу своими словами", key="raw_input",
                           placeholder="Хотим чат-бота для клиентов")
        analyze = st.form_submit_button("Проанализировать задачу")
    if analyze:
        if not raw.strip():
            st.warning("Введите описание задачи.")
        else:
            with st.spinner("Анализируем задачу…"):
                analysis = analyze_task(raw)
            st.session_state.raw_task = raw.strip()
            st.session_state.analysis = analysis
            st.session_state.pop("task", None)
            st.session_state.pop("confirmed_snapshot", None)
            for key in list(st.session_state):
                if key.startswith(("answer_", "card_")):
                    del st.session_state[key]
    analysis = st.session_state.get("analysis")
    if not analysis:
        return
    if analysis.get("provider") == "local":
        st.info("Работает локальный режим: уточняющие вопросы и карточка доступны без API.")
    with st.form("answers_form"):
        st.subheader("Уточните детали")
        answers = {}
        for i, question in enumerate(analysis["questions"][:5]):
            answers[question["field"]] = st.text_area(question["question"], key=f"answer_{i}")
        generate = st.form_submit_button("Сформировать карточку")
    if generate:
        with st.spinner("Готовим редактируемую карточку…"):
            card = build_card(st.session_state.raw_task, answers)
        st.session_state.answers = answers
        st.session_state.task = new_task(st.session_state.raw_task, card=card)
        st.session_state.pop("confirmed_snapshot", None)
        for field in CARD_FIELDS:
            st.session_state[f"card_{field}"] = card[field]
        st.session_state.card_topic = ""
    task = st.session_state.get("task")
    if not task:
        return
    if task["status"] == "published":
        st.success("Задача опубликована. Откройте каталог или отклики в меню слева.")
        return
    st.subheader("Проверьте и отредактируйте карточку")
    st.caption("Заполняйте только известные факты. Пустые поля можно оставить и дополнить позже до публикации.")
    for field in CARD_FIELDS:
        st.session_state.setdefault(f"card_{field}", task["card"].get(field, ""))
    st.session_state.setdefault("card_topic", task.get("topic", ""))
    card = {}
    card["title"] = st.text_input(LABELS["title"], key="card_title").strip()
    topic = st.text_input("Тема / отрасль", key="card_topic").strip()
    columns = st.columns(2)
    for i, field in enumerate(CARD_FIELDS[1:]):
        with columns[i % 2]:
            card[field] = st.text_area(LABELS[field], key=f"card_{field}").strip()
    task["card"] = card
    task["topic"] = topic
    snapshot = {"card": card, "topic": topic}
    confirmed = st.session_state.get("confirmed_snapshot") == snapshot
    if st.button("Подтвердить данные и рассчитать рейтинг"):
        if not card["title"]:
            st.warning("Укажите название задачи.")
        else:
            st.session_state.confirmed_snapshot = snapshot
            confirmed = True
    statuses = {field: ("confirmed" if confirmed else "ai_draft") if card[field] else "empty"
                for field in CARD_FIELDS}
    rating = calculate_rating(card, statuses)
    st.session_state.current_rating = rating
    show_rating(rating)
    if not confirmed:
        st.caption("Баллы начисляются после подтверждения. Изменения карточки требуют нового подтверждения.")
    if st.button("Опубликовать задачу", disabled=not confirmed, type="primary"):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        published = {**task, "card": card, "topic": topic, "field_status": statuses,
                     "score": rating["score"], "level": rating["level"],
                     "status": "published", "published_at": now,
                     "score_history": [{"score": rating["score"], "created_at": now}]}
        save_task(published)
        st.session_state.task = published
        st.rerun()


def catalog():
    st.header("Каталог задач")
    tasks = list_tasks(status="published")
    level = st.selectbox("Уровень готовности", ["Все", "draft", "working", "ready", "priority"])
    st.caption("По умолчанию показаны все опубликованные задачи, включая задачи с низким рейтингом.")
    if not tasks:
        st.info("Пока нет опубликованных задач. Создайте первую в конструкторе.")
        return
    visible = [task for task in tasks if level == "Все" or task["level"] == level]
    if not visible:
        st.info("Для выбранного уровня задач нет.")
    for task in visible:
        with st.container(border=True):
            st.subheader(task["card"].get("title") or "Без названия")
            st.caption(f"{task['topic'] or 'Без темы'} · {task['score']} / 100 · {task['level']}")
            st.write(task["card"].get("need", ""))
            with st.expander("Открыть задачу и отправить предложение"):
                for field in CARD_FIELDS[1:]:
                    st.write(f"**{LABELS[field]}**")
                    st.write(task["card"].get(field) or "Не указано")
                show_rating(calculate_rating(task))
                if st.session_state.role != "Я студенческая команда":
                    st.info("Для отправки предложения выберите роль студенческой команды.")
                    continue
                proposal_key = f"proposal_{task['id']}"
                if st.session_state.get(proposal_key):
                    st.success("Ваше предложение отправлено.")
                    continue
                with st.form(f"form_{proposal_key}"):
                    team = st.text_input("Название команды")
                    idea = st.text_area("Идея решения")
                    plan = st.text_area("План работы")
                    timeline = st.text_input("Срок реализации")
                    link = st.text_input("Ссылка на прототип (необязательно)")
                    submit = st.form_submit_button("Отправить предложение")
                if submit:
                    if not all(value.strip() for value in (team, idea, plan, timeline)):
                        st.warning("Заполните команду, идею, план и срок.")
                    elif link.strip() and not link.strip().lower().startswith(("https://", "http://")):
                        st.warning("Ссылка должна начинаться с https:// или http://.")
                    else:
                        save_proposal(new_proposal(task["id"], team, idea=idea, plan=plan,
                                                   timeline=timeline, link=link))
                        st.session_state[proposal_key] = True
                        st.rerun()


def responses():
    st.header("Отклики команд")
    if st.session_state.role != "Я бизнес":
        st.info("Для просмотра и выбора откликов переключитесь на роль «Я бизнес».")
        return
    st.caption("Демо без регистрации: выберите задачу бизнеса. Решение о команде принимаете вы.")
    tasks = list_tasks(status="published")
    if not tasks:
        st.info("Сначала опубликуйте задачу.")
        return
    by_id = {task["id"]: task for task in tasks}
    task_id = st.selectbox("Задача бизнеса", list(by_id), key="selected_task",
                           format_func=lambda value: by_id[value]["card"].get("title") or value)
    proposals = list_proposals(task_id)
    if not proposals:
        st.info("Предложений пока нет.")
    status_labels = {"new": "Новое", "selected": "Выбрано", "rejected": "Отклонено"}
    for proposal in proposals:
        with st.container(border=True):
            st.subheader(proposal["team_name"])
            st.write(f"Статус: **{status_labels.get(proposal['status'], proposal['status'])}**")
            for field, label in (("idea", "Идея"), ("plan", "План"), ("timeline", "Срок")):
                st.write(f"**{label}:** {proposal[field]}")
            if proposal["link"]:
                st.text(proposal["link"])
            left, right = st.columns(2)
            if left.button("Выбрать", key=f"select_{proposal['id']}", disabled=proposal["status"] == "selected"):
                set_proposal_status(proposal["id"], "selected")
                st.rerun()
            if right.button("Отклонить", key=f"reject_{proposal['id']}", disabled=proposal["status"] == "rejected"):
                set_proposal_status(proposal["id"], "rejected")
                st.rerun()


def main():
    init_db()
    st.title("AI SANA")
    st.write("Превратите бизнес-идею в понятную задачу и найдите студенческую команду.")
    st.sidebar.radio("Ваша роль", ["Я бизнес", "Я студенческая команда"], key="role")
    screen = st.sidebar.radio("Раздел", ["Конструктор", "Каталог", "Отклики"], key="screen")
    if not os.getenv("OPENAI_API_KEY"):
        st.sidebar.caption("Без API-ключа: локальный режим работает.")
    if st.sidebar.button("Загрузить демо-примеры"):
        seed = Path(__file__).parent / "data" / "seed"
        existing = {task["id"] for task in list_tasks()}
        for task in json.loads((seed / "tasks.json").read_text(encoding="utf-8")):
            if task["id"] not in existing:
                rating = calculate_rating(task)
                task.update(score=rating["score"], level=rating["level"])
                save_task(task)
        existing_proposals = {proposal["id"] for proposal in list_proposals()}
        for proposal in json.loads((seed / "proposals.json").read_text(encoding="utf-8")):
            if proposal["id"] not in existing_proposals:
                save_proposal(proposal)
        st.sidebar.success("Демо-примеры загружены.")
    {"Конструктор": constructor, "Каталог": catalog, "Отклики": responses}[screen]()


if __name__ == "__main__":
    try:
        main()
    except (sqlite3.Error, OSError):
        st.error("Не удалось прочитать или сохранить данные. Проверьте доступ к папке data и повторите действие.")
