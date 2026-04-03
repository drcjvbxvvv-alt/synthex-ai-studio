"""
project_brain/embedder.py — Phase 1: Embedding Backend

Priority order:
  1. Ollama (local, free, nomic-embed-text → 768 dim)
  2. OpenAI (API, text-embedding-3-small → 1536 dim)
  3. Anthropic voyage (if available)
  4. None → fallback to FTS5

Usage:
    emb = get_embedder()
    if emb:
        vec = emb.embed("JWT must use RS256")  # list[float]
    else:
        vec = None  # system falls back to FTS5
"""
from __future__ import annotations

import os
import hashlib
import logging
from collections import OrderedDict
from typing import Optional

logger = logging.getLogger(__name__)

# OPT-03/BUG-14 fix: True LRU cache for LocalTFIDFEmbedder (keyed by text hash).
# Uses OrderedDict so move_to_end() promotes hits; popitem(last=False) evicts LRU.
# Pure-Python TF-IDF is deterministic — same text always produces same vector.
# Max 1 024 entries (~4 MB assuming 256-dim float vectors).
_TFIDF_CACHE: OrderedDict = OrderedDict()
_TFIDF_CACHE_MAX = 1024

# Standard dimensions
DIM_OLLAMA  = 768   # nomic-embed-text
DIM_OPENAI  = 1536  # text-embedding-3-small
DIM_DEFAULT = 768


