"""AI SANA: native Streamlit screens using the Figma visual system."""
from copy import deepcopy
from datetime import datetime, timezone
from html import escape
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlparse

import streamlit as st
from dotenv import load_dotenv

from core.ai import analyze_task, build_card
from core.models import CARD_FIELDS, RATING_FIELD_MAP, new_task, new_proposal
from core.rating import calculate_rating, get_level
from core.storage import (init_db, get_task, list_tasks, save_task, list_proposals,
                          save_proposal, set_proposal_status)

load_dotenv()
st.set_page_config(page_title="AI SANA", page_icon="💡", layout="wide")
ROOT = Path(__file__).resolve().parent
LABELS = {
    "title": "Название задачи", "context": "Что происходит сейчас?",
    "need": "Что хотите улучшить?", "users": "Кто будет пользоваться решением?",
    "data": "Какие данные уже есть?", "constraints": "Сроки и ограничения",
    "expected_result": "Ожидаемый результат", "success_criteria": "Как поймём, что получилось?",
    "contact": "Контакт бизнеса", "interaction_format": "Как будем взаимодействовать?",
}
CARD_EXAMPLES = {
    "title": "Например: Чат-бот для вопросов клиентов",
    "context": "Сейчас менеджеры вручную отвечают на вопросы клиентов в WhatsApp.",
    "need": "Хотим быстрее отвечать на типовые вопросы и снизить нагрузку на менеджеров.",
    "users": "Клиенты интернет-магазина и сотрудники поддержки.",
    "data": "Есть FAQ в Excel. Предоставим команде тестовую копию.",
    "constraints": "Прототип нужен за 3 недели. Используем только обезличенные данные.",
    "expected_result": "Рабочий прототип чат-бота для типовых вопросов.",
    "success_criteria": "Бот верно отвечает на 8 из 10 тестовых вопросов.",
    "contact": "Контактное лицо — менеджер поддержки, email или Telegram.",
    "interaction_format": "Созвон раз в неделю и обратная связь в чате.",
}
PRIMARY_FIELDS = ("title", "context", "need", "data", "expected_result", "success_criteria")
LEVEL_LABELS = {"draft": "Черновик", "working": "Рабочая", "ready": "Готовая", "priority": "Приоритетная"}
PROPOSAL_LABELS = {"new": "На рассмотрении", "selected": "Выбрана", "rejected": "Отклонена"}
PROFILE_TAGS = (("interests", "Интересы", "AI, FinTech, Retail, Analytics"),
                ("skills", "Навыки", "Python, Machine Learning, Data Analysis, Backend"),
                ("technologies", "Технологии", "Python, Pandas, OpenAI API, SQL, Streamlit"))


def brand():
    st.markdown('<div class="brand"><span class="brand-mark">AI</span><span>SANA</span></div>', unsafe_allow_html=True)


def heading(title, subtitle):
    st.title(title)
    st.caption(subtitle)


def badge(level, score=None):
    style = level if level in LEVEL_LABELS else "draft"
    label = LEVEL_LABELS.get(level, level)
    text = f"{score} / 100 · {label}" if score is not None else label
    st.markdown(f'<span class="badge {style}">{escape(text)}</span>', unsafe_allow_html=True)


def navigate(screen, task_id=None):
    st.session_state.ui_screen = screen
    if task_id is not None:
        st.session_state.open_task_id = task_id
        if screen == "Отклики":
            st.session_state.responses_task = task_id


def choose_role(role):
    st.session_state.active_role = role
    navigate("Мои задачи" if role == "business" else "Каталог")


def open_own_profile(editing=False):
    if st.session_state.get("ui_screen") not in {"Профиль команды", "Профиль бизнеса"}:
        st.session_state.profile_return_screen = st.session_state.get("ui_screen", "Каталог")
    st.session_state.profile_proposal_id = None
    st.session_state.profile_editing = editing
    if editing:
        for key in list(st.session_state):
            if key.startswith(("team_profile_field_", "business_profile_field_")):
                del st.session_state[key]
    navigate("Профиль бизнеса" if st.session_state.active_role == "business" else "Профиль команды")


def open_team_profile(proposal_id=None):
    if proposal_id is None:
        open_own_profile()
        return
    if st.session_state.get("ui_screen") not in {"Профиль команды", "Профиль бизнеса"}:
        st.session_state.profile_return_screen = st.session_state.get("ui_screen", "Каталог")
    st.session_state.profile_proposal_id = proposal_id
    st.session_state.profile_editing = False
    navigate("Профиль команды")


def profile_tags(label, values):
    st.caption(label)
    if values:
        tags = "".join(f'<span class="team-profile-tag">{escape(value)}</span>' for value in values)
        st.markdown(f'<div class="team-profile-tags">{tags}</div>', unsafe_allow_html=True)
    else:
        st.caption("Пока не указаны")


