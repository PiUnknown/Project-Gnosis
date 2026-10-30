"""Tests for the NVIDIA NIM client: model resolution, fallbacks, and failures.

No network calls — the OpenAI client is replaced with a fake that returns
scripted responses per model name.
"""
from types import SimpleNamespace

import pytest

from src.utils import nvidia_client
from src.utils.nvidia_client import (
    LLMUnavailableError,
    NVIDIA_MODEL_DEFAULT,
    _configured_models,
    _is_model_unavailable,
    call_llm,
)


def _ok_response(text: str, finish: str = "stop"):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=text),
                finish_reason=finish,
            )
        ],
        usage=SimpleNamespace(total_tokens=42),
    )


class _FakeClient:
    """Returns or raises per model name, and records which models were tried."""

    def __init__(self, behaviour: dict):
        self.behaviour = behaviour
        self.calls = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, model, messages, temperature, max_tokens, timeout):
        self.calls.append(model)
        result = self.behaviour.get(model, KeyError(model))
        if isinstance(result, Exception):
            raise result
        return result


def _install(monkeypatch, behaviour):
    client = _FakeClient(behaviour)
    monkeypatch.setattr(nvidia_client, "get_client", lambda: client)
    return client


class _NotFound(Exception):
    """Mirrors openai.NotFoundError closely enough for the classifier."""


def test_default_model_is_available_in_catalogue():
    # The previous default (meta/llama-3.2-11b-vision-instruct) returns 404.
    assert NVIDIA_MODEL_DEFAULT == "poolside/laguna-xs-2.1"


def test_configured_models_defaults_to_primary_then_fallback(monkeypatch):
    monkeypatch.delenv("NVIDIA_MODEL", raising=False)
    monkeypatch.delenv("NVIDIA_MODEL_FALLBACKS", raising=False)
    models = _configured_models()
    assert models[0] == NVIDIA_MODEL_DEFAULT
    assert len(models) > 1
    assert len(models) == len(set(models))


def test_configured_models_respects_env(monkeypatch):
    monkeypatch.setenv("NVIDIA_MODEL", "vendor/primary")
    monkeypatch.setenv("NVIDIA_MODEL_FALLBACKS", "vendor/a, vendor/b ,vendor/a")
    assert _configured_models() == ["vendor/primary", "vendor/a", "vendor/b"]


def test_configured_models_can_disable_fallbacks(monkeypatch):
    monkeypatch.setenv("NVIDIA_MODEL", "vendor/primary")
    monkeypatch.setenv("NVIDIA_MODEL_FALLBACKS", "")
    assert _configured_models() == ["vendor/primary"]


def test_is_model_unavailable_classifies_404_and_410():
    assert _is_model_unavailable(_NotFound("Error code: 404 - not found"))
    assert _is_model_unavailable(RuntimeError("Error code: 410 - Gone: end of life"))
    assert not _is_model_unavailable(RuntimeError("429 rate limit"))
    assert not _is_model_unavailable(TimeoutError("request timed out"))


def test_falls_back_when_primary_model_is_gone(monkeypatch):
    monkeypatch.setenv("NVIDIA_MODEL", "vendor/retired")
    monkeypatch.setenv("NVIDIA_MODEL_FALLBACKS", "vendor/working")
    client = _install(
        monkeypatch,
        {
            "vendor/retired": _NotFound("Error code: 404 - model not found"),
            "vendor/working": _ok_response("Explanation from fallback."),
        },
    )

    result = call_llm("system", "user")

    assert result == "Explanation from fallback."
    # The retired model must not be retried: one attempt, then move on.
    assert client.calls == ["vendor/retired", "vendor/working"]


def test_empty_completion_moves_to_next_model(monkeypatch):
    """Reasoning models can burn the whole token budget and return nothing."""
    monkeypatch.setenv("NVIDIA_MODEL", "vendor/reasoner")
    monkeypatch.setenv("NVIDIA_MODEL_FALLBACKS", "vendor/working")
    client = _install(
        monkeypatch,
        {
            "vendor/reasoner": _ok_response("", finish="length"),
            "vendor/working": _ok_response("Real explanation."),
        },
    )

    result = call_llm("system", "user")

    assert result == "Real explanation."
    assert client.calls == ["vendor/reasoner", "vendor/working"]


def test_all_models_failing_returns_none_by_default(monkeypatch):
    monkeypatch.setenv("NVIDIA_MODEL", "vendor/a")
    monkeypatch.setenv("NVIDIA_MODEL_FALLBACKS", "vendor/b")
    _install(
        monkeypatch,
        {
            "vendor/a": _NotFound("Error code: 404 - nope"),
            "vendor/b": _NotFound("Error code: 410 - gone"),
        },
    )

    assert call_llm("system", "user") is None


def test_all_models_failing_raises_with_provider_message(monkeypatch):
    monkeypatch.setenv("NVIDIA_MODEL", "vendor/a")
    monkeypatch.setenv("NVIDIA_MODEL_FALLBACKS", "vendor/b")
    _install(
        monkeypatch,
        {
            "vendor/a": _NotFound("Error code: 404 - nope"),
            "vendor/b": _NotFound("Error code: 410 - end of life"),
        },
    )

    with pytest.raises(LLMUnavailableError) as excinfo:
        call_llm("system", "user", raise_on_failure=True)

    message = str(excinfo.value)
    assert "vendor/b" in message
    assert "410" in message


def test_transient_error_retries_same_model(monkeypatch):
    monkeypatch.setenv("NVIDIA_MODEL", "vendor/flaky")
    monkeypatch.setenv("NVIDIA_MODEL_FALLBACKS", "")

    attempts = []

    class _Flaky(_FakeClient):
        def create(self, model, messages, temperature, max_tokens, timeout):
            attempts.append(model)
            if len(attempts) == 1:
                raise TimeoutError("read timeout")
            return _ok_response("Recovered.")

    client = _Flaky({})
    monkeypatch.setattr(nvidia_client, "get_client", lambda: client)
    monkeypatch.setattr(nvidia_client, "BASE_DELAY_SECONDS", 0.0)

    assert call_llm("system", "user") == "Recovered."
    assert attempts == ["vendor/flaky", "vendor/flaky"]
