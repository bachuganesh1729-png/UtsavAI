"""
tests/test_gemini_service.py
─────────────────────────────
Unit tests for services/gemini_service.py.

Tests cover all error paths WITHOUT making real API calls.
The google.genai client is mocked using pytest-mock.

Covers:
- Missing API key → MISSING_CREDENTIALS error (no crash, no import error)
- Valid response → AIResult.success = True, validated data returned
- Empty response text → INVALID_RESPONSE error
- Non-JSON response → INVALID_RESPONSE error
- JSON-fenced response → successfully stripped and parsed
- Schema-invalid JSON → INVALID_RESPONSE error
- API key/auth error → MISSING_CREDENTIALS error
- Rate limit (429 / resource_exhausted) → RATE_LIMIT error
- Timeout → TIMEOUT error
- Generic API error → UNEXPECTED error
- _extract_json helper (fence stripping, bad JSON, non-dict)
- AIResult constructor helpers (ok / fail)
- AIError immutability
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from services.gemini_service import (
    AIErrorKind,
    AIError,
    AIResult,
    _extract_json,
    _classify_api_error,
    generate_event_plan,
    generate_budget_suggestions,
    answer_event_question,
)
from utils.config import AppConfig


# ── Helpers ───────────────────────────────────────────────────────────────────

def _config(has_key: bool = True, model: str = "gemini-test-model") -> AppConfig:
    """Build a test AppConfig with or without an API key."""
    key = "test-api-key-abc123" if has_key else None
    return AppConfig(gemini_api_key=key, gemini_model=model)


def _future(days: int = 90) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _valid_event_plan_json() -> str:
    return json.dumps({
        "event_summary": "A beautiful wedding in Hyderabad.",
        "key_highlights": ["Outdoor ceremony", "Live music", "Traditional decor"],
        "budget_breakdown": {"Venue": 50000, "Catering": 80000, "Decoration": 20000},
        "timeline_milestones": [
            {"task": "Book venue", "deadline": _future(60), "priority": "high"},
            {"task": "Send invites", "deadline": _future(30), "priority": "medium"},
        ],
        "vendor_checklist": [
            {"category": "Photography", "name_suggestion": "Local photographer", "notes": "Review portfolio"},
        ],
        "cultural_notes": "Consider traditional Telugu rituals.",
    })


def _valid_budget_suggestions_json() -> str:
    return json.dumps({
        "optimizations": [
            {"category": "Catering", "suggestion": "Use buffet.", "potential_saving": "10-15%"},
        ],
        "summary": "Reduce catering and decoration costs for savings.",
    })


def _valid_answer_json() -> str:
    return json.dumps({"answer": "You should book your venue at least 6 months in advance."})


def _mock_response(text: str) -> MagicMock:
    mock = MagicMock()
    mock.text = text
    return mock


# ── AIResult helpers ──────────────────────────────────────────────────────────

class TestAIResult:
    def test_ok_sets_success_true(self):
        result = AIResult.ok({"key": "value"})
        assert result.success is True
        assert result.data == {"key": "value"}
        assert result.error is None

    def test_fail_sets_success_false(self):
        error = AIError(kind=AIErrorKind.TIMEOUT, message="Timed out.")
        result = AIResult.fail(error)
        assert result.success is False
        assert result.data is None
        assert result.error is error

    def test_ai_error_is_frozen(self):
        error = AIError(kind=AIErrorKind.RATE_LIMIT, message="Rate limited.")
        with pytest.raises((AttributeError, TypeError)):
            error.message = "changed"  # type: ignore[misc]


# ── _extract_json ─────────────────────────────────────────────────────────────

class TestExtractJson:
    def test_plain_json(self):
        result = _extract_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_with_fenced_block(self):
        fenced = '```json\n{"key": "value"}\n```'
        result = _extract_json(fenced)
        assert result == {"key": "value"}

    def test_json_with_plain_fence(self):
        fenced = '```\n{"key": "value"}\n```'
        result = _extract_json(fenced)
        assert result == {"key": "value"}

    def test_invalid_json_returns_none(self):
        assert _extract_json("this is not json") is None

    def test_json_array_returns_none(self):
        assert _extract_json("[1, 2, 3]") is None

    def test_empty_string_returns_none(self):
        assert _extract_json("") is None

    def test_nested_json(self):
        data = {"budget": {"Venue": 50000, "Catering": 80000}}
        result = _extract_json(json.dumps(data))
        assert result == data


# ── _classify_api_error ───────────────────────────────────────────────────────

class TestClassifyApiError:
    def test_auth_error(self):
        err = _classify_api_error(Exception("API_KEY invalid_argument"))
        assert err.kind == AIErrorKind.MISSING_CREDENTIALS

    def test_unauthenticated(self):
        err = _classify_api_error(Exception("unauthenticated request"))
        assert err.kind == AIErrorKind.MISSING_CREDENTIALS

    def test_rate_limit_429(self):
        err = _classify_api_error(Exception("429 resource_exhausted quota exceeded"))
        assert err.kind == AIErrorKind.RATE_LIMIT

    def test_timeout(self):
        err = _classify_api_error(Exception("request timed out after 30s"))
        assert err.kind == AIErrorKind.TIMEOUT

    def test_deadline_exceeded(self):
        err = _classify_api_error(Exception("deadline exceeded"))
        assert err.kind == AIErrorKind.TIMEOUT

    def test_generic_api_error(self):
        err = _classify_api_error(Exception("internal server error"))
        assert err.kind == AIErrorKind.API_ERROR

    def test_error_message_is_user_safe(self):
        """Error messages must never expose raw exception internals."""
        err = _classify_api_error(Exception("api_key=sk-secret-value"))
        assert "sk-secret-value" not in err.message


# ── generate_event_plan ───────────────────────────────────────────────────────

class TestGenerateEventPlan:
    def test_missing_api_key_returns_error(self):
        config = _config(has_key=False)
        result = generate_event_plan(
            config, "Test Wedding", "Wedding", "Hyderabad",
            _future(180), 200, 500_000, "Traditional"
        )
        assert result.success is False
        assert result.error.kind == AIErrorKind.MISSING_CREDENTIALS

    def test_successful_response(self):
        config = _config()
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _mock_response(_valid_event_plan_json())

        with patch("services.gemini_service._build_client", return_value=mock_client):
            result = generate_event_plan(
                config, "Priya Wedding", "Wedding", "Chennai",
                _future(180), 150, 800_000, "South Indian traditions"
            )

        assert result.success is True
        assert "event_summary" in result.data
        assert "budget_breakdown" in result.data
        assert isinstance(result.data["budget_breakdown"], dict)

    def test_empty_response_returns_invalid_response_error(self):
        config = _config()
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _mock_response("")

        with patch("services.gemini_service._build_client", return_value=mock_client):
            result = generate_event_plan(
                config, "Test", "Wedding", "Delhi", _future(90), 100, 200_000, ""
            )

        assert result.success is False
        assert result.error.kind == AIErrorKind.INVALID_RESPONSE

    def test_non_json_response(self):
        config = _config()
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _mock_response(
            "Sure! Here is your event plan in natural language..."
        )

        with patch("services.gemini_service._build_client", return_value=mock_client):
            result = generate_event_plan(
                config, "Test", "Wedding", "Mumbai", _future(90), 50, 100_000, ""
            )

        assert result.success is False
        assert result.error.kind == AIErrorKind.INVALID_RESPONSE

    def test_schema_invalid_json(self):
        """JSON that parses but fails schema validation."""
        bad_json = json.dumps({"wrong_key": "value", "another": 123})
        config = _config()
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _mock_response(bad_json)

        with patch("services.gemini_service._build_client", return_value=mock_client):
            result = generate_event_plan(
                config, "Test", "Wedding", "Pune", _future(90), 80, 300_000, ""
            )

        assert result.success is False
        assert result.error.kind == AIErrorKind.INVALID_RESPONSE

    def test_rate_limit_exception(self):
        config = _config()
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("429 resource_exhausted")

        with patch("services.gemini_service._build_client", return_value=mock_client):
            result = generate_event_plan(
                config, "Test", "Wedding", "Kolkata", _future(90), 50, 200_000, ""
            )

        assert result.success is False
        assert result.error.kind == AIErrorKind.RATE_LIMIT

    def test_timeout_exception(self):
        config = _config()
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("request timed out")

        with patch("services.gemini_service._build_client", return_value=mock_client):
            result = generate_event_plan(
                config, "Test", "Wedding", "Bengaluru", _future(90), 50, 200_000, ""
            )

        assert result.success is False
        assert result.error.kind == AIErrorKind.TIMEOUT

    def test_json_fenced_response_parsed_correctly(self):
        """Model wraps JSON in markdown fences — should still succeed."""
        fenced = f"```json\n{_valid_event_plan_json()}\n```"
        config = _config()
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _mock_response(fenced)

        with patch("services.gemini_service._build_client", return_value=mock_client):
            result = generate_event_plan(
                config, "Fenced Test", "Wedding", "Hyderabad", _future(180), 200, 500_000, ""
            )

        assert result.success is True


# ── generate_budget_suggestions ───────────────────────────────────────────────

class TestGenerateBudgetSuggestions:
    def test_missing_key_returns_error(self):
        config = _config(has_key=False)
        result = generate_budget_suggestions(config, "Wedding", 500_000, [], [])
        assert result.success is False
        assert result.error.kind == AIErrorKind.MISSING_CREDENTIALS

    def test_successful_response(self):
        config = _config()
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _mock_response(
            _valid_budget_suggestions_json()
        )

        with patch("services.gemini_service._build_client", return_value=mock_client):
            result = generate_budget_suggestions(
                config, "Wedding", 500_000,
                [{"category": "Catering", "allocated_amount": 80_000, "actual_amount": 95_000}],
                ["Catering"],
            )

        assert result.success is True
        assert "optimizations" in result.data
        assert "summary" in result.data


# ── answer_event_question ─────────────────────────────────────────────────────

class TestAnswerEventQuestion:
    def test_missing_key_returns_error(self):
        config = _config(has_key=False)
        result = answer_event_question(config, "What should I do first?", {}, [])
        assert result.success is False
        assert result.error.kind == AIErrorKind.MISSING_CREDENTIALS

    def test_successful_answer(self):
        config = _config()
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _mock_response(_valid_answer_json())

        with patch("services.gemini_service._build_client", return_value=mock_client):
            result = answer_event_question(
                config,
                "How early should I book the venue?",
                {"name": "Test Wedding", "event_type": "Wedding", "event_date": _future(180),
                 "guest_count": 200, "total_budget": 500_000, "location": "Hyderabad"},
                [],
            )

        assert result.success is True
        assert "answer" in result.data
        assert isinstance(result.data["answer"], str)
        assert len(result.data["answer"]) > 0

    def test_conversation_history_capped(self):
        """Ensure long conversation history does not cause failures (uses last 6 turns)."""
        config = _config()
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _mock_response(_valid_answer_json())

        long_history = [{"role": "user", "content": f"Message {i}"} for i in range(20)]

        with patch("services.gemini_service._build_client", return_value=mock_client):
            result = answer_event_question(
                config, "Short question.", {"name": "Test", "event_type": "Wedding",
                 "event_date": _future(90), "guest_count": 50,
                 "total_budget": 100_000, "location": "Delhi"},
                long_history,
            )

        assert result.success is True