def team_profile():
    proposal_id = st.session_state.get("profile_proposal_id")
    own_profile = proposal_id is None and st.session_state.active_role == "student"
    st.button("← Назад", key="profile_back", on_click=navigate,
              args=(st.session_state.get("profile_return_screen", "Каталог"),))
    heading("Профиль команды", "Расскажите бизнесу, кто вы и какие задачи умеете решать."
            if own_profile else "Команда, которая откликнулась на задачу.")
    if own_profile:
        profile = st.session_state.team_profile
        st.caption("Профиль сохраняется на время текущего визита. К отклику прикладывается его копия на момент отправки.")
        if st.session_state.pop("team_profile_updated", False):
            st.success("Профиль обновлён")
    else:
        proposal = next((item for item in list_proposals() if item["id"] == proposal_id), None)
        if not proposal:
            st.info("Отклик не найден.")
            return
        profile = st.session_state.proposal_profiles.get(proposal_id, {"team_name": proposal["team_name"]})
        if proposal_id not in st.session_state.proposal_profiles:
            st.info("Подробный профиль этого отклика недоступен в текущем визите. Известно только название команды.")
        else:
            st.caption("Данные команды на момент отправки отклика.")

    with st.container(border=True, key="panel_team_profile"):
        if own_profile and st.session_state.get("profile_editing"):
            with st.form("team_profile_form"):
                st.subheader("Настройки профиля")
                edited = {"team_name": st.text_input("Название команды", value=profile.get("team_name", ""),
                          key="team_profile_field_team_name", placeholder="Например: DataLab", max_chars=80).strip()}
                edited["organization"] = st.text_input("Университет / организация (необязательно)",
                    value=profile.get("organization", ""), key="team_profile_field_organization",
                    placeholder="Например: AITU", max_chars=120).strip()
                edited["description"] = st.text_area("О команде (необязательно)", value=profile.get("description", ""),
                    key="team_profile_field_description",
                    placeholder="Например: Разрабатываем AI и data-driven решения для бизнеса.", max_chars=600).strip()
                for field, label, example in PROFILE_TAGS:
                    value = st.text_input(label, value=", ".join(profile.get(field, [])),
                                          key=f"team_profile_field_{field}", placeholder=example,
                                          help="Перечислите через запятую.", max_chars=500)
                    edited[field] = list(dict.fromkeys(tag.strip() for tag in re.split(r"[,;\n·]+", value) if tag.strip()))
                edited["link"] = st.text_input("GitHub / демо (необязательно)", value=profile.get("link", ""),
                    key="team_profile_field_link", placeholder="https://github.com/team/project", max_chars=300).strip()
                edited["contact"] = st.text_input("Контакт (необязательно)", value=profile.get("contact", ""),
                    key="team_profile_field_contact", placeholder="Например: @datalab или team@example.com", max_chars=160).strip()
                st.caption("Обязательные поля: название команды, интересы, навыки и технологии.")
                save, cancel = st.columns(2)
                saved = save.form_submit_button("Сохранить изменения", type="primary", use_container_width=True)
                cancelled = cancel.form_submit_button("Отмена", use_container_width=True)
                if cancelled:
                    st.session_state.profile_editing = False
                    st.rerun()
                if saved:
                    try:
                        link = urlparse(edited["link"])
                        valid_link = not edited["link"] or (link.scheme in {"https", "http"} and bool(link.hostname))
                    except ValueError:
                        valid_link = False
                    if not all(edited[field] for field in ("team_name", "interests", "skills", "technologies")):
                        st.warning("Укажите название команды, интересы, навыки и технологии.")
                    elif not valid_link:
                        st.warning("Укажите полную ссылку на GitHub или демо с https:// или http://.")
                    else:
                        st.session_state.team_profile = edited
                        st.session_state.profile_editing = False
                        st.session_state.team_profile_updated = True
                        st.rerun()
            return

        name = profile.get("team_name") or "Ваша команда"
        initials = "".join(word[0] for word in name.split()[:2]).upper()
        st.markdown(
            f'<div class="team-profile-header"><div class="team-profile-avatar" aria-hidden="true">{escape(initials)}</div>'
            f'<div><h2>{escape(name)}</h2><p>{escape(profile.get("organization", ""))}</p></div></div>',
            unsafe_allow_html=True,
        )
        st.subheader("О команде")
        st.write(profile.get("description") or "Описание пока не добавлено.")
        for field, label, _ in PROFILE_TAGS:
            profile_tags(label, profile.get(field, []))
        if profile.get("link"):
            st.link_button("GitHub / демо ↗", profile["link"])
        st.subheader("Контакт")
        st.write(profile.get("contact") or "Пока не указан")
        if own_profile:
            st.button("Редактировать профиль", key="edit_team_profile", type="primary",
                      on_click=open_own_profile, args=(True,))


