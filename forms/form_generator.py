"""
Validates and normalizes the raw JSON coming back from Gemini, then
permanently archives it to disk as forms/<form_id>.json so a shareable
link keeps working even after newer forms are generated. Also tracks
which form is "active" (the one used as a default when no form_id is
given), purely as a convenience.
"""
import json
import os
import uuid
from datetime import datetime, timezone

from config import Config
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


def _form_path(form_id: str) -> str:
    return os.path.join(Config.FORMS_DIR, f"{form_id}.json")


def save_form(form: dict) -> None:
    """Archive this form permanently under its own file, keyed by form_id."""
    Config.ensure_dirs()
    with open(_form_path(form["form_id"]), "w", encoding="utf-8") as f:
        json.dump(form, f, indent=2)


def load_form(form_id: str = None) -> dict | None:
    """
    Load a specific form by id. If no id is given, fall back to whichever
    form was most recently generated (the "active" one).
    """
    if form_id is None:
        form_id = get_active_form_id()
        if not form_id:
            return None
    path = _form_path(form_id)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_forms() -> list[dict]:
    """All archived forms, newest first."""
    Config.ensure_dirs()
    forms = []
    for name in os.listdir(Config.FORMS_DIR):
        if name.endswith(".json"):
            with open(os.path.join(Config.FORMS_DIR, name), "r", encoding="utf-8") as f:
                forms.append(json.load(f))
    return sorted(forms, key=lambda f: f.get("created_at", ""), reverse=True)


def set_active_form(form_id: str) -> None:
    Config.ensure_dirs()
    with open(Config.ACTIVE_FORM_POINTER, "w", encoding="utf-8") as f:
        f.write(form_id)


def get_active_form_id() -> str | None:
    if not os.path.exists(Config.ACTIVE_FORM_POINTER):
        return None
    with open(Config.ACTIVE_FORM_POINTER, "r", encoding="utf-8") as f:
        return f.read().strip() or None


def delete_form(form_id: str) -> bool:
    """
    Permanently remove a form: its definition, every submitted response,
    and its cached sentiment scores. Returns True if the form existed.
    """
    path = _form_path(form_id)
    if not os.path.exists(path):
        return False

    os.remove(path)

    feedback_path = os.path.join(Config.FEEDBACK_DIR, f"{form_id}.csv")
    if os.path.exists(feedback_path):
        os.remove(feedback_path)

    cache_path = os.path.join(Config.SENTIMENT_CACHE_DIR, f"{form_id}.csv")
    if os.path.exists(cache_path):
        os.remove(cache_path)

    # If the deleted form was the "active" one, clear the pointer so a
    # stale id doesn't linger around as everyone's default.
    if get_active_form_id() == form_id:
        os.remove(Config.ACTIVE_FORM_POINTER)

    return True
