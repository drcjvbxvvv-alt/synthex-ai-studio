"""
project_brain/krb_ai_assist.py — PH3-03 AI-Assisted KRB Review

由 Claude Haiku 預篩 KRB staging 中的待審知識，降低人工審查負擔。

三速道分流：
  快速道  (approve)  — AI 信心 ≥ auto_approve_threshold（預設：關閉）
  人工道  (review)   — 信心介中，或 kind=Pitfall（永遠走此道）
  丟棄道  (reject)   — AI 信心 ≥ auto_reject_threshold 且建議拒絕（預設：關閉）

設計原則：
  - kind=Pitfall 永遠路由到人工道（不自動核准，Pitfall 錯標代價高）
  - auto_approve / auto_reject 預設關閉（需顯式傳入閾值）
  - 5 條/次 API 批次呼叫（降低成本）
  - Prompt Injection 防護（同 knowledge_validator.py）
  - 每個 AI 決策記錄到 knowledge_history（可審計）
  - 24 小時快取：已預篩的節點不重複呼叫

成本估算：
  50 條待審 / 5 條每呼叫 = 10 次 Haiku → ~$0.002
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── 常數 ──────────────────────────────────────────────────────────
MAX_ITEMS_PER_CALL  = 5       # 每次 API 呼叫處理的節點數
MAX_CONTENT_PROMPT  = 400     # 單條知識送入 Prompt 的最大字元
CACHE_HOURS         = 24      # 相同節點不在 24 小時內重複預篩
DEFAULT_MODEL       = "claude-haiku-4-5-20251001"

# Prompt Injection 防護（同 knowledge_validator.py）
_INJECTION_PATTERNS = re.compile(
    r"\b(ignore|forget|override|disregard|pretend|jailbreak|"
    r"act as|new instruction|system:|<\|im_start\|>)\b",
    re.IGNORECASE,
)

# ── 結果資料結構 ──────────────────────────────────────────────────

class AIScreenResult:
    """單筆知識的 AI 預篩結果"""

    __slots__ = ("staged_id", "recommendation", "confidence", "reason")

    def __init__(
        self,
        staged_id:      str,
        recommendation: str,    # "approve" | "review" | "reject"
        confidence:     float,
        reason:         str,
    ):
        self.staged_id      = staged_id
        self.recommendation = recommendation
        self.confidence     = max(0.0, min(1.0, confidence))
        self.reason         = reason[:120]

    def lane_icon(self) -> str:
        return {"approve": "✅", "review": "⚠️ ", "reject": "❌"}.get(
            self.recommendation, "❓"
        )

    def __repr__(self) -> str:
        return (f"AIScreenResult({self.staged_id[:8]} "
                f"{self.recommendation} {self.confidence:.2f})")


# ══════════════════════════════════════════════════════════════════
#  KRBAIAssistant
# ══════════════════════════════════════════════════════════════════

class KRBAIAssistant:
    """
    AI 輔助 KRB 預篩系統（PH3-03）。

    使用方式：
        from project_brain.review_board import KnowledgeReviewBoard
        from project_brain.graph import KnowledgeGraph
        from project_brain.krb_ai_assist import KRBAIAssistant
        import anthropic

        graph  = KnowledgeGraph(brain_dir)
        krb    = KnowledgeReviewBoard(brain_dir, graph)
        client = anthropic.Anthropic()
        assist = KRBAIAssistant(krb, client)

        summary = assist.pre_screen(
            limit              = 50,
            auto_approve_threshold = None,   # 關閉自動核准
            auto_reject_threshold  = None,   # 關閉自動拒絕
        )
        print(summary)
    """

    def __init__(
        self,
        krb,                               # KnowledgeReviewBoard 實例
        client,                            # anthropic.Anthropic 實例
        model: str = DEFAULT_MODEL,
    ):
        self.krb    = krb
        self.client = client
        self.model  = model
        self._brain_dir: Path = Path(krb.brain_dir)
        self._cache_db  = self._brain_dir / "krb_ai_cache.db"
        self._setup_cache()

    # ── 主入口 ────────────────────────────────────────────────────

    def pre_screen(
        self,
        limit:                   int   = 50,
        auto_approve_threshold:  Optional[float] = None,
        auto_reject_threshold:   Optional[float] = None,
        max_api_calls:           int   = 20,
    ) -> dict:
        """
        預篩所有 pending 節點。

        Args:
            limit:                   最多處理幾條待審節點
            auto_approve_threshold:  信心 ≥ 此值時自動核准（None = 關閉）
            auto_reject_threshold:   信心 ≥ 此值且建議 reject 時自動拒絕（None = 關閉）
            max_api_calls:           最大 API 呼叫次數（成本保護）

        Returns:
            {
                "total":          已處理數,
                "approve_lane":   快速道數,
                "review_lane":    人工道數,
                "reject_lane":    丟棄道數,
                "auto_approved":  自動核准數,
                "auto_rejected":  自動拒絕數,
                "api_calls_used": API 呼叫次數,
                "results":        list[AIScreenResult],
            }
        """
        pending = self.krb.list_pending(limit=limit)
        if not pending:
            return self._empty_summary()

        # 過濾掉 24 小時內已預篩的
        to_screen = [n for n in pending if not self._is_cached(n.id)]
        if not to_screen:
            return self._empty_summary()

        results: list[AIScreenResult] = []
        api_calls = 0

        # 批次呼叫（每次 MAX_ITEMS_PER_CALL 條）
        for i in range(0, len(to_screen), MAX_ITEMS_PER_CALL):
            if api_calls >= max_api_calls:
                logger.warning("krb_ai_assist: max_api_calls (%d) reached", max_api_calls)
                break
            batch = to_screen[i : i + MAX_ITEMS_PER_CALL]
            batch_results = self._screen_batch(batch)
            results.extend(batch_results)
            api_calls += 1

        # 寫回 staged_nodes + 執行自動決策
        auto_approved = auto_rejected = 0
        for r in results:
            self._write_ai_result(r)
            self._cache_result(r.staged_id)

            if r.recommendation == "approve" and auto_approve_threshold is not None:
                if r.confidence >= auto_approve_threshold and self._safe_to_auto(r.staged_id):
                    ok = self.krb.approve(r.staged_id, reviewer="ai-assist",
                                          note=f"[AI auto-approve {r.confidence:.2f}] {r.reason}")
                    if ok:
                        auto_approved += 1
                        self._record_history(r, action="ai_auto_approved")

            elif r.recommendation == "reject" and auto_reject_threshold is not None:
                if r.confidence >= auto_reject_threshold:
                    ok = self.krb.reject(r.staged_id, reviewer="ai-assist",
                                         reason=f"[AI auto-reject {r.confidence:.2f}] {r.reason}")
                    if ok:
                        auto_rejected += 1
                        self._record_history(r, action="ai_auto_rejected")
            else:
                self._record_history(r, action="ai_screened")

        approve_lane = sum(1 for r in results if r.recommendation == "approve")
        review_lane  = sum(1 for r in results if r.recommendation == "review")
        reject_lane  = sum(1 for r in results if r.recommendation == "reject")

        return {
            "total":          len(results),
            "approve_lane":   approve_lane,
            "review_lane":    review_lane,
            "reject_lane":    reject_lane,
            "auto_approved":  auto_approved,
            "auto_rejected":  auto_rejected,
            "api_calls_used": api_calls,
            "results":        results,
        }

    # ── 批次呼叫 ─────────────────────────────────────────────────

    def _screen_batch(self, nodes: list) -> list[AIScreenResult]:
        """對一批 StagedNode 發送一次 API 呼叫，回傳 AIScreenResult 列表"""
        items = []
        for n in nodes:
            safe_title   = _clean(n.title)
            safe_content = _clean(n.content)[:MAX_CONTENT_PROMPT]
            items.append({
                "id":      n.id,
                "kind":    n.kind,
                "title":   safe_title,
                "content": safe_content,
            })

        prompt = _build_prompt(items)
        try:
            resp = self.client.messages.create(
                model      = self.model,
                max_tokens = 512,
                messages   = [{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
            raw = re.sub(r"```(?:json)?|```", "", raw).strip()
            data: list[dict] = json.loads(raw)

            id_to_node = {n.id: n for n in nodes}
            results = []
            for item in data:
                sid  = str(item.get("id", ""))
                node = id_to_node.get(sid)
                if node is None:
                    continue
                rec  = str(item.get("recommendation", "review"))
                conf = float(item.get("confidence", 0.5))
                rsn  = str(item.get("reason", ""))

                # Safety: Pitfall 永遠走人工道
                if node.kind == "Pitfall" and rec == "approve":
                    rec  = "review"
                    rsn  = f"[Pitfall 安全規則] {rsn}"
                    conf = min(conf, 0.89)

                results.append(AIScreenResult(
                    staged_id      = sid,
                    recommendation = rec if rec in ("approve", "review", "reject") else "review",
                    confidence     = conf,
                    reason         = rsn,
                ))
            return results

        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.warning("krb_ai_assist: JSON parse failed: %s", e)
        except Exception as e:
            logger.error("krb_ai_assist: API call failed: %s", e)

        # Fallback：全部標記為 review
        return [
            AIScreenResult(staged_id=n.id, recommendation="review",
                           confidence=0.5, reason="AI 呼叫失敗，需人工審查")
            for n in nodes
        ]

    # ── 安全護欄 ─────────────────────────────────────────────────

    def _safe_to_auto(self, staged_id: str) -> bool:
        """
        額外安全檢查：auto-approve 只在以下條件全部通過時執行：
          - kind != Pitfall（已在 _screen_batch 防護，此處雙重確認）
          - 非空白 content
        """
        try:
            row = self.krb._get_staged(staged_id)
            if not row:
                return False
            if row["kind"] == "Pitfall":
                return False
            if not (row["content"] or "").strip():
                return False
            return True
        except Exception:
            return False

    # ── 資料寫回 ─────────────────────────────────────────────────

    def _write_ai_result(self, r: AIScreenResult) -> None:
        """將 AI 預篩結果寫回 staged_nodes 的 ai_* 欄位"""
        try:
            now = datetime.now(timezone.utc).isoformat()
            self.krb._conn_().execute("""
                UPDATE staged_nodes
                SET ai_recommendation=?, ai_confidence=?,
                    ai_reasoning=?, ai_screened_at=?
                WHERE id=?
            """, (r.recommendation, r.confidence, r.reason, now, r.staged_id))
            self.krb._conn_().commit()
        except Exception as e:
            logger.error("krb_ai_assist: write_ai_result failed: %s", e)

    def _record_history(self, r: AIScreenResult, action: str) -> None:
        """在 knowledge_history 記錄 AI 審計軌跡（不影響主流程）"""
        try:
            now = datetime.now(timezone.utc).isoformat()
            self.krb._conn_().execute("""
                INSERT INTO knowledge_history
                    (l3_node_id, staged_id, action, title, content, reviewer, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, ("", r.staged_id, action, "", "",
                  f"ai-assist({self.model})",
                  f"{r.recommendation} conf={r.confidence:.2f}: {r.reason}", now))
            self.krb._conn_().commit()
        except Exception as e:
            logger.debug("krb_ai_assist: history write failed: %s", e)

    # ── 快取 ─────────────────────────────────────────────────────

    def _setup_cache(self) -> None:
        try:
            conn = sqlite3.connect(str(self._cache_db))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_screen_cache (
                    staged_id  TEXT PRIMARY KEY,
                    screened_at TEXT NOT NULL,
                    expires_at  TEXT NOT NULL
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug("krb_ai_assist: cache setup failed: %s", e)

    def _is_cached(self, staged_id: str) -> bool:
        try:
            conn = sqlite3.connect(str(self._cache_db))
            row = conn.execute(
                "SELECT expires_at FROM ai_screen_cache WHERE staged_id=?",
                (staged_id,)
            ).fetchone()
            conn.close()
            if row:
                expires = datetime.fromisoformat(row[0])
                if datetime.now(timezone.utc) < expires:
                    return True
        except Exception:
            pass
        return False

    def _cache_result(self, staged_id: str) -> None:
        try:
            now     = datetime.now(timezone.utc)
            expires = (now + timedelta(hours=CACHE_HOURS)).isoformat()
            conn    = sqlite3.connect(str(self._cache_db))
            conn.execute(
                "INSERT OR REPLACE INTO ai_screen_cache (staged_id, screened_at, expires_at) "
                "VALUES (?, ?, ?)",
                (staged_id, now.isoformat(), expires)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug("krb_ai_assist: cache write failed: %s", e)

    # ── 輔助 ─────────────────────────────────────────────────────

    @staticmethod
    def _empty_summary() -> dict:
        return {
            "total": 0, "approve_lane": 0, "review_lane": 0,
            "reject_lane": 0, "auto_approved": 0, "auto_rejected": 0,
            "api_calls_used": 0, "results": [],
        }


# ── 模組層輔助函數 ─────────────────────────────────────────────────

def _clean(text: str) -> str:
    """移除 Prompt Injection 特徵"""
    return _INJECTION_PATTERNS.sub("[filtered]", text or "")


def _build_prompt(items: list[dict]) -> str:
    items_json = json.dumps(items, ensure_ascii=False, indent=2)
    return f"""你是一個知識品質審查助手。以下是從程式碼庫自動提取的知識條目，
請判斷每一條的入庫品質。

{items_json}

以 JSON 陣列回答，每項對應輸入順序，不要輸出任何其他文字：
[
  {{
    "id": "與輸入相同的 id",
    "recommendation": "approve" | "review" | "reject",
    "confidence": 0.0-1.0,
    "reason": "一句話說明（中文，30字以內）"
  }}
]

判斷標準：
- approve （confidence ≥ 0.85）：內容清晰、可操作、非重複、明確是 Rule/Pitfall/Decision/ADR
- review  （confidence 0.60-0.84）：有價值但表述模糊、適用條件不明確、需人工確認
- reject  （confidence < 0.60）：過於模糊（如「要注意效能」）、與程式碼無關、明顯雜訊或重複

注意：kind=Pitfall 的條目請謹慎判斷，寧可標 review 也不要輕易 approve。"""