def business_profile():
    if st.session_state.active_role != "business":
        return
    st.button("← Назад", key="business_profile_back", on_click=navigate,
              args=(st.session_state.get("profile_return_screen", "Мои задачи"),))
    heading("Профиль бизнеса", "Расскажите о компании и оставьте контакт для связи.")
    st.caption("Профиль сохраняется на время текущего визита.")
    profile = st.session_state.business_profile
    if st.session_state.pop("business_profile_updated", False):
        st.success("Профиль обновлён")
    with st.container(border=True, key="panel_business_profile"):
        if st.session_state.get("profile_editing"):
            with st.form("business_profile_form"):
                st.subheader("Настройки профиля")
                edited = {}
                for field, label, example in (
                    ("company_name", "Название компании", "Например: SANA Retail"),
                    ("representative_name", "Имя представителя", "Например: Айдана Омарова"),
                    ("industry", "Отрасль", "Например: Ритейл"),
                    ("description", "О компании", "Чем занимается компания и кому помогает?"),
                    ("contact", "Email / контакт", "Например: hello@example.com или @company"),
                ):
                    widget = st.text_area if field == "description" else st.text_input
                    edited[field] = widget(label, value=profile.get(field, ""),
                        key=f"business_profile_field_{field}", placeholder=example,
                        max_chars=600 if field == "description" else 160).strip()
                st.caption("Обязательное поле: название компании.")
                save, cancel = st.columns(2)
                saved = save.form_submit_button("Сохранить изменения", type="primary", use_container_width=True)
                cancelled = cancel.form_submit_button("Отмена", use_container_width=True)
                if cancelled:
                    st.session_state.profile_editing = False
                    st.rerun()
                if saved:
                    if not edited["company_name"]:
                        st.warning("Укажите название компании.")
                    else:
                        st.session_state.business_profile = edited
                        st.session_state.profile_editing = False
                        st.session_state.business_profile_updated = True
                        st.rerun()
            return
        name = profile.get("company_name") or "Ваша компания"
        initials = "".join(word[0] for word in name.split()[:2]).upper()
        st.markdown(
            f'<div class="team-profile-header"><div class="team-profile-avatar" aria-hidden="true">{escape(initials)}</div>'
            f'<div><h2>{escape(name)}</h2><p>{escape(profile.get("industry", ""))}</p></div></div>',
            unsafe_allow_html=True,
        )
        st.subheader("О компании")
        st.write(profile.get("description") or "Описание пока не добавлено.")
        st.subheader("Представитель")
        st.write(profile.get("representative_name") or "Пока не указан")
        st.subheader("Email / контакт")
        st.write(profile.get("contact") or "Пока не указан")
        st.button("Редактировать профиль", key="edit_business_profile", type="primary",
                  on_click=open_own_profile, args=(True,))


def start_task():
    if st.session_state.get("task", {}).get("status") == "published":
        for key in list(st.session_state):
            if key.startswith(("card_", "answer_")) or key in {
                "task", "analysis", "answers", "raw_input", "raw_task", "raw_draft", "confirmed_snapshot", "workflow_step",
                "readiness_preview", "current_rating"
            }:
                del st.session_state[key]
    navigate("Создать задачу")


def invalidate_confirmation():
    st.session_state.pop("confirmed_snapshot", None)
    st.session_state.pop("current_rating", None)


def preview_readiness(card):
    # Hypothetical confirmation, only for the preview. Never store these flags
    # or this score on the task; publication uses the actual confirmation below.
    rating = calculate_rating(card, {field: "confirmed" for field in CARD_FIELDS})
    previous = st.session_state.get("readiness_preview")
    if previous is None or previous["card"] != card:
        delta = rating["score"] - (previous["rating"]["score"] if previous else 0)
        st.session_state.readiness_preview = {"card": deepcopy(card), "rating": rating, "delta": delta}
    return rating, st.session_state.readiness_preview["delta"]


def show_rating(rating, *, preview=False, delta=0):
    score, level = rating["score"], rating["level"]
    with st.container(border=True, key="panel_rating"):
        st.caption("Прогноз готовности" if preview else "Подтверждённая готовность")
        st.metric("Готовность", f"{score} / 100", label_visibility="collapsed",
                  delta=(f"{delta:+d}" if delta else "0") if preview else None,
                  delta_color="normal" if delta else "off")
        if preview:
            st.caption("Изменение относительно предыдущего варианта. Прогноз обновляется после выхода из поля.")
        badge(level)
        st.progress(score / 100)
        next_score = next((value for value in range(score + 1, 101) if get_level(value) != level), None)
        if next_score is None:
            st.caption("Достигнут максимальный уровень готовности.")
        else:
            st.caption(f"До уровня «{LEVEL_LABELS[get_level(next_score)]}» — {next_score - score} баллов")
        recommendations = sorted(
            (item for item in rating["breakdown"].values() if item["potential_gain"]),
            key=lambda item: item["potential_gain"], reverse=True,
        )[:3]
        if recommendations:
            st.markdown("**Что добавить**" if preview else "**Что улучшить**")
            for item in recommendations:
                st.markdown(
                    f'<div class="recommendation"><b>+{item["potential_gain"]}</b>'
                    f'<span>{escape(item["suggestion"])}</span></div>', unsafe_allow_html=True,
                )
        with st.expander("Показать полный разбор"):
            for item in rating["breakdown"].values():
                st.write(f"**{item['label']}** · {item['score']} / {item['max_score']}")
                st.progress(item["score"] / item["max_score"])
                st.caption(item["reason"])
        if preview:
            st.caption("Предварительная оценка. Итоговый рейтинг появится после подтверждения карточки.")


