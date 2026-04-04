"""
project_brain/ann_index.py — PH3-05 ANN Vector Index

Optional sqlite-vec HNSW index for O(log N) vector search.
Falls back to pure-Python linear cosine scan when sqlite-vec is not installed.

Install sqlite-vec:  pip install sqlite-vec
"""

from __future__ import annotations

import logging
import math
import sqlite3
import struct
import time
from pathlib import Path
from typing import Union

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
#  LinearScanIndex — Pure-Python fallback, always available
# ══════════════════════════════════════════════════════════════

class LinearScanIndex:
    """
    純 Python 線性掃描索引 — 永遠可用，O(N) 搜尋。

    適合小型知識庫（< 1 000 節點），無需額外依賴。
    """

    def __init__(self, dim: int) -> None:
        self.dim     = dim
        self._entries: list[tuple[str, list[float]]] = []  # (node_id, vec)

    def add(self, node_id: str, vec: list[float]) -> None:
        """新增一個向量到索引"""
        self._entries.append((node_id, list(vec)))

    def search(
        self, query_vec: list[float], k: int = 10
    ) -> list[tuple[str, float]]:
        """
        線性餘弦相似度搜尋。

        Returns:
            [(node_id, score), ...] 依 score 降冪排列
        """
        if not self._entries:
            return []

        q_norm = _l2_norm(query_vec)
        results: list[tuple[str, float]] = []

        for node_id, vec in self._entries:
            score = _cosine(query_vec, vec, q_norm)
            results.append((node_id, score))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:k]

    def __len__(self) -> int:
        return len(self._entries)


# ══════════════════════════════════════════════════════════════
#  HNSWIndex — sqlite-vec HNSW index, O(log N) search
# ══════════════════════════════════════════════════════════════

