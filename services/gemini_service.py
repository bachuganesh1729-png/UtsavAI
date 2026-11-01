"""
services/gemini_service.py
───────────────────────────
Google Gemini API integration for UtsavAI.

Uses the official modern SDK: from google import genai

Responsibilities:
- Initialise the Gemini client from AppConfig.
- Expose typed AI call functions that return structured results.
- Validate all AI-generated JSON before returning it to callers.
- Handle and categorise every failure mode without crashing.

Error model:
    Every public function returns an AIResult dataclass with:
        success: bool
        data:    dict | None  — present only when success=True
        error:   AIError | None — present only when success=False

    AIError.kind is one of:
        "missing_credentials"  — API key absent/invalid
        "rate_limit"           — 429 from the API
        "timeout"              — network/request timeout
        "invalid_response"     — non-JSON or schema-invalid response
        "api_error"            — other API-side error
        "unexpected"           — catch-all for truly unexpected exceptions

Layer contract: services/ may import from utils/ and the standard library.
                services/ must NOT import from modules/ or streamlit.

⚠️  Financial note: AI-generated budget figures are SUGGESTIONS only.
    All arithmetic is re-computed in Python by budget_service.py.
    This service never claims AI totals are accurate.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Optional

from utils.config import AppConfig
from utils.validators import validate_ai_event_plan, validate_ai_budget_suggestions

logger = logging.getLogger(__name__)


# ── Error model ───────────────────────────────────────────────────────────────

class AIErrorKind(str, Enum):
    MISSING_CREDENTIALS = "missing_credentials"
    RATE_LIMIT          = "rate_limit"
    TIMEOUT             = "timeout"
    INVALID_RESPONSE    = "invalid_response"
    API_ERROR           = "api_error"
    UNEXPECTED          = "unexpected"


@dataclass(frozen=True)
class AIError:
    kind:    AIErrorKind
    message: str          # Safe for display in the UI
    detail:  str = ""     # Internal — logged, never shown to users


@dataclass
class AIResult:
    success: bool
    data:    Optional[dict[str, Any]] = None
    error:   Optional[AIError]        = None

    @classmethod
    def ok(cls, data: dict[str, Any]) -> "AIResult":
        return cls(success=True, data=data)

    @classmethod
    def fail(cls, error: AIError) -> "AIResult":
        return cls(success=False, error=error)


# ── Client initialisation ─────────────────────────────────────────────────────

def _build_client(config: AppConfig):
    """
    Build and return a google.genai.Client.

    Returns None if the API key is absent (avoids import error when key missing).
    """
    if not config.ai_available:
        return None
    try:
        from google import genai  # type: ignore[import]
        return genai.Client(api_key=config.gemini_api_key)
    except Exception as exc:
        logger.error("Failed to build Gemini client: %s", exc)
        return None


# ── JSON extraction ───────────────────────────────────────────────────────────

def _extract_json(text: str) -> Optional[dict[str, Any]]:
    """
    Parse JSON from an AI response string.

    The model sometimes wraps JSON in markdown fences (```json ... ```).
    This function strips fences before parsing.

    Returns the parsed dict or None on failure.
    """
    stripped = text.strip()
    # Strip markdown code fences if present
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        # Remove opening fence line (```json or ```)
        lines = lines[1:]
        # Remove closing fence line
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    try:
        parsed = json.loads(stripped)
        if not isinstance(parsed, dict):
            return None
        return parsed
    except json.JSONDecodeError:
        return None


# ── Error classification ──────────────────────────────────────────────────────

def _classify_api_error(exc: Exception) -> AIError:
    """
    Map a google-genai SDK exception to a structured AIError.
    """
    exc_str = str(exc).lower()

    if "api_key" in exc_str or "invalid_argument" in exc_str or "unauthenticated" in exc_str:
        return AIError(
            kind=AIErrorKind.MISSING_CREDENTIALS,
            message="The Gemini API key is invalid or not authorised. Please check your configuration.",
            detail=str(exc),
        )
    if "quota" in exc_str or "429" in exc_str or "resource_exhausted" in exc_str:
        return AIError(
            kind=AIErrorKind.RATE_LIMIT,
            message="Gemini API rate limit reached. Please wait a moment and try again.",
            detail=str(exc),
        )
    if "timeout" in exc_str or "deadline" in exc_str or "timed out" in exc_str:
        return AIError(
            kind=AIErrorKind.TIMEOUT,
            message="The request to Gemini timed out. Please check your connection and try again.",
            detail=str(exc),
        )
    return AIError(
        kind=AIErrorKind.API_ERROR,
        message="Gemini API returned an error. Please try again.",
        detail=str(exc),
    )


# ── Core generate helper ──────────────────────────────────────────────────────

def _generate_json(
    client,
    model: str,
    prompt: str,
    validator,
) -> AIResult:
    """
    Call the Gemini API and return a validated AIResult.

    Args:
        client:    Initialised google.genai.Client.
        model:     Model identifier string.
        prompt:    The full text prompt.
        validator: A function (data: Any) -> (bool, str) from validators.py.

    The model is instructed to return JSON only. The response is parsed and
    schema-validated before being returned.
    """
    try:
        from google.genai import types  # type: ignore[import]

        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.4,   # Low temperature for structured, consistent output
            ),
        )

        raw_text = response.text if hasattr(response, "text") else ""
        if not raw_text:
            return AIResult.fail(
                AIError(
                    kind=AIErrorKind.INVALID_RESPONSE,
                    message="Gemini returned an empty response. Please try again.",
                    detail="response.text was empty or missing",
                )
            )

        parsed = _extract_json(raw_text)
        if parsed is None:
            logger.warning("Gemini response was not valid JSON. Raw length: %d", len(raw_text))
            return AIResult.fail(
                AIError(
                    kind=AIErrorKind.INVALID_RESPONSE,
                    message="Gemini returned a response that could not be parsed as JSON.",
                    detail=f"Raw text (first 200 chars): {raw_text[:200]}",
                )
            )

        valid, err_msg = validator(parsed)
        if not valid:
            logger.warning("AI response failed schema validation: %s", err_msg)
            return AIResult.fail(
                AIError(
                    kind=AIErrorKind.INVALID_RESPONSE,
                    message=f"AI response did not match the expected format: {err_msg}",
                    detail=err_msg,
                )
            )

        return AIResult.ok(data=parsed)

    except Exception as exc:
        error = _classify_api_error(exc)
        logger.error(
            "Gemini API call failed [%s]: %s",
            error.kind.value,
            error.detail,
        )
        if error.kind == AIErrorKind.API_ERROR:
            # Re-check for truly unexpected errors
            return AIResult.fail(
                AIError(
                    kind=AIErrorKind.UNEXPECTED,
                    message="An unexpected error occurred while contacting Gemini. Please try again.",
                    detail=str(exc),
                )
            )
        return AIResult.fail(error)


# ── Public API ────────────────────────────────────────────────────────────────

def generate_event_plan(
    config: AppConfig,
    event_name: str,
    event_type: str,
    location: str,
    event_date: str,
    guest_count: int,
    total_budget: float,
    preferences: str,
) -> AIResult:
    """
    Generate a personalised event plan using Gemini.

    Args:
        config:       AppConfig (used for API key and model name).
        event_name:   Name of the event.
        event_type:   Type of celebration (e.g., "Wedding").
        location:     City or region (used for regional suggestions).
        event_date:   ISO date string (YYYY-MM-DD).
        guest_count:  Number of expected guests.
        total_budget: Total budget in INR.
        preferences:  Free-text user preferences.

    Returns:
        AIResult with validated event plan dict, or a structured AIError.

    Note:
        Budget figures in the response are SUGGESTIONS. Arithmetic is
        re-verified by budget_service.py before use.
    """
    if not config.ai_available:
        return AIResult.fail(
            AIError(
                kind=AIErrorKind.MISSING_CREDENTIALS,
                message="AI features are not available. Please configure your Gemini API key.",
            )
        )

    client = _build_client(config)
    if client is None:
        return AIResult.fail(
            AIError(
                kind=AIErrorKind.MISSING_CREDENTIALS,
                message="Could not initialise the Gemini client. Please check your API key.",
            )
        )

    prompt = f"""