def welcome():
    with st.container(key="welcome"):
        brand()
        heading("Начните работу с AI SANA", "Выберите, как вы будете использовать платформу.")
        business, student = st.columns(2, gap="large")
        with business, st.container(border=True, key="panel_business"):
            st.markdown('<div class="role-icon">▤</div>', unsafe_allow_html=True)
            st.subheader("Я представляю бизнес")
            st.write("Опубликуйте реальную задачу, улучшите её с помощью AI и найдите студенческую команду.")
            st.button("Продолжить как бизнес →", key="choose_business", type="primary",
                      use_container_width=True, on_click=choose_role, args=("business",))
        with student, st.container(border=True, key="panel_student"):
            st.markdown('<div class="role-icon">◈</div>', unsafe_allow_html=True)
            st.subheader("Я студент / команда")
            st.write("Находите реальные бизнес-задачи, предлагайте идеи и создавайте решения для компаний.")
            st.button("Продолжить как команда →", key="choose_student",
                      use_container_width=True, on_click=choose_role, args=("student",))
        st.caption("Без регистрации · Выбор команды всегда остаётся за бизнесом")


def constructor():
    if st.session_state.active_role != "business":
        return
    step = st.session_state.setdefault("workflow_step", 1)
    st.markdown(f'<div class="eyebrow">ШАГ {step} ИЗ 3</div>', unsafe_allow_html=True)
    steps = ("Описание", "Уточнение", "Карточка + рейтинг")
    st.markdown('<div class="steps">' + ''.join(
        f'<span class="{"active" if step == index else ""}">{index}. {label}</span>'
        for index, label in enumerate(steps, 1)) + '</div>', unsafe_allow_html=True)
    if step == 1:
        left, right = st.columns([2.2, 1], gap="large")
        with left, st.container(key="describe"):
            heading("Опишите задачу", "Расскажите своими словами, что хотите улучшить. Мы поможем превратить идею в понятную задачу.")
            with st.container(border=True, key="panel_description"):
                st.session_state.setdefault("raw_input", st.session_state.get("raw_draft", st.session_state.get("raw_task", "")))
                raw = st.text_area("Описание задачи", key="raw_input", height=190,
                                   placeholder="Например: Сейчас менеджеры отвечают клиентам вручную в WhatsApp. Хотим сократить время ответа и автоматизировать типовые вопросы.",
                                   on_change=invalidate_confirmation)
                st.session_state.raw_draft = raw
                st.caption("Можно начать с 1–2 предложений")
                if st.button("Продолжить →", key="analyze", type="primary"):
                    if not raw.strip():
                        st.warning("Добавьте короткое описание задачи.")
                    else:
                        with st.spinner("Подбираем уточняющие вопросы…"):
                            analysis = analyze_task(raw)
                        st.session_state.raw_task = raw.strip()
                        st.session_state.analysis = analysis
                        st.session_state.answers = {}
                        for key in list(st.session_state):
                            if key.startswith(("answer_", "card_")) or key in ("task", "confirmed_snapshot"):
                                del st.session_state[key]
                        st.session_state.workflow_step = 2
                        st.rerun()
        with right:
            rating, delta = preview_readiness({"need": raw.strip()})
            show_rating(rating, preview=True, delta=delta)
            st.caption("Пока учтено общее описание. Остальные поля уточним на следующих шагах.")
        return
    if step == 2:
        analysis = st.session_state.get("analysis")
        if not analysis:
            st.session_state.workflow_step = 1
            st.rerun()
        heading("Уточним несколько деталей", "Чем точнее задача, тем проще команде предложить подходящее решение.")
        left, right = st.columns([2.2, 1], gap="large")
        with left:
            with st.expander("Ваше описание"):
                st.write(st.session_state.raw_task)
            if st.session_state.get("task"):
                st.caption("Повторная генерация заменит текущую карточку. Ответы можно уточнить перед продолжением.")
            answers = dict(st.session_state.get("answers", {}))
            questions = analysis["questions"][:4]
            for offset in range(0, len(questions), 2):
                columns = st.columns(2)
                for index, question in enumerate(questions[offset:offset + 2], offset):
                    field = question["field"]
                    example_field = {"context_need": "context", "business_contact": "contact"}.get(field, field)
                    with columns[index % 2], st.container(border=True, key=f"panel_question_{index}"):
                        st.caption(f"ВОПРОС {index + 1}")
                        key = f"answer_{index}"
                        st.session_state.setdefault(key, answers.get(field, ""))
                        answers[field] = st.text_area(question["question"], key=key, height=130,
                                                       placeholder=CARD_EXAMPLES.get(example_field, "Укажите известные вам детали."),
                                                       on_change=invalidate_confirmation)
            st.session_state.answers = answers
            back, forward = st.columns([1, 2])
            if back.button("← Назад", key="back_description"):
                st.session_state.workflow_step = 1
                st.rerun()
            if forward.button("Сформировать карточку →", key="generate", type="primary", use_container_width=True):
                with st.spinner("Готовим редактируемую карточку…"):
                    card = build_card(st.session_state.raw_task, answers)
                st.session_state.task = new_task(st.session_state.raw_task, card=card)
                st.session_state.pop("confirmed_snapshot", None)
                for field in CARD_FIELDS:
                    st.session_state[f"card_{field}"] = card[field]
                st.session_state.card_topic = ""
                st.session_state.workflow_step = 3
                st.rerun()
        with right:
            preview_card = {"need": st.session_state.raw_task}
            for field, value in answers.items():
                if not value.strip():
                    continue
                for target in RATING_FIELD_MAP.get(field, (field,)):
                    if target in CARD_FIELDS:
                        preview_card[target] = value.strip()
            rating, delta = preview_readiness(preview_card)
            show_rating(rating, preview=True, delta=delta)
            if analysis.get("provider") == "local":
                st.caption("Локальный режим: сценарий доступен без API-ключа.")
        return
    task = st.session_state.get("task")
    if not task:
        st.session_state.workflow_step = 1
        st.rerun()
    if task["status"] == "published":
        heading("Задача опубликована", "Теперь студенческие команды могут отправлять предложения.")
        left, right = st.columns([2, 1], gap="large")
        with left, st.container(border=True, key="panel_published"):
            st.subheader(task["card"]["title"])
            st.write(task["card"].get("need", ""))
            st.button("Открыть в каталоге →", key="published_open", type="primary", on_click=navigate, args=("Карточка", task["id"]))
            st.button("Создать ещё задачу", key="create_another", on_click=start_task)
        with right:
            show_rating(calculate_rating(task))
        return
    heading("Проверьте карточку", "Мы собрали задачу из ваших ответов. Проверьте и при необходимости измените.")
    left, right = st.columns([2.2, 1], gap="large")
    with left:
        for field in CARD_FIELDS:
            st.session_state.setdefault(f"card_{field}", task["card"].get(field, ""))
        st.session_state.setdefault("card_topic", task.get("topic", ""))
        card = {}
        with st.container(border=True, key="panel_review"):
            for field in PRIMARY_FIELDS:
                widget = st.text_input if field == "title" else st.text_area
                card[field] = widget(LABELS[field], key=f"card_{field}", placeholder=CARD_EXAMPLES[field],
                                     on_change=invalidate_confirmation).strip()
            with st.expander("Показать все поля"):
                for field in CARD_FIELDS:
                    if field not in PRIMARY_FIELDS:
                        card[field] = st.text_area(LABELS[field], key=f"card_{field}", placeholder=CARD_EXAMPLES[field],
                                                  on_change=invalidate_confirmation).strip()
                topic = st.text_input("Тема / отрасль", key="card_topic", placeholder="Например: Ритейл, автоматизация",
                                      on_change=invalidate_confirmation).strip()
        task.update(card=card, topic=topic)
        snapshot = {"card": card, "topic": topic}
        confirmed = st.session_state.get("confirmed_snapshot") == snapshot
        if not confirmed:
            invalidate_confirmation()
        back, confirm = st.columns([1, 2])
        if back.button("← Назад", key="back_questions"):
            st.session_state.workflow_step = 2
            st.rerun()
        if confirm.button("Подтвердить карточку", key="confirm", use_container_width=True):
            if not card["title"]:
                st.warning("Укажите название задачи.")
            else:
                st.session_state.confirmed_snapshot = snapshot
                confirmed = True
        st.caption("Заполняйте только известные факты. После редактирования карточку нужно подтвердить заново.")
    statuses = {field: ("confirmed" if confirmed else "ai_draft") if card[field] else "empty" for field in CARD_FIELDS}
    rating = calculate_rating(card, statuses)
    st.session_state.current_rating = rating
    preview_rating, delta = preview_readiness(card)
    with right:
        show_rating(rating if confirmed else preview_rating, preview=not confirmed, delta=delta)
        if confirmed:
            st.success("Данные подтверждены")
        else:
            st.caption("Проверьте поля и подтвердите данные перед публикацией.")
        if st.button("Опубликовать задачу →", key="publish", disabled=not confirmed, type="primary", use_container_width=True):
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            published = {**task, "field_status": statuses, "score": rating["score"], "level": rating["level"],
                         "status": "published", "published_at": now,
                         "score_history": [{"score": rating["score"], "created_at": now}]}
            save_task(published)
            st.session_state.task = published
            st.session_state.owned_task_ids.add(published["id"])
            st.rerun()


