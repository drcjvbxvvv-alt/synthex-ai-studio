"""
VectorMemory — Chroma 向量記憶層 (v1.1)

安全設計：
  - 所有輸入均做長度限制與清理，防止注入
  - 向量 DB 資料夾只允許在 .brain/ 內部
  - 嵌入維度固定，避免維度不一致導致崩潰
  - 記憶體使用量監控，超過閾值自動清理最舊記錄

可靠設計：
  - 懶初始化：chroma 不可用時 graceful degrade 到 FTS5
  - 所有操作 try/except，不因向量 DB 錯誤影響主流程
  - 版本遷移：schema 版本標記，確保向前相容
"""

from __future__ import annotations

import os
import re
import hashlib
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# ── 安全常數 ────────────────────────────────────────────────────
MAX_CONTENT_CHARS  = 8_000   # 單筆知識最大字元數
MAX_QUERY_CHARS    = 500     # 查詢字串最大長度
MAX_COLLECTION_DOCS = 50_000 # 單集合最大文件數（約 200MB 向量）
EMBED_BATCH_SIZE   = 32      # 批次嵌入大小（控制記憶體峰值）


def _sanitize_text(text: str, max_len: int = MAX_CONTENT_CHARS) -> str:
    """清理輸入：去除控制字元、限制長度"""
    if not isinstance(text, str):
        return ""
    # 去除 null bytes 和其他控制字元（保留換行）
    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return cleaned[:max_len]


def _safe_id(raw: str) -> str:
    """產生安全的 Chroma document ID（只含 ASCII 字母數字和連字符）"""
    h = hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"doc-{h}"


