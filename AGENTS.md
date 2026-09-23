# AGENTS.md

## Project
AI SANA hackathon MVP.

## Stack
- Python 3.12
- Streamlit
- Pydantic
- OpenAI API
- JSON / SQLite

## Structure
- app.py — entry point
- pages/ — Streamlit UI
- core/rating.py — rating logic
- core/ai.py — AI analysis and card generation
- core/storage.py — data storage
- data/seed/ — demo data
- tests/ — tests

## Rules
- Never commit .env or API keys.
- Rating logic must stay in core/rating.py.
- AI must not invent facts not provided by the user.
- AI-generated fields must be editable and confirmed by the business.
- Team selection must always be manual.
- Keep changes small and focused.