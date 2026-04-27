"""
C-02: Unified LLM Client tests

Tests for project_brain.integrations.llm_client:
- LLMClient Protocol conformance
- OllamaLLMClient (mocked urllib)
- AnthropicLLMClient (mocked SDK)
- FallbackLLMClient logic
- NoopLLMClient
- from_brain_config factory
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from project_brain.integrations.llm_client import (
    AnthropicLLMClient,
    FallbackLLMClient,
    LLMClient,
    NoopLLMClient,
    OllamaLLMClient,
    from_brain_config,
)


# ════════════════════════════════════════════════════════════════
# Protocol conformance
# ════════════════════════════════════════════════════════════════


class TestProtocol:
    """All implementations satisfy LLMClient Protocol."""

    def test_ollama_is_llm_client(self):
        assert isinstance(OllamaLLMClient(), LLMClient)

    def test_anthropic_is_llm_client(self):
        assert isinstance(AnthropicLLMClient(api_key="test"), LLMClient)

    def test_noop_is_llm_client(self):
        assert isinstance(NoopLLMClient(), LLMClient)

    def test_fallback_is_llm_client(self):
        p = NoopLLMClient()
        f = NoopLLMClient()
        assert isinstance(FallbackLLMClient(p, f), LLMClient)


# ════════════════════════════════════════════════════════════════
# NoopLLMClient
# ════════════════════════════════════════════════════════════════


class TestNoopClient:
    """NoopLLMClient returns empty string for all prompts."""

    def test_complete_returns_empty(self):
        c = NoopLLMClient()
        assert c.complete("anything") == ""

    def test_model_is_noop(self):
        c = NoopLLMClient()
        assert c.model == "noop"

    def test_repr(self):
        assert "Noop" in repr(NoopLLMClient())


# ════════════════════════════════════════════════════════════════
# OllamaLLMClient
# ════════════════════════════════════════════════════════════════


class TestOllamaClient:
    """OllamaLLMClient calls /api/chat with correct payload."""

    def test_model_property(self):
        c = OllamaLLMClient(model="gemma3:4b")
        assert c.model == "gemma3:4b"

    def test_repr(self):
        c = OllamaLLMClient(model="test")
        assert "test" in repr(c)

    @patch("project_brain.integrations.llm_client.urllib.request.urlopen")
    def test_complete_sends_correct_payload(self, mock_urlopen):
        import json
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps({
            "message": {"content": "test response"}
        }).encode()
        mock_urlopen.return_value = mock_resp

        c = OllamaLLMClient(model="gemma3:4b")
        result = c.complete("hello", max_tokens=100, temperature=0.5)

        assert result == "test response"
        # Verify the request was made
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        body = json.loads(req.data)
        assert body["model"] == "gemma3:4b"
        assert body["messages"] == [{"role": "user", "content": "hello"}]
        assert body["options"]["num_predict"] == 100
        assert body["options"]["temperature"] == 0.5

    @patch("project_brain.integrations.llm_client.urllib.request.urlopen")
    def test_complete_raises_on_failure(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("connection refused")

        c = OllamaLLMClient()
        with pytest.raises(RuntimeError, match="Ollama request failed"):
            c.complete("hello")


# ════════════════════════════════════════════════════════════════
# AnthropicLLMClient
# ════════════════════════════════════════════════════════════════


class TestAnthropicClient:
    """AnthropicLLMClient calls anthropic SDK."""

    def test_model_property(self):
        c = AnthropicLLMClient(model="claude-haiku-4-5-20251001", api_key="test")
        assert c.model == "claude-haiku-4-5-20251001"

    def test_no_api_key_raises(self):
        c = AnthropicLLMClient(api_key="")
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
                c.complete("hello")

    def test_complete_with_mock_sdk(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="mocked response")]
        mock_client.messages.create.return_value = mock_resp

        c = AnthropicLLMClient(model="haiku", api_key="test-key")
        c._client = mock_client  # inject mock

        result = c.complete("test prompt", max_tokens=256)
        assert result == "mocked response"
        mock_client.messages.create.assert_called_once_with(
            model="haiku",
            max_tokens=256,
            messages=[{"role": "user", "content": "test prompt"}],
        )

    def test_repr(self):
        c = AnthropicLLMClient(model="haiku")
        assert "haiku" in repr(c)


# ════════════════════════════════════════════════════════════════
# FallbackLLMClient
# ════════════════════════════════════════════════════════════════


class TestFallbackClient:
    """FallbackLLMClient tries primary then falls back."""

    def test_uses_primary_when_available(self):
        primary = MagicMock(spec=LLMClient)
        primary.model = "primary"
        primary.complete.return_value = "from primary"

        fallback = MagicMock(spec=LLMClient)
        fallback.model = "fallback"

        c = FallbackLLMClient(primary, fallback)
        result = c.complete("test")
        assert result == "from primary"
        fallback.complete.assert_not_called()

    def test_falls_back_on_primary_failure(self):
        primary = MagicMock(spec=LLMClient)
        primary.model = "primary"
        primary.complete.side_effect = RuntimeError("primary down")

        fallback = MagicMock(spec=LLMClient)
        fallback.model = "fallback"
        fallback.complete.return_value = "from fallback"

        c = FallbackLLMClient(primary, fallback)
        result = c.complete("test")
        assert result == "from fallback"

    def test_raises_when_both_fail(self):
        primary = MagicMock(spec=LLMClient)
        primary.model = "primary"
        primary.complete.side_effect = RuntimeError("primary down")

        fallback = MagicMock(spec=LLMClient)
        fallback.model = "fallback"
        fallback.complete.side_effect = RuntimeError("fallback down")

        c = FallbackLLMClient(primary, fallback)
        with pytest.raises(RuntimeError, match="Both LLM clients failed"):
            c.complete("test")

    def test_model_returns_primary_model(self):
        primary = MagicMock(spec=LLMClient)
        primary.model = "primary-model"
        fallback = MagicMock(spec=LLMClient)
        fallback.model = "fallback-model"

        c = FallbackLLMClient(primary, fallback)
        assert c.model == "primary-model"

    def test_repr(self):
        p = NoopLLMClient(model="p")
        f = NoopLLMClient(model="f")
        assert "Fallback" in repr(FallbackLLMClient(p, f))


# ════════════════════════════════════════════════════════════════
# from_brain_config factory
# ════════════════════════════════════════════════════════════════


class TestFromBrainConfig:
    """Factory function builds correct client from config."""

    def test_no_config_no_ollama_no_key_returns_noop(self, tmp_path):
        """No brain.toml, no Ollama, no API key → NoopLLMClient."""
        bd = tmp_path / ".brain"
        bd.mkdir()
        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "project_brain.integrations.llm_client.OllamaLLMClient.available",
                return_value=False,
            ):
                c = from_brain_config("pipeline", brain_dir=bd)
                assert isinstance(c, NoopLLMClient)

    def test_ollama_available_returns_ollama_client(self, tmp_path):
        """Ollama reachable → OllamaLLMClient."""
        bd = tmp_path / ".brain"
        bd.mkdir()
        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "project_brain.integrations.llm_client.OllamaLLMClient.available",
                return_value=True,
            ):
                c = from_brain_config("pipeline", brain_dir=bd)
                assert isinstance(c, OllamaLLMClient)

    def test_anthropic_key_returns_anthropic_client(self, tmp_path):
        """No Ollama but ANTHROPIC_API_KEY set → AnthropicLLMClient."""
        bd = tmp_path / ".brain"
        bd.mkdir()
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}, clear=True):
            with patch(
                "project_brain.integrations.llm_client.OllamaLLMClient.available",
                return_value=False,
            ):
                c = from_brain_config("pipeline", brain_dir=bd)
                assert isinstance(c, AnthropicLLMClient)

    def test_toml_ollama_section(self, tmp_path):
        """brain.toml with [pipeline.llm] provider=ollama → OllamaLLMClient."""
        bd = tmp_path / ".brain"
        bd.mkdir()
        toml = bd / "brain.toml"
        toml.write_text(
            '[pipeline.llm]\nprovider = "ollama"\nmodel = "gemma3:4b"\n'
            'base_url = "http://localhost:11434"\n'
        )
        c = from_brain_config("pipeline", brain_dir=bd)
        assert isinstance(c, OllamaLLMClient)
        assert c.model == "gemma3:4b"

    def test_toml_anthropic_section(self, tmp_path):
        """brain.toml with provider=anthropic → AnthropicLLMClient."""
        bd = tmp_path / ".brain"
        bd.mkdir()
        toml = bd / "brain.toml"
        toml.write_text(
            '[pipeline.llm]\nprovider = "anthropic"\n'
            'model = "claude-haiku-4-5-20251001"\n'
        )
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            c = from_brain_config("pipeline", brain_dir=bd)
            assert isinstance(c, AnthropicLLMClient)
            assert c.model == "claude-haiku-4-5-20251001"

    def test_missing_brain_dir_returns_client(self, tmp_path):
        """Non-existent brain_dir → NoopLLMClient (no crash)."""
        bd = tmp_path / "nonexistent"
        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "project_brain.integrations.llm_client.OllamaLLMClient.available",
                return_value=False,
            ):
                c = from_brain_config("pipeline", brain_dir=bd)
                assert isinstance(c, NoopLLMClient)


# ════════════════════════════════════════════════════════════════
# Integration: LLMJudgmentEngine uses LLMClient
# ════════════════════════════════════════════════════════════════


class TestLLMJudgmentIntegration:
    """LLMJudgmentEngine._call_llm uses unified LLMClient when provided."""

    def test_call_llm_uses_llm_client(self):
        from project_brain.pipeline.llm_judgment import LLMJudgmentEngine

        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.model = "test-model"
        mock_llm.complete.return_value = '{"action": "skip", "reason": "test"}'

        engine = LLMJudgmentEngine(llm_client=mock_llm, model="test-model")
        result = engine._call_llm("test prompt")

        assert result == '{"action": "skip", "reason": "test"}'
        mock_llm.complete.assert_called_once()

    def test_call_llm_falls_back_to_legacy(self):
        """Without llm_client, uses legacy client.messages.create()."""
        from project_brain.pipeline.llm_judgment import LLMJudgmentEngine

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="legacy response")]
        mock_client.messages.create.return_value = mock_resp

        engine = LLMJudgmentEngine(client=mock_client, model="legacy")
        result = engine._call_llm("test")
        assert result == "legacy response"
