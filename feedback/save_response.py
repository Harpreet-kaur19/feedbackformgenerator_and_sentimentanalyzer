"""
SQLite persistence for submitted feedback (table `responses`).

Each row is one submission: response_id, form_id, submitted_at, the
answers (stored as JSON, one blob per response so each form's own
question ids never need a shared schema), and a respondent_token used
to stop the same browser from submitting the same form twice (see
`already_submitted`).
"""
import json
import sqlite3
import uuid
from datetime import datetime, timezone

import pandas as pd

from db import db_cursor

META_COLUMNS = ["response_id", "submitted_at", "form_id", "topic"]


class AlreadySubmittedError(Exception):
    """Raised when this respondent_token has already submitted this form."""


def already_submitted(form_id: str, respondent_token: str | None) -> bool:
    """True if this respondent (identified by their cookie token) already
    has a response on file for this form. Always False if there's no
    token to check (e.g. cookies blocked) -- that case is handled by the
    UNIQUE index + AlreadySubmittedError at save time instead."""
    if not respondent_token:
        return False
    with db_cursor() as cur:
        cur.execute(
            "SELECT 1 FROM responses WHERE form_id = ? AND respondent_token = ?",
            (form_id, respondent_token),
        )
        return cur.fetchone() is not None


def save_response(form: dict, answers: dict, respondent_token: str | None = None) -> str:
    """
    Save one submission for this form.
    `answers` maps question_id -> submitted value (string).
    Returns the generated response_id.
    Raises AlreadySubmittedError if respondent_token already submitted
    this form (belt-and-suspenders alongside the already_submitted() check
    the caller should do before rendering the form).
    """
    form_id = form.get("form_id", "")
    response_id = str(uuid.uuid4())
    submitted_at = datetime.now(timezone.utc).isoformat()

    row_answers = {q["id"]: answers.get(q["id"], "") for q in form["questions"]}

    try:
        with db_cursor() as cur:
            cur.execute(
                """
                INSERT INTO responses (response_id, form_id, submitted_at, respondent_token, answers_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (response_id, form_id, submitted_at, respondent_token, json.dumps(row_answers)),
            )
    except sqlite3.IntegrityError as exc:
        raise AlreadySubmittedError(
            f"{respondent_token} already submitted form {form_id}"
        ) from exc

    return response_id


def load_responses(form_id: str) -> pd.DataFrame:
    """Return one form's stored feedback as a DataFrame (empty if none),
    one column per question id plus the META_COLUMNS metadata columns --
    same shape the rest of the app (sentiment.py, charts.py) expects."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT response_id, form_id, submitted_at, answers_json,
                   (SELECT topic FROM forms WHERE forms.form_id = responses.form_id) AS topic
            FROM responses WHERE form_id = ? ORDER BY submitted_at ASC
            """,
            (form_id,),
        )
        rows = cur.fetchall()

    if not rows:
        return pd.DataFrame(columns=META_COLUMNS)

    records = []
    for r in rows:
        record = {
            "response_id": r["response_id"],
            "submitted_at": r["submitted_at"],
            "form_id": r["form_id"],
            "topic": r["topic"] or "",
        }
        record.update(json.loads(r["answers_json"]))
        records.append(record)

    return pd.DataFrame(records)


def load_all_responses() -> pd.DataFrame:
    """
    Return every form's feedback concatenated together. Only used where a
    deliberate cross-form view is wanted -- the normal dashboard/analysis
    flow uses load_responses(form_id) for a single form. Because
    different forms have different question ids, columns are unioned and
    missing values are left blank (same behavior as before).
    """
    with db_cursor() as cur:
        cur.execute("SELECT DISTINCT form_id FROM responses")
        form_ids = [r["form_id"] for r in cur.fetchall()]

    frames = [load_responses(fid) for fid in form_ids]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame(columns=META_COLUMNS)
    return pd.concat(frames, ignore_index=True, sort=False)


def question_columns(df: pd.DataFrame) -> list[str]:
    """All non-metadata columns, i.e. actual question ids."""
    return [c for c in df.columns if c not in META_COLUMNS]
