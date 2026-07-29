import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class Config:
    """Central configuration for the app."""

    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-me")

    # Single shared password protecting the admin area (new form, my forms,
    # dashboard, analysis, delete, refresh-sentiment). Leave unset locally
    # to skip the login gate entirely; always set it in production.
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

    # Gemini API
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

    # Storage paths
    DATA_DIR = os.path.join(BASE_DIR, "data")

    # Everything (forms, responses, sentiment cache, the "active form"
    # pointer) lives in one SQLite file instead of separate JSON/CSV
    # files. DATABASE_PATH can be overridden via an env var so it can be
    # pointed at a Render Persistent Disk mount (e.g. /var/data/app.db)
    # -- without that, this file lives on the service's local disk,
    # which Render wipes on every restart/redeploy.
    DB_PATH = os.getenv("DATABASE_PATH", os.path.join(DATA_DIR, "app.db"))

    # Cookie used to recognize a returning respondent on the public form
    # pages (no login exists for them), so we can block a second
    # submission of the same form from the same browser.
    RESPONDENT_COOKIE_NAME = "fb_respondent"
    RESPONDENT_COOKIE_MAX_AGE = 60 * 60 * 24 * 365 * 2  # ~2 years

    # Form generation defaults
    DEFAULT_NUM_QUESTIONS = 5

    @staticmethod
    def ensure_dirs():
        os.makedirs(os.path.dirname(Config.DB_PATH) or ".", exist_ok=True)