class HNSWIndex:
    """
    sqlite-vec HNSW 向量索引 — O(log N) 搜尋，需要 sqlite-vec。

    安裝：pip install sqlite-vec
    """

    def __init__(self, dim: int, db_path: Path) -> None:
        """
        建立或開啟指定路徑的 ANN SQLite 資料庫。

        Args:
            dim:     向量維度
            db_path: SQLite 資料庫路徑（.brain/ann_index.db）
        """
        import sqlite_vec as _sv  # noqa: F401 — confirm availability

        self.dim     = dim
        self.db_path = db_path
        self._conn   = self._open_conn()
        self._init_table()

    def _open_conn(self) -> sqlite3.Connection:
        import sqlite_vec as _sv
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.enable_load_extension(True)
        _sv.load(conn)
        conn.enable_load_extension(False)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_table(self) -> None:
        self._conn.execute(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_nodes
            USING vec0(node_id TEXT, embedding FLOAT[{self.dim}])
            """
        )
        self._conn.commit()

    def add(self, node_id: str, vec: list[float]) -> None:
        """插入一個向量（node_id 已存在時 REPLACE）"""
        import sqlite_vec as _sv
        blob = _sv.serialize_float32(vec)
        self._conn.execute(
            "INSERT OR REPLACE INTO vec_nodes(node_id, embedding) VALUES (?, ?)",
            (node_id, blob),
        )
        self._conn.commit()

    def search(
        self, query_vec: list[float], k: int = 10
    ) -> list[tuple[str, float]]:
        """
        KNN 搜尋。

        Returns:
            [(node_id, distance), ...] 依 distance 升冪排列
            （距離越小 = 越相似；調用者視需要轉換為相似度）
        """
        import sqlite_vec as _sv
        blob = _sv.serialize_float32(query_vec)
        rows = self._conn.execute(
            """
            SELECT node_id, distance
            FROM   vec_nodes
            WHERE  embedding MATCH ?
              AND  k = ?
            ORDER  BY distance
            """,
            (blob, k),
        ).fetchall()
        # 回傳 (node_id, score) — 以 1 - distance 作為相似度估算
        return [(r["node_id"], 1.0 - float(r["distance"])) for r in rows]

    def rebuild(self) -> None:
        """重建索引（大量插入後可呼叫以優化查詢效率）"""
        try:
            self._conn.execute("DROP TABLE IF EXISTS vec_nodes")
            self._conn.commit()
            self._init_table()
            logger.info("ann_index: HNSW index rebuilt")
        except Exception as exc:
            logger.error("ann_index: rebuild failed: %s", exc)

    def __len__(self) -> int:
        try:
            row = self._conn.execute(
                "SELECT COUNT(*) AS cnt FROM vec_nodes"
            ).fetchone()
            return int(row["cnt"]) if row else 0
        except Exception:
            return 0

    @classmethod
    def is_available(cls) -> bool:
        """回傳 sqlite-vec 是否已安裝"""
        try:
            import sqlite_vec  # noqa: F401
            return True
        except ImportError:
            return False


# ══════════════════════════════════════════════════════════════
#  Factory
# ══════════════════════════════════════════════════════════════

def get_ann_index(
    dim: int, brain_dir: Path
) -> Union[LinearScanIndex, HNSWIndex]:
    """
    工廠函式：若 sqlite-vec 可用則回傳 HNSWIndex（持久化），
    否則回傳純 Python 的 LinearScanIndex（記憶體中）。

    Args:
        dim:       向量維度
        brain_dir: .brain/ 目錄路徑

    Returns:
        HNSWIndex 或 LinearScanIndex
    """
    if HNSWIndex.is_available():
        db_path = Path(brain_dir) / "ann_index.db"
        try:
            return HNSWIndex(dim, db_path)
        except Exception as exc:
            logger.warning(
                "ann_index: HNSWIndex 建立失敗，退回 LinearScanIndex: %s", exc
            )

    logger.info(
        "sqlite-vec not found — using linear scan (pip install sqlite-vec for HNSW)"
    )
    return LinearScanIndex(dim)


# ══════════════════════════════════════════════════════════════
#  build_index_from_graph
# ══════════════════════════════════════════════════════════════

def build_index_from_graph(
    graph,
    embedder,
    brain_dir: Path,
    batch_size: int = 100,
) -> dict:
    """
    從 KnowledgeGraph 中所有有 embedding 向量的節點建立（或重建）ANN 索引。

    Args:
        graph:      KnowledgeGraph 實例
        embedder:   實作 embed(text) -> list[float] 的嵌入器（可為 None）
        brain_dir:  .brain/ 目錄路徑
        batch_size: 每批處理節點數

    Returns:
        {"backend": "hnsw"|"linear", "indexed": N, "elapsed_ms": N}
    """
    t0      = time.monotonic()
    indexed = 0
    dim     = 0

    # 先確定向量維度（嘗試查 DB 或用 embedder 推測）
    try:
        # 嘗試從 graph 找一個 embedding 確定 dim
        sample = graph._conn.execute(
            "SELECT embedding FROM nodes WHERE embedding IS NOT NULL LIMIT 1"
        ).fetchone()
        if sample and sample[0]:
            blob = sample[0]
            # float32 = 4 bytes per element
            dim  = len(blob) // 4
    except Exception as _e:
        logger.debug("vector dim probe from db failed", exc_info=True)

    if dim == 0 and embedder is not None:
        try:
            test_vec = embedder.embed("test")
            dim = len(test_vec)
        except Exception as _e:
            logger.debug("vector dim probe from embedder failed", exc_info=True)

    if dim == 0:
        # 無法確定維度，預設 768
        dim = 768
        logger.warning("ann_index: 無法確定向量維度，使用預設值 %d", dim)

    index   = get_ann_index(dim, brain_dir)
    backend = "hnsw" if isinstance(index, HNSWIndex) else "linear"

    # 批次讀取並插入
    offset = 0
    while True:
        try:
            rows = graph._conn.execute(
                """
                SELECT id, title, content, embedding
                FROM   nodes
                WHERE  embedding IS NOT NULL
                LIMIT  ? OFFSET ?
                """,
                (batch_size, offset),
            ).fetchall()
        except Exception as exc:
            logger.error("build_index_from_graph: 查詢失敗: %s", exc)
            break

        if not rows:
            break

        for row in rows:
            node_id = row[0]
            blob    = row[3]

            if blob:
                try:
                    # 解序列化 float32 blob
                    n_floats = len(blob) // 4
                    vec      = list(struct.unpack(f"{n_floats}f", blob))
                    if len(vec) != dim:
                        continue
                    index.add(node_id, vec)
                    indexed += 1
                except Exception as _e:
                    logger.debug("ann_index add from stored vector failed", exc_info=True)
            elif embedder is not None:
                # 節點沒有預存 embedding，即時計算
                text = (row[1] or "") + " " + (row[2] or "")
                try:
                    vec = embedder.embed(text.strip())
                    if vec and len(vec) == dim:
                        index.add(node_id, vec)
                        indexed += 1
                except Exception as _e:
                    logger.debug("ann_index add from on-the-fly embed failed", exc_info=True)

        offset += batch_size

    elapsed_ms = int((time.monotonic() - t0) * 1_000)
    logger.info(
        "ann_index: built | backend=%s indexed=%d elapsed_ms=%d",
        backend, indexed, elapsed_ms,
    )
    return {"backend": backend, "indexed": indexed, "elapsed_ms": elapsed_ms}


# ══════════════════════════════════════════════════════════════
#  Private helpers
# ══════════════════════════════════════════════════════════════

def _l2_norm(vec: list[float]) -> float:
    """計算 L2 範數（zero-safe）"""
    s = sum(x * x for x in vec)
    return math.sqrt(s) if s > 0 else 0.0


def _cosine(a: list[float], b: list[float], a_norm: float = 0.0) -> float:
    """
    計算兩向量的餘弦相似度。

    零向量安全：任一向量為零時回傳 0.0。
    """
    if not a or not b:
        return 0.0
    if a_norm == 0.0:
        a_norm = _l2_norm(a)
    b_norm = _l2_norm(b)
    if a_norm == 0.0 or b_norm == 0.0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (a_norm * b_norm)