You are an expert Indian event planner. Generate a detailed, personalised event plan for the following celebration.

EVENT DETAILS:
- Event Name: {event_name}
- Event Type: {event_type}
- Location: {location}
- Event Date: {event_date}
- Guest Count: {guest_count}
- Total Budget (INR): {total_budget:,.0f}
- Preferences / Special Requests: {preferences or "None specified"}

IMPORTANT INSTRUCTIONS:
1. Return ONLY valid JSON matching the schema below. No markdown, no explanation.
2. Budget breakdown amounts must be positive numbers (INR). They are SUGGESTIONS for allocation — do not claim exact prices.
3. Timeline milestones must have deadlines on or before the event date ({event_date}).
4. Include regionally relevant suggestions for {location} where appropriate (Telugu, Tamil, North Indian traditions etc.) — but label them as suggestions, not universal rules.
5. Do not invent specific vendor names, prices or availability.

REQUIRED JSON SCHEMA:
{{
  "event_summary": "<2-3 sentence overview of the event plan>",
  "key_highlights": ["<highlight 1>", "<highlight 2>", "..."],
  "budget_breakdown": {{
    "<category>": <suggested_amount_inr>,
    ...
  }},
  "timeline_milestones": [
    {{
      "task": "<task description>",
      "deadline": "<YYYY-MM-DD>",
      "priority": "<high|medium|low>"
    }}
  ],
  "vendor_checklist": [
    {{
      "category": "<vendor category>",
      "name_suggestion": "<generic description, not a specific vendor>",
      "notes": "<what to look for / questions to ask>"
    }}
  ],
  "cultural_notes": "<optional: culturally relevant suggestions for this event type and location>"
}}
"""

    return _generate_json(client, config.gemini_model, prompt, validate_ai_event_plan)


def generate_budget_suggestions(
    config: AppConfig,
    event_type: str,
    total_budget: float,
    allocated_items: list[dict],
    overrun_categories: list[str],
) -> AIResult:
    """
    Generate cost-optimisation suggestions for a given budget allocation.

    Args:
        config:               AppConfig.
        event_type:           Type of celebration.
        total_budget:         Total budget in INR.
        allocated_items:      List of {category, allocated_amount, actual_amount}.
        overrun_categories:   Categories where actual > allocated.

    Returns:
        AIResult with validated budget suggestion dict, or a structured AIError.

    Note:
        "potential_saving" values in the AI response are treated as rough
        estimates only. Python arithmetic is used for all real calculations.
    """
    if not config.ai_available:
        return AIResult.fail(
            AIError(
                kind=AIErrorKind.MISSING_CREDENTIALS,
                message="AI features are not available. Please configure your Gemini API key.",
            )
        )

    client = _build_client(config)
    if client is None:
        return AIResult.fail(
            AIError(
                kind=AIErrorKind.MISSING_CREDENTIALS,
                message="Could not initialise the Gemini client.",
            )
        )

    items_text = "\n".join(
        f"  - {item['category']}: allocated ₹{item.get('allocated_amount', 0):,.0f}, "
        f"actual ₹{item.get('actual_amount', 0):,.0f}"
        for item in allocated_items
    )
    overruns_text = ", ".join(overrun_categories) if overrun_categories else "None"

    prompt = f"""
