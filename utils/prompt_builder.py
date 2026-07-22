"""
Generic, reusable prompt-string builders.

Kept separate from forms/prompt_generator.py so the *wording* of prompts
lives in one place, while forms/prompt_generator.py owns the *orchestration*
(calling Gemini, retrying, parsing).
"""


def build_question_generation_prompt(topic: str, num_questions: int = 5) -> str:
    """Prompt asking Gemini to produce a feedback form as strict JSON."""
    return f"""You are an expert survey designer. Create a feedback form about the
following topic:

TOPIC: "{topic}"

Generate exactly {num_questions} questions that would help collect useful,
actionable feedback about this topic. Mix question types so the form isn't
repetitive.

Return ONLY valid JSON (no markdown fences, no commentary) matching this
exact schema:

{{
  "title": "string - short form title",
  "description": "string - one sentence description of the form",
  "questions": [
    {{
      "id": "q1",
      "label": "string - the question text",
      "type": "text | textarea | rating | multiple_choice | yes_no",
      "options": ["only present when type is multiple_choice"],
      "required": true
    }}
  ]
}}

Rules:
- "type" must be one of: text, textarea, rating, multiple_choice, yes_no
- "rating" questions are on a 1-5 scale, do not include "options" for them
- Include at least one "rating" question and at least one open-ended
  "textarea" question so sentiment analysis has something to work with
- Keep labels concise and clear
- Output raw JSON only
"""


def build_sentiment_prompt(feedback_text: str) -> str:
    """Prompt asking Gemini to classify sentiment + extract keywords for one text."""
    return f"""You are a careful sentiment analyst scoring customer feedback for a
business dashboard. Read the feedback closely, including tone, sarcasm, and
any mix of praise and criticism, before deciding.

FEEDBACK: "{feedback_text}"

Scoring rubric ("score" is a float from -1.0 to 1.0):
  0.6 to 1.0    clearly positive: enthusiastic or strongly satisfied
  0.2 to 0.6    mildly positive: satisfied, minor or no complaints
 -0.2 to 0.2    neutral: purely factual/no emotional language, OR praise
                and criticism that roughly cancel out
 -0.6 to -0.2   mildly negative: dissatisfied, some redeeming points
 -1.0 to -0.6   clearly negative: frustrated, angry, or strongly dissatisfied

Rules:
- "sentiment" must match the score: "positive" if score > 0.2, "negative"
  if score < -0.2, "neutral" otherwise. Never let them contradict.
- If the feedback mixes praise and criticism, weigh which one dominates
  the overall message rather than defaulting to neutral.
- Score sarcasm and backhanded compliments by their real meaning, not
  the literal words (e.g. "great, it crashed again" is negative).
- Purely factual statements with no emotional language (e.g. "I used it
  on Tuesday") are neutral, not positive.
- Don't let one stray positive or negative word override the message
  as a whole.

Calibration examples (for reference only, do not include in output):
  "This saved me so much time, the team is amazing!" -> positive, 0.9
  "Support was slow but the product itself works well." -> positive, 0.3
  "It's fine, does what it says." -> neutral, 0.1
  "Nothing special, but nothing broke either." -> neutral, 0.0
  "Oh great, ANOTHER crash right before my deadline." -> negative, -0.8
  "Constant bugs and no one replied to my ticket." -> negative, -0.85

Return ONLY valid JSON (no markdown fences, no commentary) matching this
exact schema:

{{
  "sentiment": "positive | neutral | negative",
  "score": 0.0,
  "summary": "one short sentence summarizing why",
  "keywords": ["short keyword or phrase", "..."]
}}

"keywords" should be 2-5 short, lowercase keywords or phrases capturing the
main topics/themes mentioned (e.g. "loading speed", "customer support").
If the feedback is empty or has no clear theme, return an empty list.
Output raw JSON only.
"""


def build_batch_sentiment_prompt(feedback_items: list[str]) -> str:
    """Prompt for classifying sentiment + extracting keywords for many texts at once."""
    numbered = "\n".join(f"{i+1}. {text}" for i, text in enumerate(feedback_items))
    return f"""You are a careful sentiment analyst scoring customer feedback for a
business dashboard. Analyze the sentiment of each numbered feedback item
below and extract its main themes as keywords. Score each item
independently — do not let earlier items bias later ones.

FEEDBACK ITEMS:
{numbered}

Scoring rubric ("score" is a float from -1.0 to 1.0):
  0.6 to 1.0    clearly positive: enthusiastic or strongly satisfied
  0.2 to 0.6    mildly positive: satisfied, minor or no complaints
 -0.2 to 0.2    neutral: purely factual/no emotional language, OR praise
                and criticism that roughly cancel out
 -0.6 to -0.2   mildly negative: dissatisfied, some redeeming points
 -1.0 to -0.6   clearly negative: frustrated, angry, or strongly dissatisfied

Rules:
- "sentiment" must match the score: "positive" if score > 0.2, "negative"
  if score < -0.2, "neutral" otherwise. Never let them contradict.
- If an item mixes praise and criticism, weigh which one dominates rather
  than defaulting to neutral.
- Score sarcasm and backhanded compliments by their real meaning, not the
  literal words (e.g. "great, it crashed again" is negative).
- Purely factual statements with no emotional language are neutral, not
  positive.
- Don't let one stray positive or negative word override an item's
  message as a whole.

Return ONLY valid JSON (no markdown fences, no commentary): a JSON array
of exactly {len(feedback_items)} elements, one per feedback item above, in
the same order as the input, each matching this schema:

[
  {{
    "sentiment": "positive | neutral | negative",
    "score": 0.0,
    "summary": "one short sentence",
    "keywords": ["short keyword or phrase", "..."]
  }}
]

"keywords" should be 2-5 short, lowercase keywords or phrases capturing the
main topics/themes mentioned in that specific item. If an item is empty or
has no clear theme, use an empty list for it.
Output raw JSON only.
"""
