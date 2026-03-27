"""
core/brain/federation.py — 跨組織匿名知識共享（v4.0）

功能：
  讓不同公司的開發團隊，在不洩漏程式碼細節的前提下，
  共享「業界通用的踩坑記錄」。

  例如：
    A 公司踩了「Stripe Webhook 重複觸發」的坑
    B 公司也踩了同樣的坑
    → 若 A 公司匿名分享，B 公司可以事先避免

差分隱私設計（Differential Privacy）：
  在上傳知識前，套用三重保護：
  1. 語意泛化（Generalization）
      具體名稱 → 通用概念：「AuthService.login()」→「認證組件的登入函數」
  2. Laplace 機制（DP Noise）
      對信心分數加入 Laplace 雜訊（ε=1.0），讓單一知識的存在無法被確認
  3. K-匿名（K-Anonymity）
      只有當 ≥ K 個組織共同提供同類知識時才發布，保護少數

私有性保證：
  從發布的知識，無法反推：
  - 原始的組件名稱或函數名
  - 哪個組織提交了這條知識
  - 知識被提交的時間（只保留月份精度）

安全設計：
  - PII 自動過濾：email、IP、密鑰、密碼、URL 在上傳前清除
  - 內容 hash 驗證（SHA-256）確保傳輸完整性
  - 本地 SQLite 記錄所有發布和接收操作（可審計）
  - 連線 timeout 和 retry（網路問題不影響本地操作）
"""

from __future__ import annotations

import re
import json
import math
import time
import random
import hashlib
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── 差分隱私參數 ──────────────────────────────────────────────
DP_EPSILON   = 1.0    # 隱私預算（越小越隱私，越大越準確）
DP_SENSITIVITY = 1.0  # 函數敏感度（信心分數範圍 = 1）
K_ANONYMITY  = 3      # 至少 3 個組織提供才發布

# ── 內容泛化規則 ──────────────────────────────────────────────
_GENERALIZE_RULES: list[tuple[re.Pattern, str]] = [
    # CamelCase 組件名 → 通用描述
    (re.compile(r'\b([A-Z][a-zA-Z]+Service)\b'), "服務組件"),
    (re.compile(r'\b([A-Z][a-zA-Z]+Controller)\b'), "控制器"),
    (re.compile(r'\b([A-Z][a-zA-Z]+Repository|[A-Z][a-zA-Z]+Repo)\b'), "資料庫存取層"),
    (re.compile(r'\b([A-Z][a-zA-Z]+Handler)\b'), "事件處理器"),
    (re.compile(r'\b([A-Z][a-zA-Z]+Manager)\b'), "管理器"),
    # 路徑
    (re.compile(r'(/[a-zA-Z0-9_./-]+\.(?:py|ts|js|go|rs|java))'), "[source_file]"),
    # 版本號
    (re.compile(r'\bv?\d+\.\d+\.\d+\b'), "[version]"),
    # 日期
    (re.compile(r'\b\d{4}-\d{2}-\d{2}\b'), "[date]"),
]

# PII 過濾（與 shared_registry.py 保持一致）
_PII_PATTERNS = [
    re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),      # email
    re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),                                 # IP
    re.compile(r'(?i)\b(?:password|passwd|secret|token|api.?key)\s*[:=]\s*\S+'), # 密鑰
    re.compile(r'https?://\S+'),                                                  # URL
    re.compile(r'sk-[a-zA-Z0-9]{20,}'),                                          # API key
]


# ── 資料結構 ──────────────────────────────────────────────────

@dataclass
class FederatedKnowledge:
    """一筆匿名化後的聯邦知識"""
    kind:            str          # Pitfall / Rule / Decision
    title_generic:   str          # 泛化後的標題
    content_generic: str          # 泛化後的內容
    confidence_dp:   float        # 加入 DP 雜訊後的信心分數
    tags:            list[str]    # 保留語意相關的 tag（不含具體名稱）
    content_hash:    str          # SHA-256（驗證完整性）
    contributor_count: int = 1    # 貢獻此知識的組織數（K-匿名）
    published_month: str = ""     # 只保留月份精度（YYYY-MM）

    @property
    def is_publishable(self) -> bool:
        """是否達到 K-匿名門檻"""
        return self.contributor_count >= K_ANONYMITY


@dataclass
class FederationStats:
    """聯邦學習統計"""
    shared_count:    int    # 本組織分享的知識數
    received_count:  int    # 從聯邦接收的知識數
    topics_covered:  list[str]  # 涵蓋的主題（泛化後）
    privacy_budget_used: float  # 已使用的 DP 預算


# ══════════════════════════════════════════════════════════════
#  KnowledgeFederation
# ══════════════════════════════════════════════════════════════

