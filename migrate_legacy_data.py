"""
One-off migration: imports the old JSON/CSV storage (data/forms/*.json,
data/feedback/*.csv, data/sentiment_cache/*.csv) into the new SQLite
database. Safe to run more than once (uses INSERT OR IGNORE / upserts).

Run once, locally, before you deploy the SQLite version:

    python migrate_legacy_data.py

After confirming your forms show up on the "My Forms" page, the old
data/forms, data/feedback, data/sentiment_cache folders and
data/active_form_id.txt are no longer used and can be deleted.
"""
import csv
import json
import os

from config import Config
from db import db_cursor, init_db

LEGACY_FORMS_DIR = os.path.join(Config.DATA_DIR, "forms")
LEGACY_FEEDBACK_DIR = os.path.join(Config.DATA_DIR, "feedback")
LEGACY_SENTIMENT_DIR = os.path.join(Config.DATA_DIR, "sentiment_cache")
LEGACY_ACTIVE_POINTER = os.path.join(Config.DATA_DIR, "active_form_id.txt")

META_COLUMNS = {"response_id", "submitted_at", "form_id", "topic"}


def migrate_forms() -> list[str]:
    if not os.path.isdir(LEGACY_FORMS_DIR):
        return []
    form_ids = []
    with db_cursor() as cur:
        for name in os.listdir(LEGACY_FORMS_DIR):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(LEGACY_FORMS_DIR, name), "r", encoding="utf-8") as f:
                form = json.load(f)
            cur.execute(
                """
                INSERT INTO forms (form_id, topic, title, description, created_at, questions_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(form_id) DO NOTHING
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
            form_ids.append(form["form_id"])
            print(f"  form {form['form_id']} ({form.get('title', '')!r})")
    return form_ids


def migrate_responses() -> None:
    if not os.path.isdir(LEGACY_FEEDBACK_DIR):
        return
    with db_cursor() as cur:
        for name in os.listdir(LEGACY_FEEDBACK_DIR):
            if not name.endswith(".csv"):
                continue
            form_id = name[: -len(".csv")]
            with open(os.path.join(LEGACY_FEEDBACK_DIR, name), newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            for row in rows:
                answers = {k: v for k, v in row.items() if k not in META_COLUMNS}
                cur.execute(
                    """
                    INSERT INTO responses (response_id, form_id, submitted_at, respondent_token, answers_json)
                    VALUES (?, ?, ?, NULL, ?)
                    ON CONFLICT(response_id) DO NOTHING
                    """,
                    (row["response_id"], form_id, row.get("submitted_at", ""), json.dumps(answers)),
                )
            print(f"  {len(rows)} response(s) for form {form_id}")


def migrate_sentiment_cache() -> None:
    if not os.path.isdir(LEGACY_SENTIMENT_DIR):
        return
    with db_cursor() as cur:
        for name in os.listdir(LEGACY_SENTIMENT_DIR):
            if not name.endswith(".csv"):
                continue
            form_id = name[: -len(".csv")]
            with open(os.path.join(LEGACY_SENTIMENT_DIR, name), newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO sentiment_cache (response_id, form_id, sentiment, score, summary, keywords)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(response_id) DO NOTHING
                    """,
                    (
                        row["response_id"],
                        form_id,
                        row.get("sentiment"),
                        row.get("score"),
                        row.get("summary"),
                        row.get("keywords"),
                    ),
                )
            print(f"  {len(rows)} cached sentiment row(s) for form {form_id}")


def migrate_active_pointer() -> None:
    if not os.path.exists(LEGACY_ACTIVE_POINTER):
        return
    with open(LEGACY_ACTIVE_POINTER, "r", encoding="utf-8") as f:
        form_id = f.read().strip()
    if not form_id:
        return
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO app_meta (key, value) VALUES ('active_form_id', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (form_id,),
        )
    print(f"  active form -> {form_id}")


if __name__ == "__main__":
    init_db()
    print(f"Migrating into {Config.DB_PATH} ...")
    print("Forms:")
    migrate_forms()
    print("Responses:")
    migrate_responses()
    print("Sentiment cache:")
    migrate_sentiment_cache()
    print("Active form pointer:")
    migrate_active_pointer()
    print("Done.")
