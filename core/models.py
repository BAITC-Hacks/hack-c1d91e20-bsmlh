"""Shared, dependency-free data contracts for the AI SANA MVP.

UI code may pass plain dictionaries. These constants and constructors keep the
field names stable across AI, rating, storage, and Streamlit modules.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TypedDict
from uuid import uuid4


CARD_FIELDS = (
    "title",
    "context",
    "need",
    "users",
    "data",
    "constraints",
    "expected_result",
    "success_criteria",
    "contact",
    "interaction_format",
)

# These seven keys are the rating contract. Values name the card field(s) that
# make up each scored dimension. `core/rating.py` can import this constant.
RATING_FIELD_MAP: dict[str, tuple[str, ...]] = {
    "context_need": ("context", "need"),
    "data": ("data",),
    "expected_result": ("expected_result",),
    "success_criteria": ("success_criteria",),
    "constraints": ("constraints",),
    "users": ("users",),
    "business_contact": ("contact", "interaction_format"),
}

RATING_WEIGHTS: dict[str, int] = {
    "context_need": 20,
    "data": 20,
    "expected_result": 15,
    "success_criteria": 15,
    "constraints": 10,
    "users": 10,
    "business_contact": 10,
}


class Card(TypedDict, total=False):
    title: str
    context: str
    need: str
    users: str
    data: str
    constraints: str
    expected_result: str
    success_criteria: str
    contact: str
    interaction_format: str
    sources: dict[str, str]


class Task(TypedDict, total=False):
    id: str
    status: str  # draft | confirmed | published
    topic: str
    raw_text: str
    card: Card
    field_status: dict[str, str]  # empty | ai_draft | confirmed
    score: int
    level: str
    score_history: list[dict[str, Any]]
    created_at: str
    published_at: str | None


class Proposal(TypedDict, total=False):
    id: str
    task_id: str
    team_name: str
    idea: str
    plan: str
    timeline: str
    link: str
    status: str  # new | selected | rejected
    created_at: str


def empty_card() -> Card:
    """Return a card with every user-facing field initialized to an empty string."""
    card: Card = {field: "" for field in CARD_FIELDS}
    card["sources"] = {}
    return card


def normalize_card(value: dict[str, Any] | None) -> Card:
    """Drop unknown keys and coerce known values to strings."""
    source = value or {}
    card = empty_card()
    for field in CARD_FIELDS:
        item = source.get(field, "")
        card[field] = item.strip() if isinstance(item, str) else str(item or "")
    sources = source.get("sources", {})
    if isinstance(sources, dict):
        card["sources"] = {
            str(key): str(item)
            for key, item in sources.items()
            if key in CARD_FIELDS and isinstance(item, (str, int, float))
        }
    return card


def new_task(
    raw_text: str,
    *,
    topic: str = "",
    card: dict[str, Any] | None = None,
) -> Task:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    normalized = normalize_card(card)
    return {
        "id": str(uuid4()),
        "status": "draft",
        "topic": topic.strip(),
        "raw_text": raw_text.strip(),
        "card": normalized,
        "field_status": {field: "empty" for field in CARD_FIELDS},
        "score": 0,
        "level": "черновик",
        "score_history": [],
        "created_at": now,
        "published_at": None,
    }


def new_proposal(
    task_id: str,
    team_name: str,
    *,
    idea: str = "",
    plan: str = "",
    timeline: str = "",
    link: str = "",
) -> Proposal:
    return {
        "id": str(uuid4()),
        "task_id": task_id,
        "team_name": team_name.strip(),
        "idea": idea.strip(),
        "plan": plan.strip(),
        "timeline": timeline.strip(),
        "link": link.strip(),
        "status": "new",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
