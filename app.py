import json

from flask import Flask, redirect, render_template, request, url_for, flash, session

from config import Config
from forms.form_generator import (
    FormValidationError,
    delete_form,
    generate_form,
    list_forms,
    load_form,
)
from feedback.save_response import load_responses, save_response
from sentiment.sentiment import analyze_form_feedback, cached_sentiment_summary
from charts.charts import dashboard_summary

app = Flask(__name__)
app.config.from_object(Config)
Config.ensure_dirs()


# ============================================================================
# Admin login gate -- protects everything except the public form-fill/submit
# routes. Disabled entirely (no login required) if ADMIN_PASSWORD is unset,
# so local dev keeps working without extra setup. Always set ADMIN_PASSWORD
# in production (e.g. on Render) to lock the admin area down.
# ============================================================================

PUBLIC_ENDPOINTS = {"login", "fill_form", "submit", "static"}


@app.before_request
def require_admin_login():
    if not Config.ADMIN_PASSWORD:
        return
    if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint is None:
        return
    if session.get("is_admin"):
        return
    return redirect(url_for("login", next=request.path))


@app.route("/login", methods=["GET", "POST"])
def login():
    if not Config.ADMIN_PASSWORD:
        return redirect(url_for("index"))

    next_url = request.values.get("next") or url_for("index")
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == Config.ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(next_url)
        flash("Incorrect password.", "error")
    return render_template("login.html", next=next_url)


@app.route("/logout", methods=["POST"])
def logout():
    session.pop("is_admin", None)
    return redirect(url_for("login"))


# ============================================================================
# Admin area -- everything a form's creator uses to build forms and review
# results. Every page here shares the admin chrome (top nav + back button).
# ============================================================================

@app.route("/", methods=["GET"])
def index():
    """User enters a topic/prompt to generate a feedback form."""
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    """Call Gemini to turn the user's prompt into a form definition, then
    append any questions the user wrote themselves."""
    topic = request.form.get("topic", "").strip()
    num_questions = request.form.get("num_questions", type=int)
    custom_questions = _parse_custom_questions(request.form)

    if not topic:
        flash("Please describe what you'd like feedback on.", "error")
        return redirect(url_for("index"))

    try:
        form = generate_form(topic, num_questions, custom_questions=custom_questions)
    except FormValidationError as exc:
        flash(f"Couldn't build a valid form: {exc}", "error")
        return redirect(url_for("index"))
    except Exception as exc:  # Gemini/network errors
        flash(f"Form generation failed: {exc}", "error")
        return redirect(url_for("index"))

    share_link = url_for("fill_form", form_id=form["form_id"], _external=True)
    return render_template("generated_form.html", form=form, share_link=share_link)


def _parse_custom_questions(form_data) -> list[dict]:
    """
    Reads the repeated custom_label / custom_type / custom_options fields
    submitted by the "Add your own questions" builder on the index page
    and turns them into raw question dicts ready for generate_form().
    Rows with no label are ignored (an empty row the user never filled in).
    """
    labels = form_data.getlist("custom_label")
    types = form_data.getlist("custom_type")
    options_raw = form_data.getlist("custom_options")

    questions = []
    for i, label in enumerate(labels):
        label = label.strip()
        if not label:
            continue
        q_type = types[i] if i < len(types) else "text"
        question = {"label": label, "type": q_type, "required": True}
        if q_type == "multiple_choice":
            opts = options_raw[i] if i < len(options_raw) else ""
            question["options"] = [o.strip() for o in opts.split(",") if o.strip()]
        questions.append(question)
    return questions


@app.route("/forms", methods=["GET"])
def forms_list():
    """
    Every form ever generated. Each form's responses live in their own
    file, so every row here shows that form's own response count and a
    quick sentiment snapshot -- click through to see every response for
    that form grouped together, or the full chart dashboard.
    """
    forms = list_forms()
    links = {}
    stats = {}
    for f in forms:
        form_id = f["form_id"]
        links[form_id] = url_for("fill_form", form_id=form_id, _external=True)
        stats[form_id] = {
            "response_count": int(len(load_responses(form_id))),
            "sentiment": cached_sentiment_summary(form_id),
        }
    return render_template("forms_list.html", forms=forms, links=links, stats=stats)


@app.route("/delete/<form_id>", methods=["POST"])
def delete(form_id):
    """Permanently remove a form, its responses, and its sentiment cache."""
    deleted = delete_form(form_id)
    if deleted:
        flash("Form deleted.", "success")
    else:
        flash("That form doesn't exist or was already deleted.", "error")
    return redirect(url_for("forms_list"))


@app.route("/dashboard/<form_id>", methods=["GET"])
def dashboard(form_id):
    """Run sentiment + keyword analysis on one form's responses and show charts."""
    form = load_form(form_id)
    if not form:
        flash("That form doesn't exist or was never generated.", "error")
        return redirect(url_for("forms_list"))
    df = analyze_form_feedback(form_id)
    summary = dashboard_summary(df, form_id)
    return render_template("dashboard.html", summary=summary, form=form)


@app.route("/analysis/<form_id>", methods=["GET"])
def analysis(form_id):
    """Detailed, per-response table with sentiment + keyword labels."""
    form = load_form(form_id)
    if not form:
        flash("That form doesn't exist or was never generated.", "error")
        return redirect(url_for("forms_list"))

    df = analyze_form_feedback(form_id)
    records = []
    if not df.empty:
        for r in df.to_dict(orient="records"):
            kw = r.get("keywords")
            if isinstance(kw, str):
                try:
                    r["keywords"] = json.loads(kw)
                except (json.JSONDecodeError, TypeError):
                    r["keywords"] = []
            records.append(r)

    return render_template("analysis.html", records=records, form=form)


@app.route("/api/refresh-sentiment/<form_id>", methods=["POST"])
def refresh_sentiment(form_id):
    """Force re-scoring of one form's feedback (bypasses the sentiment cache)."""
    analyze_form_feedback(form_id, force_refresh=True)
    return redirect(url_for("dashboard", form_id=form_id))


# ============================================================================
# Public area -- the only pages a respondent ever sees. No admin chrome, no
# navigation to forms/dashboards/other people's data -- just the form itself,
# the same way a Google Forms or SurveyMonkey link works.
# ============================================================================

@app.route("/form/<form_id>", methods=["GET"])
def fill_form(form_id):
    """Render one specific generated form for users to fill out."""
    form = load_form(form_id)
    if not form:
        flash("That form doesn't exist or was never generated.", "error")
        return redirect(url_for("index"))
    return render_template("fill_form.html", form=form)


@app.route("/submit/<form_id>", methods=["POST"])
def submit(form_id):
    """Save a user's submitted answers to that form's own CSV."""
    form = load_form(form_id)
    if not form:
        flash("That form doesn't exist or was never generated.", "error")
        return redirect(url_for("index"))

    answers = {}
    for q in form["questions"]:
        answers[q["id"]] = request.form.get(q["id"], "").strip()
        if q["required"] and not answers[q["id"]]:
            flash(f"Please answer: {q['label']}", "error")
            return render_template("fill_form.html", form=form, answers=answers)

    save_response(form, answers)
    flash("Thanks! Your feedback was submitted.", "success")
    return redirect(url_for("fill_form", form_id=form_id))


if __name__ == "__main__":
    app.run(debug=True)