def catalog():
    heading("Каталог задач", "Выберите задачу, которая подходит вашей команде.")
    tasks = list_tasks(status="published")
    search_col, topic_col, level_col = st.columns([2, 1, 1])
    search = search_col.text_input("Поиск задач", placeholder="Название или описание…").strip().casefold()
    topic = topic_col.selectbox("Тема", ["Все темы"] + sorted({task["topic"] for task in tasks if task["topic"]}))
    level_codes = {"Любая готовность": None, **{label: code for code, label in LEVEL_LABELS.items()}}
    level = level_col.selectbox("Готовность", list(level_codes))
    visible = [task for task in tasks
               if (topic == "Все темы" or task["topic"] == topic)
               and (level_codes[level] is None or task["level"] == level_codes[level])
               and (not search or search in (task["card"].get("title", "") + " " + task["card"].get("need", "")).casefold())]
    st.caption(f"Найдено задач: {len(visible)} · По готовности ↓ · Задачи с низким рейтингом тоже доступны")
    if not visible:
        st.info("Задач пока нет или они не подходят под выбранные фильтры.")
    for offset in range(0, len(visible), 3):
        columns = st.columns(3, gap="medium")
        for index, task in enumerate(visible[offset:offset + 3]):
            with columns[index], st.container(border=True, key=f"panel_task_{task["id"]}"):
                badge(task["level"], task["score"])
                st.progress(task["score"] / 100)
                st.subheader(task["card"].get("title") or "Без названия")
                description = task["card"].get("need") or "Описание ещё не добавлено."
                st.write(description[:180] + ("…" if len(description) > 180 else ""))
                st.caption(task["topic"] or "Тема не указана")
                st.caption("Результат: " + (task["card"].get("expected_result") or "ещё не указан"))
                st.button("Открыть задачу →", key=f"open_{task['id']}", use_container_width=True,
                          on_click=navigate, args=("Карточка", task["id"]))