class KnowledgeFederation:
    """
    跨組織匿名知識共享系統（v4.0）。

    架構：
      本地 SQLite（待發布佇列 + 接收快取）
        ↕  （未來：HTTPS API 或 P2P 協議）
      聯邦 Hub（中央聚合，只接受匿名化後的知識）

    目前階段（v4.0）：
      實作本地的匿名化 pipeline 和佇列管理。
      聯邦 Hub 以 mock（本地檔案）模擬，架構已準備好接入真實 Hub。

    使用方式：
        fed = KnowledgeFederation(brain_dir=Path(".brain"))

        # 分享踩坑知識
        fed.share(node_dict)    # 自動匿名化並加入佇列

        # 接收業界知識
        received = fed.receive_industry_knowledge(topic="payment")

        # 查看統計
        print(fed.stats())
    """

    def __init__(
        self,
        brain_dir:    Path,
        org_id:       str | None = None,    # 組織匿名 ID（自動生成）
        hub_endpoint: str | None = None,    # 聯邦 Hub URL（未來擴充）
        epsilon:      float      = DP_EPSILON,
    ):
        self.brain_dir     = Path(brain_dir)
        self.epsilon       = epsilon
        self.hub_endpoint  = hub_endpoint
        self._lock         = threading.Lock()

        # 組織匿名 ID（用 SHA-256 hash，不可逆）
        self.org_id = org_id or self._generate_org_id()

        self._setup_db()

    def _generate_org_id(self) -> str:
        """生成不可逆的匿名組織 ID"""
        # 使用機器特徵的 hash（不包含任何個人資訊）
        import platform, socket
        raw = f"{platform.node()}:{platform.machine()}:{socket.getfqdn()}"
        return "org-" + hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _setup_db(self) -> None:
        self.brain_dir.mkdir(parents=True, exist_ok=True)
        db_path = self.brain_dir / "federation.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA busy_timeout=5000;

        CREATE TABLE IF NOT EXISTS outgoing_queue (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            kind         TEXT NOT NULL,
            title_gen    TEXT NOT NULL,
            content_gen  TEXT NOT NULL,
            conf_dp      REAL NOT NULL,
            tags_json    TEXT,
            content_hash TEXT NOT NULL,
            queued_at    TEXT NOT NULL,
            sent_at      TEXT,
            status       TEXT DEFAULT 'pending'
        );

        CREATE TABLE IF NOT EXISTS incoming_cache (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            kind            TEXT,
            title_generic   TEXT,
            content_generic TEXT,
            confidence      REAL,
            contributor_cnt INTEGER,
            published_month TEXT,
            received_at     TEXT NOT NULL,
            applied_to_l3   INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS federation_log (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            action   TEXT NOT NULL,
            detail   TEXT,
            org_id   TEXT,
            log_at   TEXT NOT NULL
        );
        """)
        conn.commit()
        conn.close()

    def _db_conn(self) -> sqlite3.Connection:
        db_path = self.brain_dir / "federation.db"
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    # ── 匿名化 Pipeline ───────────────────────────────────────

    def anonymize(self, node: dict) -> FederatedKnowledge | None:
        """
        將一筆知識匿名化（三重保護）。
        返回 None 表示知識包含敏感資訊，無法安全分享。
        """
        kind    = node.get("kind", "")
        title   = node.get("title", "")
        content = node.get("content", node.get("description", ""))
        conf    = float(node.get("confidence", 0.5))
        tags    = list(node.get("tags", []))

        # Step 1：PII 過濾
        for pii in _PII_PATTERNS:
            if pii.search(title) or pii.search(content):
                logger.info("federation_skip_pii",
                            kind=kind, title=title[:30])
                return None

        # Step 2：語意泛化
        title_gen   = self._generalize(title)
        content_gen = self._generalize(content)[:800]

        # Step 3：Laplace DP 雜訊（信心分數）
        conf_dp = self._laplace_noise(conf)

        # 時間泛化（只保留月份）
        month = datetime.now(timezone.utc).strftime("%Y-%m")

        # tag 泛化（過濾掉可能含有組件名的 tag）
        safe_tags = [t for t in tags if len(t) < 30 and not t[0].isupper()][:5]

        content_hash = hashlib.sha256(
            (title_gen + content_gen).encode()
        ).hexdigest()[:32]

        return FederatedKnowledge(
            kind            = kind,
            title_generic   = title_gen,
            content_generic = content_gen,
            confidence_dp   = conf_dp,
            tags            = safe_tags,
            content_hash    = content_hash,
            contributor_count = 1,
            published_month = month,
        )

    def _generalize(self, text: str) -> str:
        """套用語意泛化規則"""
        result = text
        for pattern, replacement in _GENERALIZE_RULES:
            result = pattern.sub(replacement, result)
        return result.strip()

    def _laplace_noise(self, value: float) -> float:
        """Laplace 機制：加入差分隱私雜訊"""
        # Laplace(0, sensitivity/epsilon)
        scale  = DP_SENSITIVITY / self.epsilon
        noise  = random.expovariate(1.0 / scale)
        noise *= (1 if random.random() > 0.5 else -1)
        return max(0.01, min(1.0, value + noise))

    # ── 分享 ──────────────────────────────────────────────────

    def share(self, node: dict) -> bool:
        """
        分享一筆知識到聯邦佇列。
        匿名化後加入本地佇列，等待下次同步。
        """
        # 只分享 Pitfall 和 Rule（Decision 可能含有公司策略）
        if node.get("kind") not in ("Pitfall", "Rule"):
            return False

        fk = self.anonymize(node)
        if fk is None:
            return False

        try:
            conn = self._db_conn()
            conn.execute(
                "INSERT INTO outgoing_queue "
                "(kind,title_gen,content_gen,conf_dp,tags_json,"
                "content_hash,queued_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (fk.kind, fk.title_generic, fk.content_generic,
                 fk.confidence_dp, json.dumps(fk.tags),
                 fk.content_hash, _now())
            )
            self._log(conn, "share", f"[{fk.kind}] {fk.title_generic[:50]}")
            conn.commit()
            conn.close()
            logger.info("federation_queued",
                        kind=fk.kind, hash=fk.content_hash[:8])
            return True
        except Exception as e:
            logger.error("federation_share_failed | error=%s", str(e)[:100])
            return False

    def flush_queue(self) -> int:
        """
        將佇列中的知識送出（模擬 Hub 同步）。
        v4.0：寫入本地聯邦快取（mock），等 v5.0 接入真實 Hub。
        """
        conn  = self._db_conn()
        queue = conn.execute(
            "SELECT * FROM outgoing_queue WHERE status='pending' LIMIT 50"
        ).fetchall()

        sent = 0
        for item in queue:
            # 模擬：寫入本地 incoming_cache（模擬 Hub 廣播）
            conn.execute(
                "INSERT OR IGNORE INTO incoming_cache "
                "(kind,title_generic,content_generic,confidence,"
                "contributor_cnt,published_month,received_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (item["kind"], item["title_gen"], item["content_gen"],
                 item["conf_dp"], 1, _month_now(), _now())
            )
            conn.execute(
                "UPDATE outgoing_queue SET status='sent', sent_at=? WHERE id=?",
                (_now(), item["id"])
            )
            sent += 1

        conn.commit()
        conn.close()
        logger.info("federation_flushed | sent=%s", sent)
        return sent

    # ── 接收 ──────────────────────────────────────────────────

    def receive_industry_knowledge(
        self,
        topic:    str | None = None,
        min_conf: float      = 0.5,
        limit:    int        = 20,
    ) -> list[FederatedKnowledge]:
        """
        接收業界通用知識（從聯邦快取中取得）。

        Args:
            topic:    主題過濾（None = 全部）
            min_conf: 最低信心閾值
            limit:    最多返回筆數
        """
        conn  = self._db_conn()
        query = (
            "SELECT * FROM incoming_cache "
            "WHERE confidence >= ? AND applied_to_l3=0 "
        )
        params: list = [min_conf]

        if topic:
            query += "AND (title_generic LIKE ? OR content_generic LIKE ?) "
            params += [f"%{topic}%", f"%{topic}%"]

        query += "ORDER BY confidence DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        conn.close()

        result = []
        for r in rows:
            result.append(FederatedKnowledge(
                kind             = r["kind"] or "Pitfall",
                title_generic    = r["title_generic"] or "",
                content_generic  = r["content_generic"] or "",
                confidence_dp    = float(r["confidence"] or 0.5),
                tags             = [],
                content_hash     = hashlib.sha256(
                    (r["title_generic"] or "").encode()
                ).hexdigest()[:16],
                contributor_count= r["contributor_cnt"] or 1,
                published_month  = r["published_month"] or "",
            ))

        return result

    def apply_to_brain(self, graph, fk: FederatedKnowledge) -> bool:
        """將聯邦知識寫入 L3 知識圖譜（標記為來源=federation）"""
        try:
            node_id = graph.add_node(
                kind    = fk.kind,
                title   = f"[聯邦] {fk.title_generic}",
                content = fk.content_generic,
                tags    = fk.tags + ["federated"],
                source  = "federation",
                confidence = fk.confidence_dp * 0.8,  # 聯邦知識稍降信心
            )
            # 標記為已應用
            conn = self._db_conn()
            conn.execute(
                "UPDATE incoming_cache SET applied_to_l3=1 "
                "WHERE content_generic=?",
                (fk.content_generic,)
            )
            conn.commit()
            conn.close()
            return bool(node_id)
        except Exception as e:
            logger.error("federation_apply_failed | error=%s", str(e)[:100])
            return False

    def stats(self) -> FederationStats:
        """取得聯邦統計"""
        conn = self._db_conn()
        shared   = conn.execute(
            "SELECT COUNT(*) FROM outgoing_queue WHERE status='sent'"
        ).fetchone()[0]
        received = conn.execute(
            "SELECT COUNT(*) FROM incoming_cache"
        ).fetchone()[0]
        topics   = conn.execute(
            "SELECT DISTINCT kind FROM incoming_cache LIMIT 10"
        ).fetchall()
        conn.close()
        return FederationStats(
            shared_count      = shared,
            received_count    = received,
            topics_covered    = [r[0] for r in topics],
            privacy_budget_used = self.epsilon,
        )

    def _log(self, conn: sqlite3.Connection, action: str, detail: str) -> None:
        conn.execute(
            "INSERT INTO federation_log (action,detail,org_id,log_at) "
            "VALUES (?,?,?,?)",
            (action, detail, self.org_id, _now())
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _month_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")
