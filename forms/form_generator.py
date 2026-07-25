"""
Validates and normalizes the raw JSON coming back from Gemini, then
permanently archives it to the SQLite database (table `forms`) so a
shareable link keeps working even after newer forms are generated, and
survives app restarts/redeploys. Also tracks which form is "active"
(the one used as a default when no form_id is given), purely as a
convenience.
"""
import json
import uuid
from datetime import datetime, timezone

from db import db_cursor
from .prompt_generator import generate_questions_json

VALID_TYPES = {"text", "textarea", "rating", "multiple_choice", "yes_no"}


class FormValidationError(Exception):
    pass


def _normalize_question(raw_q: dict, index: int) -> dict:
    q_type = raw_q.get("type", "text")
    if q_type not in VALID_TYPES:
        q_type = "text"

    question = {
        "id": raw_q.get("id") or f"q{index + 1}",
        "label": raw_q.get("label", f"Question {index + 1}"),
        "type": q_type,
        "required": bool(raw_q.get("required", True)),
    }

    if q_type == "multiple_choice":
        options = raw_q.get("options") or []
        # Fall back to a sane default so the form never renders empty
        question["options"] = options if options else ["Option 1", "Option 2"]

    return question


def _normalize_form(raw: dict, topic: str, custom_questions: list[dict] | None = None) -> dict:
    if "questions" not in raw or not isinstance(raw["questions"], list):
        raise FormValidationError("Gemini response missing a 'questions' list")

    raw_questions = list(raw["questions"]) + list(custom_questions or [])
    questions = [
        _normalize_question(q, i) for i, q in enumerate(raw_questions)
    ]
    if not questions:
        raise FormValidationError("Gemini returned zero questions")

    return {
        "form_id": str(uuid.uuid4())[:8],
        "topic": topic,
        "title": raw.get("title") or f"Feedback: {topic}",
        "description": raw.get("description", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "questions": questions,
    }


def generate_form(topic: str, num_questions: int = None, custom_questions: list[dict] | None = None) -> dict:
    """
    Generate, validate, permanently archive, and activate a new form.
    `custom_questions`, if given, are the respondent's own hand-written
    questions (each a dict with label/type/options/required) -- they're
    appended after whatever Gemini generates from the topic.
    """
    raw = generate_questions_json(topic, num_questions)
    form = _normalize_form(raw, topic, custom_questions=custom_questions)
    save_form(form)
    set_active_form(form["form_id"])
    return form


def _row_to_form(row) -> dict:
    return {
        "form_id": row["form_id"],
        "topic": row["topic"],
        "title": row["title"],
        "description": row["description"],
        "created_at": row["created_at"],
        "questions": json.loads(row["questions_json"]),
    }


def save_form(form: dict) -> None:
    """Archive this form permanently in the `forms` table, keyed by form_id."""
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO forms (form_id, topic, title, description, created_at, questions_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(form_id) DO UPDATE SET
                topic=excluded.topic,
                title=excluded.title,
                description=excluded.description,
                created_at=excluded.created_at,
                questions_json=excluded.questions_json
            """,
            (
                form["form_id"],
                form.get("topic", ""),
                form.get("title", ""),
                form.get("description", ""),
                form.get("created_at", ""),
                json.dumps(form["questions"]),
            ),
        )


def load_form(form_id: str = None) -> dict | None:
    """
    Load a specific form by id. If no id is given, fall back to whichever
    form was most recently generated (the "active" one).
    """
    if form_id is None:
        form_id = get_active_form_id()
        if not form_id:
            return None
    with db_cursor() as cur:
        cur.execute("SELECT * FROM forms WHERE form_id = ?", (form_id,))
        row = cur.fetchone()
    return _row_to_form(row) if row else None


def list_forms() -> list[dict]:
    """All archived forms, newest first."""
    with db_cursor() as cur:
        cur.execute("SELECT * FROM forms ORDER BY created_at DESC")
        rows = cur.fetchall()
    return [_row_to_form(r) for r in rows]


def set_active_form(form_id: str) -> None:
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO app_meta (key, value) VALUES ('active_form_id', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (form_id,),
        )


def get_active_form_id() -> str | None:
    with db_cursor() as cur:
        cur.execute("SELECT value FROM app_meta WHERE key = 'active_form_id'")
        row = cur.fetchone()
    return row["value"] if row and row["value"] else None


def delete_form(form_id: str) -> bool:
    """
    Permanently remove a form: its definition, every submitted response,
    and its cached sentiment scores. Returns True if the form existed.
    """
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM forms WHERE form_id = ?", (form_id,))
        if cur.fetchone() is None:
            return False

        cur.execute("DELETE FROM sentiment_cache WHERE form_id = ?", (form_id,))
        cur.execute("DELETE FROM responses WHERE form_id = ?", (form_id,))
        cur.execute("DELETE FROM forms WHERE form_id = ?", (form_id,))

        # If the deleted form was the "active" one, clear the pointer so a
        # stale id doesn't linger around as everyone's default.
        cur.execute("SELECT value FROM app_meta WHERE key = 'active_form_id'")
        row = cur.fetchone()
        if row and row["value"] == form_id:
            cur.execute("DELETE FROM app_meta WHERE key = 'active_form_id'")

    return True