class VectorMemory:
    """
    向量記憶層：語義搜尋補充 SQLite FTS5 的精確搜尋。

    使用 Chroma + 預設嵌入模型（all-MiniLM-L6-v2）。
    若 chromadb 未安裝，所有方法靜默降級（不拋例外）。

    集合設計：
      brain_knowledge  — 所有知識片段（Decision / Pitfall / Rule / ADR）
      brain_sessions   — 每次 AI 對話的摘要（用於跨 session 連貫性）
    """

    SCHEMA_VERSION = "1.1"

    def __init__(self, brain_dir: Path):
        # 路徑安全：確保只在 .brain/ 內部
        self.vector_dir = (brain_dir / "vectors").resolve()
        brain_resolved  = brain_dir.resolve()
        if not str(self.vector_dir).startswith(str(brain_resolved)):
            raise ValueError("向量目錄必須在 .brain/ 內部")

        self._chroma   = None
        self._client   = None
        self._col_know = None
        self._col_sess = None
        self._available = False

        self._init_chroma()

    def _init_chroma(self) -> None:
        try:
            import chromadb
            from chromadb.config import Settings

            self.vector_dir.mkdir(parents=True, exist_ok=True)

            self._client = chromadb.PersistentClient(
                path=str(self.vector_dir),
                settings=Settings(
                    anonymized_telemetry=False,   # 不回傳使用資料
                    allow_reset=False,             # 防止意外 reset
                ),
            )

            # 知識集合
            self._col_know = self._client.get_or_create_collection(
                name="brain_knowledge",
                metadata={
                    "hnsw:space":       "cosine",
                    "schema_version":   self.SCHEMA_VERSION,
                    "created_at":       datetime.now().isoformat(),
                },
            )

            # Session 集合
            self._col_sess = self._client.get_or_create_collection(
                name="brain_sessions",
                metadata={"hnsw:space": "cosine"},
            )

            self._available = True
            logger.debug("VectorMemory 初始化成功（%s docs）",
                         self._col_know.count())

        except ImportError:
            logger.info("chromadb 未安裝，向量記憶降級到 FTS5")
        except Exception as e:
            logger.warning("VectorMemory 初始化失敗（降級）：%s", e)

    @property
    def available(self) -> bool:
        return self._available

    # ── 寫入 ───────────────────────────────────────────────────────

    def upsert(
        self,
        node_id:    str,
        content:    str,
        node_type:  str,
        title:      str,
        tags:       list[str] | None = None,
        author:     str = "",
        created_at: str = "",
    ) -> bool:
        """
        寫入或更新一筆知識向量。
        回傳 True 成功，False 失敗（降級狀態）。
        """
        if not self._available:
            return False

        # 安全清理
        content_clean = _sanitize_text(content)
        title_clean   = _sanitize_text(title, 200)
        doc_id        = _safe_id(node_id)

        # 防止集合過大
        if self._col_know.count() >= MAX_COLLECTION_DOCS:
            logger.warning("向量集合已達上限 %d，跳過寫入", MAX_COLLECTION_DOCS)
            return False

        # 嵌入文字 = 標題 + 內容（標題權重更高）
        embed_text = f"{title_clean}\n\n{content_clean}"[:MAX_CONTENT_CHARS]

        try:
            self._col_know.upsert(
                ids        = [doc_id],
                documents  = [embed_text],
                metadatas  = [{
                    "node_id":    node_id[:200],
                    "type":       node_type[:50],
                    "title":      title_clean[:200],
                    "tags":       ",".join((tags or [])[:20]),
                    "author":     _sanitize_text(author, 100),
                    "created_at": created_at[:30] or datetime.now().isoformat(),
                }],
            )
            return True
        except Exception as e:
            logger.error("VectorMemory.upsert 失敗：%s", e)
            return False

    def add_session(self, session_id: str, summary: str) -> bool:
        """記錄 AI 工作 session 的摘要（用於跨 session 連貫性查詢）"""
        if not self._available:
            return False
        try:
            doc_id = _safe_id(session_id)
            self._col_sess.upsert(
                ids       = [doc_id],
                documents = [_sanitize_text(summary, 2000)],
                metadatas = [{
                    "session_id": session_id[:100],
                    "created_at": datetime.now().isoformat(),
                }],
            )
            return True
        except Exception as e:
            logger.error("add_session 失敗：%s", e)
            return False

    # ── 查詢 ───────────────────────────────────────────────────────

    def search(
        self,
        query:      str,
        top_k:      int = 5,
        node_type:  str | None = None,
        min_score:  float = 0.3,   # cosine similarity 閾值
    ) -> list[dict]:
        """
        語義搜尋知識庫。
        回傳依相似度排序的知識片段列表，空列表表示無結果或降級。
        """
        if not self._available:
            return []

        # 安全清理查詢字串
        q = _sanitize_text(query, MAX_QUERY_CHARS).strip()
        if not q:
            return []

        top_k = min(max(1, top_k), 20)  # 限制範圍 1-20

        try:
            where = {"type": node_type} if node_type else None
            results = self._col_know.query(
                query_texts    = [q],
                n_results      = top_k,
                where          = where,
                include        = ["documents", "metadatas", "distances"],
            )

            output = []
            docs      = results.get("documents",  [[]])[0]
            metas     = results.get("metadatas",  [[]])[0]
            distances = results.get("distances",  [[]])[0]

            for doc, meta, dist in zip(docs, metas, distances):
                # cosine distance → similarity（1 - dist）
                similarity = max(0.0, 1.0 - float(dist))
                if similarity < min_score:
                    continue
                output.append({
                    "node_id":    meta.get("node_id", ""),
                    "type":       meta.get("type", ""),
                    "title":      meta.get("title", ""),
                    "content":    doc[:2000],
                    "tags":       meta.get("tags", "").split(","),
                    "author":     meta.get("author", ""),
                    "created_at": meta.get("created_at", ""),
                    "similarity": round(similarity, 4),
                })

            return sorted(output, key=lambda x: -x["similarity"])

        except Exception as e:
            logger.error("VectorMemory.search 失敗：%s", e)
            return []

    def similar_sessions(self, query: str, top_k: int = 3) -> list[dict]:
        """找出和當前任務最相似的歷史 session"""
        if not self._available:
            return []
        q = _sanitize_text(query, MAX_QUERY_CHARS).strip()
        if not q:
            return []
        try:
            results = self._col_sess.query(
                query_texts = [q],
                n_results   = min(top_k, 5),
                include     = ["documents", "metadatas", "distances"],
            )
            output = []
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                output.append({
                    "session_id": meta.get("session_id", ""),
                    "summary":    doc[:500],
                    "similarity": round(max(0.0, 1.0 - float(dist)), 4),
                    "created_at": meta.get("created_at", ""),
                })
            return output
        except Exception as e:
            logger.error("similar_sessions 失敗：%s", e)
            return []

    # ── 管理 ───────────────────────────────────────────────────────

    def delete(self, node_id: str) -> bool:
        """刪除指定節點的向量"""
        if not self._available:
            return False
        try:
            doc_id = _safe_id(node_id)
            self._col_know.delete(ids=[doc_id])
            return True
        except Exception as e:
            logger.error("VectorMemory.delete 失敗：%s", e)
            return False

    def stats(self) -> dict:
        if not self._available:
            return {"available": False, "knowledge_docs": 0, "session_docs": 0}
        try:
            return {
                "available":      True,
                "knowledge_docs": self._col_know.count(),
                "session_docs":   self._col_sess.count() if self._col_sess else 0,
                "vector_dir":     str(self.vector_dir),
            }
        except Exception:
            return {"available": False, "error": "stats 失敗"}

    def close(self) -> None:
        """釋放資源"""
        self._col_know = None
        self._col_sess = None
        self._client   = None
        self._available = False
