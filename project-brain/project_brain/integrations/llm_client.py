"""C-02: Unified LLM client interface.

Provides a single ``LLMClient`` Protocol that all Brain subsystems use,
replacing the scattered ``client.messages.create()`` / ``client.chat.completions.create()``
calls across the codebase.

Architecture:
  - ``LLMClient`` Protocol — one method: ``complete(prompt, ...) → str``
  - ``OllamaLLMClient`` — calls local Ollama via urllib (zero deps)
  - ``AnthropicLLMClient`` — calls Anthropic API via ``anthropic`` SDK
  - ``FallbackLLMClient`` — tries primary, falls back to secondary
  - ``from_brain_config(section, brain_dir)`` — factory from brain.toml

Usage:
    from project_brain.integrations.llm_client import from_brain_config

    client = from_brain_config("pipeline", brain_dir)
    text = client.complete("Summarize this knowledge node.", max_tokens=256)
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_URL = "http://localhost:11434"


# ── Protocol ──────────────────────────────────────────────────────


@runtime_checkable
class LLMClient(Protocol):
    """Unified LLM call interface.

    All Brain subsystems should depend on this Protocol, not on
    specific SDK types (anthropic.Anthropic, openai.OpenAI, etc.).
    """

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.1,
        timeout: int = 30,
    ) -> str:
        """Send a single-turn prompt and return the text response.

        Args:
            prompt:      The user message (plain text).
            max_tokens:  Maximum tokens in the response.
            temperature: Sampling temperature (0.0 = deterministic).
            timeout:     Request timeout in seconds.

        Returns:
            The model's text response.

        Raises:
            RuntimeError: If the request fails after retries.
        """
        ...

    @property
    def model(self) -> str:
        """The model identifier used by this client."""
        ...


# ── Ollama implementation ─────────────────────────────────────────


class OllamaLLMClient:
    """Local Ollama backend (zero external dependencies).

    Uses ``/api/chat`` endpoint with JSON format enforcement.
    """

    def __init__(
        self,
        model: str = "gemma3:4b",
        base_url: str = DEFAULT_OLLAMA_URL,
        default_timeout: int = 120,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._default_timeout = default_timeout

    @property
    def model(self) -> str:
        return self._model

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.1,
        timeout: int = 0,
    ) -> str:
        timeout = timeout or self._default_timeout
        url = f"{self._base_url}/api/chat"
        payload = json.dumps({
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": "json",
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }).encode()

        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read())
            return body.get("message", {}).get("content", "")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Ollama request failed: {e}") from e
        except Exception as e:
            raise RuntimeError(f"Ollama request failed: {e}") from e

    @staticmethod
    def available(base_url: str = DEFAULT_OLLAMA_URL) -> bool:
        """Check if Ollama is reachable."""
        try:
            req = urllib.request.Request(f"{base_url.rstrip('/')}/api/tags")
            with urllib.request.urlopen(req, timeout=3):
                return True
        except Exception:
            return False

    def __repr__(self) -> str:
        return f"OllamaLLMClient(model={self._model!r}, url={self._base_url!r})"


# ── Anthropic implementation ──────────────────────────────────────


class AnthropicLLMClient:
    """Anthropic API backend (requires ``anthropic`` package + API key)."""

    def __init__(
        self,
        model: str = "claude-haiku-4-5-20251001",
        api_key: str = "",
        default_timeout: int = 30,
        max_retries: int = 2,
    ) -> None:
        self._model = model
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._default_timeout = default_timeout
        self._max_retries = max_retries
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import anthropic
            except ImportError:
                raise RuntimeError(
                    "anthropic package not installed. "
                    "Install with: pip install anthropic"
                )
            if not self._api_key:
                raise RuntimeError("ANTHROPIC_API_KEY not set")
            self._client = anthropic.Anthropic(
                api_key=self._api_key,
                timeout=self._default_timeout,
            )
        return self._client

    @property
    def model(self) -> str:
        return self._model

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.1,
        timeout: int = 0,
    ) -> str:
        client = self._get_client()
        last_err: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                resp = client.messages.create(
                    model=self._model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.content[0].text
            except Exception as e:
                last_err = e
                err_str = str(e).lower()
                if "rate" in err_str or "overloaded" in err_str:
                    wait = 2 ** attempt
                    logger.debug("Anthropic rate-limited, retry in %ds", wait)
                    time.sleep(wait)
                    continue
                raise RuntimeError(f"Anthropic request failed: {e}") from e

        raise RuntimeError(f"Anthropic request failed after retries: {last_err}")

    def __repr__(self) -> str:
        return f"AnthropicLLMClient(model={self._model!r})"


# ── Fallback wrapper ──────────────────────────────────────────────


class FallbackLLMClient:
    """Try primary client first; fall back to secondary on failure."""

    def __init__(self, primary: LLMClient, fallback: LLMClient) -> None:
        self._primary = primary
        self._fallback = fallback

    @property
    def model(self) -> str:
        return self._primary.model

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.1,
        timeout: int = 0,
    ) -> str:
        try:
            return self._primary.complete(
                prompt, max_tokens=max_tokens,
                temperature=temperature, timeout=timeout,
            )
        except Exception as primary_err:
            logger.debug(
                "LLM primary (%s) failed: %s — trying fallback (%s)",
                self._primary.model, primary_err, self._fallback.model,
            )
            try:
                return self._fallback.complete(
                    prompt, max_tokens=max_tokens,
                    temperature=temperature, timeout=timeout,
                )
            except Exception as fallback_err:
                raise RuntimeError(
                    f"Both LLM clients failed. "
                    f"Primary ({self._primary.model}): {primary_err}; "
                    f"Fallback ({self._fallback.model}): {fallback_err}"
                ) from fallback_err

    def __repr__(self) -> str:
        return (
            f"FallbackLLMClient(primary={self._primary!r}, "
            f"fallback={self._fallback!r})"
        )


# ── Noop client (for testing / LLM-unavailable environments) ──────


class NoopLLMClient:
    """Returns empty string for all prompts. Used when no LLM is configured."""

    def __init__(self, model: str = "noop") -> None:
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    def complete(self, prompt: str, **kwargs: Any) -> str:
        return ""

    def __repr__(self) -> str:
        return "NoopLLMClient()"


# ── Factory ───────────────────────────────────────────────────────


def from_brain_config(
    section: str = "pipeline",
    brain_dir: Path | None = None,
) -> LLMClient:
    """Build an LLMClient from ``brain.toml`` configuration.

    Args:
        section:   Config section to read (``"pipeline"`` reads ``[pipeline.llm]``,
                   ``"review"`` reads ``[review.model]``).
        brain_dir: Path to ``.brain/`` directory. Falls back to env var
                   ``BRAIN_WORKDIR`` or current directory.

    Returns:
        An LLMClient instance. If the primary provider is unavailable but a
        fallback is configured, returns a FallbackLLMClient wrapping both.
        If nothing is configured and no API key exists, returns NoopLLMClient.
    """
    cfg = _load_config(brain_dir)

    if section == "review":
        return _build_from_section(cfg.get("review", {}).get("model", {}), cfg)

    # Default: [pipeline.llm]
    llm_cfg = cfg.get("pipeline", {}).get("llm", {})
    return _build_from_section(llm_cfg, cfg)


def _load_config(brain_dir: Path | None) -> dict:
    """Read brain.toml if it exists."""
    if brain_dir is None:
        wd = os.environ.get("BRAIN_WORKDIR", ".")
        brain_dir = Path(wd) / ".brain"

    toml_path = brain_dir / "brain.toml"
    if not toml_path.exists():
        return {}

    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            return {}

    try:
        with open(toml_path, "rb") as f:
            return tomllib.load(f)
    except Exception as e:
        logger.debug("Failed to load brain.toml: %s", e)
        return {}


def _build_from_section(section: dict, full_cfg: dict) -> LLMClient:
    """Build an LLMClient from a config section dict."""
    provider = section.get("provider", "").lower()
    model = section.get("model", "")
    base_url = section.get("base_url", DEFAULT_OLLAMA_URL)
    timeout = int(section.get("timeout", 30))

    # Explicit Anthropic
    if provider == "anthropic" or (not provider and os.environ.get("ANTHROPIC_API_KEY")):
        model = model or "claude-haiku-4-5-20251001"
        primary = AnthropicLLMClient(
            model=model,
            default_timeout=timeout,
        )
        # Check for Ollama fallback
        fallback_cfg = section.get("fallback", {})
        if fallback_cfg:
            fallback = _build_from_section(fallback_cfg, full_cfg)
            return FallbackLLMClient(primary, fallback)
        return primary

    # Explicit Ollama
    if provider == "ollama":
        model = model or "gemma3:4b"
        primary: LLMClient = OllamaLLMClient(
            model=model, base_url=base_url, default_timeout=timeout,
        )
        # Check for fallback
        fallback_cfg = section.get("fallback", {})
        if fallback_cfg:
            fallback = _build_from_section(fallback_cfg, full_cfg)
            return FallbackLLMClient(primary, fallback)
        return primary

    # No provider specified — try Ollama first, then Anthropic, then noop
    if OllamaLLMClient.available(base_url):
        return OllamaLLMClient(
            model=model or "gemma3:4b",
            base_url=base_url,
            default_timeout=timeout,
        )

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        return AnthropicLLMClient(
            model=model or "claude-haiku-4-5-20251001",
            default_timeout=timeout,
        )

    return NoopLLMClient()