def details():
    st.button("← Назад к каталогу", key="catalog_back", on_click=navigate, args=("Каталог",))
    task = get_task(st.session_state.get("open_task_id", ""))
    if not task or task["status"] != "published":
        st.info("Эта задача пока не опубликована.")
        return
    badge(task["level"], task["score"])
    heading(task["card"].get("title") or "Без названия", task["topic"] or "Тема не указана")
    left, right = st.columns([2, 1], gap="large")
    with left, st.container(border=True, key="panel_details"):
        for field in CARD_FIELDS[1:]:
            st.caption(LABELS[field].upper())
            st.write(task["card"].get(field) or "Не указано")
    with right:
        if st.session_state.active_role == "business":
            show_rating(calculate_rating(task))
            st.button("Посмотреть отклики →", key="details_responses", type="primary", use_container_width=True,
                      on_click=navigate, args=("Отклики", task["id"]))
            return
        sent = st.session_state.sent_by_task.get(task["id"])
        if sent:
            st.success("Предложение отправлено")
            st.button("Мои отклики →", key="sent_open", on_click=navigate, args=("Мои отклики",))
            return
        with st.container(border=True, key="panel_proposal"):
            st.subheader("Отправить предложение")
            st.caption("Расскажите о команде и вашем подходе к задаче.")
            draft = st.session_state.proposal_drafts.setdefault(task["id"], {})
            profile = st.session_state.team_profile
            if not draft.get("team_name"):
                draft["team_name"] = profile.get("team_name", "")
            fields = (("team_name", "Название команды", "Например: Data Nomads"),
                      ("idea", "Идея решения", "Опишите ваш подход…"),
                      ("plan", "План работы", "Этапы и результаты каждого этапа…"),
                      ("timeline", "Срок выполнения", "Например: 3 недели"),
                      ("link", "Ссылка на прототип (необязательно)", "https://…"))
            for field, label, example in fields:
                key = f"proposal_{task['id']}_{field}"
                st.session_state.setdefault(key, draft.get(field, ""))
                widget = st.text_area if field in ("idea", "plan") else st.text_input
                draft[field] = widget(label, key=key, placeholder=example).strip()
            attach_profile = bool(profile) and draft["team_name"] == profile.get("team_name")
            if attach_profile:
                st.caption("К отклику будет приложен ваш профиль с навыками и технологиями.")
            elif profile:
                st.caption("Название команды отличается от профиля. Профиль к этому отклику не прикрепится.")
            else:
                st.caption("Заполните профиль, чтобы бизнес мог узнать о навыках вашей команды.")
            st.button("Открыть профиль" if profile else "Заполнить профиль", key="proposal_profile",
                      on_click=open_team_profile, use_container_width=True)
            if st.button("Отправить предложение", key="send_proposal", type="primary", use_container_width=True):
                link = urlparse(draft["link"])
                if not all(draft[field] for field in ("team_name", "idea", "plan", "timeline")):
                    st.warning("Заполните команду, идею, план и срок.")
                elif draft["link"] and (link.scheme not in {"https", "http"} or not link.netloc):
                    st.warning("Укажите полную ссылку с https:// или http://.")
                else:
                    proposal = new_proposal(task["id"], draft["team_name"], idea=draft["idea"],
                                            plan=draft["plan"], timeline=draft["timeline"], link=draft["link"])
                    save_proposal(proposal)
                    if attach_profile:
                        st.session_state.proposal_profiles[proposal["id"]] = deepcopy(profile)
                    st.session_state.sent_by_task[task["id"]] = proposal["id"]
                    st.rerun()


