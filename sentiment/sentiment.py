"""
Runs Gemini sentiment + keyword analysis over the open-ended (text/textarea)
answers in a single form's feedback CSV. Results are cached per form in
sentiment_cache/<form_id>.csv, keyed by response_id, so reloading the
dashboard doesn't re-call the API for responses we've already scored.
"""
import json
import os

import pandas as pd

from config import Config
from utils.gemini_client import generate_json
from utils.prompt_builder import build_batch_sentiment_prompt, build_sentiment_prompt
from feedback.save_response import load_responses
from forms.form_generator import load_form

TEXT_QUESTION_TYPES = {"text", "textarea"}
CACHE_COLUMNS = ["response_id", "sentiment", "score", "summary", "keywords"]
_VALID_SENTIMENTS = {"positive", "neutral", "negative"}


def _cache_path(form_id: str) -> str:
    return os.path.join(Config.SENTIMENT_CACHE_DIR, f"{form_id}.csv")


def _normalize_result(result: dict) -> dict:
    """
    Make a Gemini sentiment result safe and internally consistent:
    - clamps "score" into [-1.0, 1.0] and coerces it to a float
    - falls back to deriving "sentiment" from the score if the label is
      missing/invalid, or if it flatly contradicts a clearly-signed score
      (e.g. score=-0.7 but sentiment="positive")
    - drops non-string/empty keywords and caps the list at 5
    """
    if not isinstance(result, dict):
        result = {}

    try:
        score = float(result.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    score = max(-1.0, min(1.0, score))

    derived = "positive" if score > 0.2 else "negative" if score < -0.2 else "neutral"
    sentiment = str(result.get("sentiment", "")).strip().lower()
    if sentiment not in _VALID_SENTIMENTS:
        sentiment = derived
    elif derived != "neutral" and sentiment != derived and abs(score) > 0.35:
        # label and score clearly disagree - trust the score
        sentiment = derived

    keywords = result.get("keywords", [])
    if not isinstance(keywords, list):
        keywords = []
    keywords = [str(k).strip().lower() for k in keywords if str(k).strip()][:5]

    summary = str(result.get("summary", "")).strip()

    return {"sentiment": sentiment, "score": round(score, 3), "summary": summary, "keywords": keywords}


def analyze_text(feedback_text: str) -> dict:
    """Analyze a single piece of text. Returns {sentiment, score, summary, keywords}."""
    if not feedback_text or not feedback_text.strip():
        return {"sentiment": "neutral", "score": 0.0, "summary": "No text provided.", "keywords": []}
    prompt = build_sentiment_prompt(feedback_text)
    try:
        result = generate_json(prompt, temperature=0.2)
    except ValueError:
        return {
            "sentiment": "neutral",
            "score": 0.0,
            "summary": "Could not be analyzed automatically.",
            "keywords": [],
        }
    return _normalize_result(result)


def _analyze_batch(texts: list[str]) -> list[dict]:
    """Analyze many texts (sentiment + keywords) in one Gemini call.
    Falls back to one-by-one analysis if the batch call fails or mismatches."""
    if not texts:
        return []
    prompt = build_batch_sentiment_prompt(texts)
    try:
        results = generate_json(prompt, temperature=0.2)
        if isinstance(results, list) and len(results) == len(texts):
            return [_normalize_result(r) for r in results]
    except ValueError:
        pass
    return [analyze_text(t) for t in texts]


def _load_cache(form_id: str) -> pd.DataFrame:
    path = _cache_path(form_id)
    if not os.path.exists(path):
        return pd.DataFrame(columns=CACHE_COLUMNS)
    return pd.read_csv(path)


def _save_cache(form_id: str, df: pd.DataFrame) -> None:
    Config.ensure_dirs()
    df.to_csv(_cache_path(form_id), index=False)


def _open_ended_column_ids(form: dict) -> list[str]:
    if not form:
        return []
    return [q["id"] for q in form["questions"] if q["type"] in TEXT_QUESTION_TYPES]


def analyze_form_feedback(form_id: str, force_refresh: bool = False) -> pd.DataFrame:
    """
    Returns one form's feedback DataFrame merged with sentiment + keyword
    columns (sentiment, score, summary, keywords) for each response.
    `keywords` is stored/returned as a JSON-encoded string per row; callers
    that need the list should json.loads() it (see charts.top_keywords
    and app.analysis for examples).
    """
    responses = load_responses(form_id)
    if responses.empty:
        return responses

    form = load_form(form_id)
    text_cols = _open_ended_column_ids(form)
    text_cols = [c for c in text_cols if c in responses.columns]

    cache = _load_cache(form_id) if not force_refresh else pd.DataFrame(columns=CACHE_COLUMNS)
    already_scored = set(cache["response_id"]) if not cache.empty else set()

    to_score = responses[~responses["response_id"].isin(already_scored)]

    if not to_score.empty and text_cols:
        new_rows = []
        for _, row in to_score.iterrows():
            combined_text = " ".join(
                str(row[c]) for c in text_cols if pd.notna(row.get(c)) and str(row[c]).strip()
            )
            new_rows.append({"response_id": row["response_id"], "text": combined_text})

        results = _analyze_batch([r["text"] for r in new_rows])
        new_cache_rows = []
        for meta, result in zip(new_rows, results):
            new_cache_rows.append(
                {
                    "response_id": meta["response_id"],
                    "sentiment": result.get("sentiment", "neutral"),
                    "score": result.get("score", 0.0),
                    "summary": result.get("summary", ""),
                    "keywords": json.dumps(result.get("keywords", [])),
                }
            )
        cache = pd.concat([cache, pd.DataFrame(new_cache_rows)], ignore_index=True)
        _save_cache(form_id, cache)

    return responses.merge(cache, on="response_id", how="left")


def cached_sentiment_summary(form_id: str) -> dict:
    """
    Lightweight per-form sentiment snapshot for list views: reads only
    whatever is already in sentiment_cache/<form_id>.csv and never calls
    Gemini. Safe to call once per form when rendering "My Forms" without
    triggering new API calls or slowing the page down.
    Returns {"positive": n, "neutral": n, "negative": n, "scored": n}.
    """
    cache = _load_cache(form_id)
    if cache.empty:
        return {"positive": 0, "neutral": 0, "negative": 0, "scored": 0}
    counts = cache["sentiment"].fillna("neutral").value_counts()
    return {
        "positive": int(counts.get("positive", 0)),
        "neutral": int(counts.get("neutral", 0)),
        "negative": int(counts.get("negative", 0)),
        "scored": int(len(cache)),
    }