You are a budget optimisation expert for Indian celebrations.

EVENT TYPE: {event_type}
TOTAL BUDGET (INR): {total_budget:,.0f}

CURRENT BUDGET ALLOCATION:
{items_text}

CATEGORIES OVER BUDGET: {overruns_text}

Provide practical cost-saving suggestions. Return ONLY valid JSON with this schema:
{{
  "optimizations": [
    {{
      "category": "<category name>",
      "suggestion": "<specific, actionable suggestion>",
      "potential_saving": "<rough estimate as a string, e.g. '10-15%' or '₹5,000-₹10,000'>"
    }}
  ],
  "summary": "<2-3 sentence overall budget advice>"
}}

Rules:
- Do not invent specific prices or vendor names.
- Potential savings are rough estimates, not guarantees.
- Focus on actionable suggestions relevant to Indian celebrations.
"""

    return _generate_json(
        client, config.gemini_model, prompt, validate_ai_budget_suggestions
    )


def answer_event_question(
    config: AppConfig,
    question: str,
    event_context: dict[str, Any],
    conversation_history: list[dict[str, str]],
) -> AIResult:
    """
    Answer a user question about their event in a conversational style.

    Args:
        config:               AppConfig.
        question:             The user's question.
        event_context:        Dict with current event details (name, type, budget etc.).
        conversation_history: List of {role, content} dicts (recent turns only).

    Returns:
        AIResult with {"answer": str} dict, or a structured AIError.
    """
    if not config.ai_available:
        return AIResult.fail(
            AIError(
                kind=AIErrorKind.MISSING_CREDENTIALS,
                message="AI Assistant requires a Gemini API key. Please configure it to continue.",
            )
        )

    client = _build_client(config)
    if client is None:
        return AIResult.fail(
            AIError(
                kind=AIErrorKind.MISSING_CREDENTIALS,
                message="Could not initialise the Gemini client.",
            )
        )

    # Build a compact event context summary (never include raw SQL data)
    ctx_lines = [
        f"Event: {event_context.get('name', 'Unnamed')}",
        f"Type: {event_context.get('event_type', 'Unknown')}",
        f"Date: {event_context.get('event_date', 'TBD')}",
        f"Guests: {event_context.get('guest_count', 'Unknown')}",
        f"Budget: ₹{event_context.get('total_budget', 0):,.0f}",
        f"Location: {event_context.get('location', 'Not specified')}",
    ]
    ctx_text = "\n".join(ctx_lines)

    # Build conversation history (capped at last 6 turns to stay within context)
    history_text = ""
    for turn in conversation_history[-6:]:
        role = turn.get("role", "user").upper()
        content = turn.get("content", "")
        history_text += f"\n{role}: {content}"

    prompt = f"""
You are UtsavAI, a helpful and knowledgeable Indian event planning assistant.
You are helping a user plan their celebration. Be warm, specific and practical.

CURRENT EVENT CONTEXT:
{ctx_text}

RECENT CONVERSATION:{history_text}

USER QUESTION: {question}

Instructions:
- Answer specifically for this event's context.
- If you suggest budget amounts, frame them as estimates, not guarantees.
- Do not invent specific vendor names or availability.
- If the question is outside event planning scope, politely redirect.
- Keep the answer concise (3-5 sentences) unless detail is specifically requested.

Return ONLY valid JSON:
{{
  "answer": "<your response here>"
}}
"""

    def _validate_answer(data: Any) -> tuple[bool, str]:
        if not isinstance(data, dict):
            return False, "Response must be a JSON object."
        if "answer" not in data:
            return False, "Response missing 'answer' field."
        if not isinstance(data["answer"], str) or not data["answer"].strip():
            return False, "'answer' must be a non-empty string."
        return True, ""

    return _generate_json(client, config.gemini_model, prompt, _validate_answer)