def responses():
    heading("Отклики команд", "Решение всегда принимает бизнес. Можно выбрать несколько команд.")
    tasks = list_tasks(status="published")
    if not tasks:
        st.info("Сначала опубликуйте задачу.")
        return
    by_id = {task["id"]: task for task in tasks}
    if st.session_state.get("responses_task") not in by_id:
        st.session_state.responses_task = tasks[0]["id"]
    task_id = st.selectbox("Задача", list(by_id), key="responses_task",
                           format_func=lambda value: by_id[value]["card"].get("title") or value)
    st.caption("Демо без регистрации: можно просмотреть отклики любой опубликованной задачи.")
    proposals = list_proposals(task_id)
    if not proposals:
        st.info("Предложений пока нет. Команды смогут откликнуться через каталог.")
    for proposal in proposals:
        with st.container(border=True, key=f"panel_response_{proposal["id"]}"):
            team, status = st.columns([3, 1])
            team.subheader(proposal["team_name"])
            status_style = {"new": "working", "selected": "priority", "rejected": "draft"}.get(proposal["status"], "draft")
            status.markdown(
                f'<span class="badge {status_style}">{escape(PROPOSAL_LABELS.get(proposal["status"], proposal["status"]))}</span>',
                unsafe_allow_html=True,
            )
            profile = st.session_state.proposal_profiles.get(proposal["id"], {})
            if profile:
                skills, technologies = st.columns(2)
                with skills:
                    profile_tags("Навыки", profile.get("skills", [])[:5])
                    if len(profile.get("skills", [])) > 5:
                        st.caption(f"Ещё {len(profile['skills']) - 5} — в профиле")
                with technologies:
                    profile_tags("Технологии", profile.get("technologies", [])[:5])
                    if len(profile.get("technologies", [])) > 5:
                        st.caption(f"Ещё {len(profile['technologies']) - 5} — в профиле")
            else:
                st.caption("Подробный профиль недоступен в текущем визите.")
            st.button("Открыть профиль", key=f"response_profile_{proposal['id']}",
                      on_click=open_team_profile, args=(proposal["id"],))
            idea, plan, timing, actions = st.columns([2, 2, 1.3, 1], gap="medium")
            for column, field, label in ((idea, "idea", "ИДЕЯ РЕШЕНИЯ"), (plan, "plan", "ПЛАН"), (timing, "timeline", "СРОК")):
                column.caption(label)
                column.write(proposal[field])
            if proposal["link"]:
                timing.caption("ПРОТОТИП")
                timing.write(proposal["link"])
            if actions.button("Выбрать", key=f"select_{proposal['id']}", disabled=proposal["status"] == "selected", type="primary", use_container_width=True):
                set_proposal_status(proposal["id"], "selected")
                st.rerun()
            if actions.button("Отклонить", key=f"reject_{proposal['id']}", disabled=proposal["status"] == "rejected", use_container_width=True):
                set_proposal_status(proposal["id"], "rejected")
                st.rerun()


