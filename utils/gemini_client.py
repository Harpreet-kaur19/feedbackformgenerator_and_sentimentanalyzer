"""
Thin wrapper around google-generativeai so the rest of the app never talks
to the SDK directly. Centralizes API-key setup, JSON-cleanup, and error
handling.
"""
import json
import re

from config import Config

_configured = False
genai = None  # imported lazily so the rest of the app works without the SDK installed


def _ensure_configured():
    global _configured, genai
    if not _configured:
        if genai is None:
            import google.generativeai as _genai
            genai = _genai
        if not Config.GEMINI_API_KEY:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Add it to your .env file."
            )
        # transport="rest" avoids the gRPC C-core client entirely, which is
        # the source of intermittent SIGSEGV crashes (gunicorn "code 139")
        # seen under some Linux container environments, including Render.
        genai.configure(api_key=Config.GEMINI_API_KEY, transport="rest")
        _configured = True


def _strip_code_fences(text: str) -> str:
    """Gemini sometimes wraps JSON in ```json ... ``` fences. Strip them."""
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text.strip(), flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text.strip()).strip()
    return text


def generate_text(prompt: str, temperature: float = 0.7) -> str:
    """Call Gemini and return the raw text response."""
    _ensure_configured()
    model = genai.GenerativeModel(Config.GEMINI_MODEL)
    response = model.generate_content(
        prompt,
        generation_config=genai.types.GenerationConfig(temperature=temperature),
    )
    return response.text


def generate_json(prompt: str, temperature: float = 0.4):
    """Call Gemini and parse the response as JSON, raising on failure.

    Retries once with a stricter follow-up if the first response isn't
    valid JSON (extra prose, trailing commas, etc. are the most common
    cause), before giving up.
    """
    raw = generate_text(prompt, temperature=temperature)
    cleaned = _strip_code_fences(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    repair_prompt = (
        prompt
        + "\n\nYour previous response was not valid JSON. Return ONLY the "
          "raw JSON described above - no markdown fences, no commentary, "
          "no trailing commas."
    )
    raw_retry = generate_text(repair_prompt, temperature=0.0)
    cleaned_retry = _strip_code_fences(raw_retry)
    try:
        return json.loads(cleaned_retry)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Gemini did not return valid JSON after retry.\nRaw response:\n{raw_retry}"
        ) from exc