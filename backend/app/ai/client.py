"""Gemini client. Reads GEMINI_API_KEY and GEMINI_MODEL from settings."""

from google import genai
from google.genai import errors, types

from app.config import settings


class AIUnavailable(Exception):
    """No API key configured: callers fall back to templates or mock data."""


class AIRefused(Exception):
    """Gemini blocked the request or stopped for a safety reason."""


class AIFailed(Exception):
    """The Gemini API returned an error (bad key, rate limit, outage)."""


_client: genai.Client | None = None

# Finish reasons that mean Gemini declined to answer (vs. a normal stop or running out of tokens).
_BLOCKED = {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "RECITATION"}


def enabled() -> bool:
    return settings.ai_enabled


def model() -> str:
    return settings.ai_model


def get_client() -> genai.Client:
    global _client
    if not settings.ai_enabled:
        raise AIUnavailable("GEMINI_API_KEY is not set")
    if _client is None:
        _client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(timeout=120_000, retry_options=types.HttpRetryOptions(attempts=3)),
        )
    return _client


def thinking(level: str) -> types.ThinkingConfig | None:
    """How hard the model thinks: 'low' for short messages, 'medium' for documents and chat.
    Gemini 2.x models use a token budget instead, so leave it unset for them."""
    if model().startswith("gemini-2"):
        return None
    return types.ThinkingConfig(thinking_level=level.upper())


def generate(**kwargs) -> types.GenerateContentResponse:
    """generate_content with API errors turned into AIFailed, so routes can show a clear message."""
    try:
        return get_client().models.generate_content(model=model(), **kwargs)
    except errors.APIError as exc:
        hint = " Wait a minute and try again (free-tier rate limit)." if exc.code == 429 else ""
        raise AIFailed(f"Gemini error {exc.code}: {(exc.message or '').rstrip('.')}.{hint}") from exc


def check_refusal(response: types.GenerateContentResponse) -> None:
    feedback = response.prompt_feedback
    if feedback and feedback.block_reason:
        raise AIRefused(f"Gemini blocked this request ({_name(feedback.block_reason)})")
    if not response.candidates:
        raise AIRefused("Gemini returned no answer")
    reason = _name(response.candidates[0].finish_reason)
    if reason in _BLOCKED:
        raise AIRefused(f"Gemini declined this request ({reason})")


def first_text(response: types.GenerateContentResponse) -> str:
    return (response.text or "").strip()


def _name(value) -> str:
    return getattr(value, "name", None) or str(value)