def my_tasks():
    heading("Мои задачи", "Задачи, созданные вами за текущий визит.")
    st.button("+ Создать задачу", key="my_create", type="primary", on_click=start_task)
    tasks = [task for task in list_tasks(status="published") if task["id"] in st.session_state.owned_task_ids]
    proposals = [proposal for proposal in list_proposals() if proposal["task_id"] in st.session_state.owned_task_ids]
    columns = st.columns(3)
    for column, label, value in zip(columns, ("Опубликовано", "Получено откликов", "Команд выбрано"),
                                    (len(tasks), len(proposals), sum(p["status"] == "selected" for p in proposals))):
        with column, st.container(border=True, key=f"panel_stat_{label}"):
            st.metric(label, value)
    if st.session_state.get("analysis") and st.session_state.get("task", {}).get("status") != "published":
        with st.container(border=True, key="panel_draft"):
            st.subheader("Незавершённая задача")
            st.write(st.session_state.get("raw_task", ""))
            st.button("Продолжить заполнение →", key="resume", on_click=navigate, args=("Создать задачу",))
    if not tasks:
        st.info("Здесь появятся ваши опубликованные задачи. Начните с короткого описания.")
    for task in tasks:
        with st.container(border=True, key=f"panel_owned_{task["id"]}"):
            badge(task["level"], task["score"])
            st.subheader(task["card"].get("title") or "Без названия")
            st.write(task["card"].get("need", ""))
            st.button("Открыть отклики →", key=f"my_responses_{task['id']}", on_click=navigate, args=("Отклики", task["id"]))


def my_proposals():
    heading("Мои отклики", "Предложения, отправленные вашей командой за текущий визит.")
    proposals = [p for p in list_proposals() if p["id"] in st.session_state.sent_by_task.values()]
    if not proposals:
        st.info("Вы ещё не отправляли предложений. Выберите задачу в каталоге.")
        st.button("Найти задачи →", key="find_tasks", type="primary", on_click=navigate, args=("Каталог",))
    for proposal in proposals:
        task = get_task(proposal["task_id"])
        with st.container(border=True, key=f"panel_sent_{proposal["id"]}"):
            st.subheader(task["card"].get("title") if task else "Задача недоступна")
            st.write(f"**{PROPOSAL_LABELS.get(proposal['status'], proposal['status'])}** · {proposal['team_name']}")
            st.write(proposal["idea"])
            if task:
                st.button("Открыть задачу →", key=f"proposal_open_{proposal['id']}", on_click=navigate, args=("Карточка", task["id"]))


def load_demo():
    seed = ROOT / "data" / "seed"
    teams = {team["id"]: team for team in json.loads((seed / "teams.json").read_text(encoding="utf-8"))}
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
        if team := teams.get(proposal.get("team_id")):
            st.session_state.proposal_profiles.setdefault(proposal["id"], {**team, "team_name": team["name"]})
    st.session_state.demo_loaded = True


def main():
    st.markdown('<style>' + (ROOT / "ui.css").read_text(encoding="utf-8") + '</style>', unsafe_allow_html=True)
    init_db()
    st.session_state.setdefault("owned_task_ids", set())
    st.session_state.setdefault("sent_by_task", {})
    st.session_state.setdefault("proposal_drafts", {})
    st.session_state.setdefault("team_profile", {})
    st.session_state.setdefault("business_profile", {})
    st.session_state.setdefault("proposal_profiles", {})
    role = st.session_state.get("active_role")
    if not role:
        welcome()
        return
    screens = ["Мои задачи", "Создать задачу", "Каталог", "Отклики"] if role == "business" else ["Каталог", "Мои отклики"]
    screen = st.session_state.get("ui_screen", screens[0])
    if screen not in screens + ["Карточка", "Профиль команды", "Профиль бизнеса"]:
        screen = screens[0]
        st.session_state.ui_screen = screen
    with st.container(key="topnav"):
        logo, navigation, profile = st.columns([1, 4, 1.1], vertical_alignment="center")
        with logo:
            brand()
        with navigation:
            columns = st.columns(len(screens))
            for column, name in zip(columns, screens):
                column.button(name, key=f"nav_{name}", type="primary" if screen == name else "secondary",
                              use_container_width=True, on_click=start_task if name == "Создать задачу" else navigate,
                              args=() if name == "Создать задачу" else (name,))
        with profile, st.popover("Бизнес" if role == "business" else "Команда", use_container_width=True):
            st.caption("Режим без регистрации")
            st.button("Профиль", key="menu_profile", on_click=open_own_profile, use_container_width=True)
            st.button("Настройки", key="menu_profile_settings", on_click=open_own_profile,
                      args=(True,), use_container_width=True)
            if st.button("Сменить роль", key="switch_role", use_container_width=True):
                st.session_state.active_role = None
                st.rerun()
            st.button("Загрузить демо-примеры", key="load_demo", on_click=load_demo)
            if st.session_state.get("demo_loaded"):
                st.caption("Демо-примеры загружены в каталог.")
    {"Мои задачи": my_tasks, "Создать задачу": constructor, "Каталог": catalog,
     "Карточка": details, "Отклики": responses, "Мои отклики": my_proposals,
     "Профиль команды": team_profile, "Профиль бизнеса": business_profile}[screen]()


if __name__ == "__main__":
    try:
        main()
    except (sqlite3.Error, OSError):
        st.error("Не удалось прочитать или сохранить данные. Проверьте доступ к папке data и повторите действие.")
