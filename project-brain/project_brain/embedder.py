"""
project_brain/embedder.py — Phase 1 + PH3-06: Embedding Backend

Priority order:
  1. Multilingual (sentence-transformers, multilingual-e5-small → 384 dim)  [PH3-06]
  2. Ollama (local, free, nomic-embed-text → 768 dim; model configurable)
  3. OpenAI (API, text-embedding-3-small → 1536 dim)
  4. Anthropic voyage (if available)
  5. LocalTFIDF → zero-dep fallback

Environment variables:
  BRAIN_EMBED_PROVIDER      one of: multilingual | ollama | openai | local | none
  BRAIN_MULTILINGUAL_MODEL  sentence-transformers model name
                            (default: intfloat/multilingual-e5-small)
  BRAIN_EMBED_E5_PREFIX     "1" (default) adds "query:"/"passage:" prefix for e5
  BRAIN_OLLAMA_EMBED_MODEL  Ollama embedding model name
                            (default: nomic-embed-text)
                            multilingual alternative: mxbai-embed-large
  BRAIN_TFIDF_DIM           LocalTFIDF projection dimension (default: 256)

Usage:
    emb = get_embedder()
    if emb:
        vec = emb.embed("JWT 必須使用 RS256")  # list[float], 中英皆可
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
DIM_MULTILINGUAL = 384   # multilingual-e5-small
DIM_OLLAMA       = 768   # nomic-embed-text
DIM_OPENAI       = 1536  # text-embedding-3-small
DIM_DEFAULT      = 768

# Default model names
_DEFAULT_OLLAMA_EMBED_MODEL       = "nomic-embed-text"
_DEFAULT_MULTILINGUAL_MODEL       = "intfloat/multilingual-e5-small"


class MultilingualEmbedder:
    """
    Multilingual embedding via sentence-transformers (PH3-06).

    Supports mixed Chinese-English text in a single vector space.
    Uses multilingual-e5 prefix convention ("query: " / "passage: ")
    which significantly improves retrieval accuracy for e5 models.

    Install:  pip install sentence-transformers
    Models:
      intfloat/multilingual-e5-small  — 117M params, 384 dim, ~250 MB  (default)
      intfloat/multilingual-e5-base   — 278M params, 768 dim, ~550 MB
      intfloat/multilingual-e5-large  — 560M params, 1024 dim, ~2.2 GB

    Configure:
      BRAIN_MULTILINGUAL_MODEL=intfloat/multilingual-e5-base
      BRAIN_EMBED_E5_PREFIX=0   # disable prefix (for non-e5 models)
    """

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = (
            model_name
            or os.environ.get("BRAIN_MULTILINGUAL_MODEL", _DEFAULT_MULTILINGUAL_MODEL)
        )
        self._model = None   # lazy-loaded on first embed()
        self.dim    = DIM_MULTILINGUAL  # updated after first load

    # ── lazy load ────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # type: ignore
            self._model = SentenceTransformer(self.model_name)
            self.dim    = self._model.get_sentence_embedding_dimension()
            logger.info(
                "MultilingualEmbedder: loaded %s (%d dim)", self.model_name, self.dim
            )

    # ── public API ───────────────────────────────────────────────────

    def embed(self, text: str, is_query: bool = True) -> Optional[list[float]]:
        """
        Embed text. Automatically adds "query: " / "passage: " prefix for e5
        models unless BRAIN_EMBED_E5_PREFIX=0.

        Args:
            text:     Input text (Chinese / English / mixed).
            is_query: True = knowledge retrieval query, False = document to index.
        """
        try:
            self._load()
            use_prefix = os.environ.get("BRAIN_EMBED_E5_PREFIX", "1") != "0"
            if use_prefix and "e5" in self.model_name.lower():
                text = ("query: " if is_query else "passage: ") + text
            vec = self._model.encode(text[:4000], normalize_embeddings=True)
            return vec.tolist()
        except Exception as e:
            logger.debug("MultilingualEmbedder.embed failed: %s", e)
            return None

    @classmethod
    def is_available(cls) -> bool:
        try:
            import sentence_transformers  # type: ignore  # noqa: F401
            return True
        except ImportError:
            return False


class OllamaEmbedder:
    """
    Local embedding via Ollama — zero cost, zero privacy concern.

    Default model: nomic-embed-text (768 dim, English-centric).
    For multilingual Ollama embedding set:
      BRAIN_OLLAMA_EMBED_MODEL=mxbai-embed-large
    """

    DEFAULT_MODEL = _DEFAULT_OLLAMA_EMBED_MODEL

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model:    str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model    = model or os.environ.get(
            "BRAIN_OLLAMA_EMBED_MODEL", self.DEFAULT_MODEL
        )
        self.dim      = DIM_OLLAMA

    def embed(self, text: str, **_kwargs) -> Optional[list[float]]:
        try:
            import urllib.request, json
            payload = json.dumps({"model": self.model, "prompt": text[:2000]}).encode()
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

    Uses hash-based random projection to produce a fixed-dim vector.
    Dimension defaults to 256; override with BRAIN_TFIDF_DIM env var.
    Quality is lower than neural embeddings but:
      - Works offline with no API key
      - Deterministic (same text → same vector)
      - Fast (<1ms per embed)
      - Captures keyword overlap reasonably well

    Disable with: BRAIN_EMBED_PROVIDER=none
    """

    DIM   = int(os.environ.get("BRAIN_TFIDF_DIM", "256"))
    MODEL = f"local-tfidf-{DIM}"

    def __init__(self):
        self.dim = self.DIM

    def embed(self, text: str) -> list[float]:
        # OPT-03: check module-level LRU cache first; include DIM so a
        # dim change (via env var restart) never returns a wrong-size vector.
        cache_key = hashlib.md5(f"{self.DIM}:{text or ''}".encode()).hexdigest()
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

    Priority:
      1. multilingual  (sentence-transformers; BRAIN_EMBED_PROVIDER=multilingual)
      2. Ollama        (local; model configurable via BRAIN_OLLAMA_EMBED_MODEL)
      3. OpenAI-compat (OPENAI_API_KEY or BRAIN_LLM_BASE_URL)
      4. LocalTFIDF    (zero-dep fallback, always available)

    Set BRAIN_EMBED_PROVIDER=none to disable all embedding (pure FTS5 only).

    Multilingual notes:
      - pip install sentence-transformers   to enable MultilingualEmbedder
      - BRAIN_EMBED_PROVIDER=multilingual   to force-select it
      - BRAIN_MULTILINGUAL_MODEL=<hf-id>   to pick a specific model
      - For Ollama multilingual: set BRAIN_OLLAMA_EMBED_MODEL=mxbai-embed-large
    """
    provider = os.environ.get("BRAIN_EMBED_PROVIDER", "").lower()

    if provider == "none":
        logger.debug("Embedder disabled via BRAIN_EMBED_PROVIDER=none")
        return None

    # ── 1. Multilingual (sentence-transformers) ───────────────────
    if provider == "multilingual" or (not provider and MultilingualEmbedder.is_available()):
        e = MultilingualEmbedder()
        vec = e.embed("test", is_query=True)
        if vec and len(vec) > 0:
            logger.info(
                "Embedder: MultilingualEmbedder %s (%d dim)", e.model_name, len(vec)
            )
            e.dim = len(vec)
            return e
        if provider == "multilingual":
            logger.warning(
                "MultilingualEmbedder requested but unavailable — "
                "run: pip install sentence-transformers"
            )

    # ── 2. Ollama ────────────────────────────────────────────────
    if provider == "ollama" or (not provider and OllamaEmbedder.is_available()):
        e = OllamaEmbedder()
        vec = e.embed("test")
        if vec and len(vec) > 0:
            logger.info("Embedder: Ollama %s (%d dim)", e.model, len(vec))
            e.dim = len(vec)
            return e

    # ── 3. OpenAI-compatible ─────────────────────────────────────
    if provider == "openai" or (not provider and OpenAIEmbedder.is_available()):
        e = OpenAIEmbedder()
        logger.info("Embedder: OpenAI %s (%d dim)", e.MODEL, e.dim)
        return e

    # ── 4. LocalTFIDF (zero-dep fallback) ────────────────────────
    if provider in ("local", "tfidf", ""):
        e = LocalTFIDFEmbedder()
        logger.info("Embedder: LocalTFIDF (%d dim, zero-dep fallback)", e.DIM)
        return e

    logger.debug("No embedder available — using FTS5 only")
    return None