class OllamaEmbedder:
    """Local embedding via Ollama — zero cost, zero privacy concern."""

    MODEL = "nomic-embed-text"

    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url.rstrip("/")
        self.dim      = DIM_OLLAMA

    def embed(self, text: str) -> Optional[list[float]]:
        try:
            import urllib.request, json
            payload = json.dumps({"model": self.MODEL, "prompt": text[:2000]}).encode()
            req     = urllib.request.Request(
                f"{self.base_url}/api/embeddings",
                data=payload, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                return data["embedding"]
        except Exception as e:
            logger.debug("Ollama embed failed: %s", e)
            return None

    @classmethod
    def is_available(cls, base_url: str = "http://localhost:11434") -> bool:
        try:
            import urllib.request
            urllib.request.urlopen(f"{base_url}/api/tags", timeout=2)
            return True
        except Exception:
            return False


class OpenAIEmbedder:
    """OpenAI text-embedding-3-small — cheap ($0.00002/1K tokens)."""

    MODEL = "text-embedding-3-small"

    def __init__(self):
        self.dim = DIM_OPENAI

    def embed(self, text: str) -> Optional[list[float]]:
        try:
            from openai import OpenAI
            base = os.environ.get("BRAIN_LLM_BASE_URL", "")
            key  = os.environ.get("OPENAI_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")
            client = OpenAI(api_key=key or "x", base_url=base or None)
            resp = client.embeddings.create(model=self.MODEL, input=text[:8000])
            return resp.data[0].embedding
        except Exception as e:
            logger.debug("OpenAI embed failed: %s", e)
            return None

    @classmethod
    def is_available(cls) -> bool:
        return bool(
            os.environ.get("OPENAI_API_KEY") or
            os.environ.get("BRAIN_LLM_BASE_URL")
        )


class AnthropicEmbedder:
    """Anthropic voyage-3-lite — available with any Anthropic key."""

    MODEL = "voyage-3-lite"
    DIM   = 512

    def __init__(self):
        self.dim = self.DIM

    def embed(self, text: str) -> Optional[list[float]]:
        try:
            import anthropic
            client = anthropic.Anthropic(
                api_key=os.environ.get("ANTHROPIC_API_KEY", "")
            )
            # Use the embeddings endpoint if available
            # voyageai is a separate client; use voyage-3-lite via anthropic
            from anthropic import Anthropic
            # Actually voyage requires voyageai package:
            import voyageai
            vo = voyageai.Client(api_key=os.environ.get("VOYAGE_API_KEY", ""))
            result = vo.embed([text[:2000]], model=self.MODEL)
            return result.embeddings[0]
        except Exception as e:
            logger.debug("Anthropic/Voyage embed failed: %s", e)
            return None

    @classmethod
    def is_available(cls) -> bool:
        try:
            import voyageai
            return bool(os.environ.get("VOYAGE_API_KEY"))
        except ImportError:
            return False


class LocalTFIDFEmbedder:
    """
    Pure-Python TF-IDF embedder — zero external dependencies.

    Uses hash-based random projection to produce a fixed 256-dim vector.
    Quality is lower than neural embeddings but:
      - Works offline with no API key
      - Deterministic (same text → same vector)
      - Fast (<1ms per embed)
      - Captures keyword overlap reasonably well

    Disable with: BRAIN_EMBED_PROVIDER=none
    """

    MODEL = "local-tfidf-256"
    DIM   = 256

    def __init__(self):
        self.dim = self.DIM

    def embed(self, text: str) -> list[float]:
        # OPT-03: check module-level LRU cache first
        cache_key = hashlib.md5((text or "").encode()).hexdigest()
        if cache_key in _TFIDF_CACHE:
            _TFIDF_CACHE.move_to_end(cache_key)   # BUG-14: promote to MRU position
            return _TFIDF_CACHE[cache_key]

        import math, struct, re
        text = (text or "")[:4000].lower()
        # Tokenise: split on non-alphanumeric, keep CJK chars as unigrams
        tokens = re.findall(r"[\u4e00-\u9fff]|[a-z0-9_]{2,}", text)
        if not tokens:
            return [0.0] * self.DIM

        # Term frequency
        tf: dict[str, float] = {}
        for tok in tokens:
            tf[tok] = tf.get(tok, 0) + 1
        total = sum(tf.values())
        tf = {k: v / total for k, v in tf.items()}

        # Project each term into DIM dimensions via signed hash
        vec = [0.0] * self.DIM
        for term, weight in tf.items():
            # Two independent hash seeds → index + sign
            h1 = int(hashlib.md5((term + "\x00").encode()).hexdigest(), 16)
            h2 = int(hashlib.sha1((term + "\x01").encode()).hexdigest(), 16)
            idx  = h1 % self.DIM
            sign = 1.0 if h2 % 2 == 0 else -1.0
            vec[idx] += sign * weight

        # L2 normalise
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        result = [v / norm for v in vec]

        # BUG-14 fix: evict true LRU entry (first = least recently used)
        if len(_TFIDF_CACHE) >= _TFIDF_CACHE_MAX:
            _TFIDF_CACHE.popitem(last=False)
        _TFIDF_CACHE[cache_key] = result

        return result

    @classmethod
    def is_available(cls) -> bool:
        return True  # always available


def get_embedder():
    """
    Return the best available embedder.

    Priority: Ollama > OpenAI-compat > LocalTFIDF (zero-dep fallback)
    Set BRAIN_EMBED_PROVIDER=none to disable all embedding (pure FTS5).
    """
    provider = os.environ.get("BRAIN_EMBED_PROVIDER", "").lower()

    if provider == "none":
        logger.debug("Embedder disabled via BRAIN_EMBED_PROVIDER=none")
        return None

    if provider == "ollama" or (not provider and OllamaEmbedder.is_available()):
        e = OllamaEmbedder()
        vec = e.embed("test")
        if vec and len(vec) > 0:
            logger.info("Embedder: Ollama (%d dim)", len(vec))
            e.dim = len(vec)
            return e

    if provider == "openai" or (not provider and OpenAIEmbedder.is_available()):
        e = OpenAIEmbedder()
        logger.info("Embedder: OpenAI %s (%d dim)", e.MODEL, e.dim)
        return e

    if provider in ("local", "tfidf", "") :
        e = LocalTFIDFEmbedder()
        logger.info("Embedder: LocalTFIDF (%d dim, zero-dep fallback)", e.DIM)
        return e

    logger.debug("No embedder available — using FTS5 only")
    return None
