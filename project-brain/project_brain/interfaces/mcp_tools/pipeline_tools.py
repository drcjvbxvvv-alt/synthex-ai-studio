"""
Pipeline tools: auto_resolve_knowledge, generate_questions, krb_pre_screen.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def register(mcp: Any, srv: Any, helpers: dict) -> None:
    """Register pipeline-related MCP tools."""

    _safe_str = helpers["_safe_str"]
    MAX_QUERY_LEN = helpers["MAX_QUERY_LEN"]

    # ── Tool: auto_resolve_knowledge ───────────────────────────────

    @mcp.tool()
    def auto_resolve_knowledge(
        task: str,
        threshold: float = 0.5,
        use_llm: bool = True,
        workdir: str = "",
    ) -> dict:
        """DEEP-04: AI 自動評估並修正低信心節點,無需人工介入。

        系統主目標是讓 AI 在長期大型企業專案中自主運作。
        此工具讓 AI 主動對知識庫中不確定的節點做出裁決:
        - Rule-based(零費用）：根據 adoption_count / access_count 自動裁決
        - LLM-assisted（可選）：規則無法裁決時,呼叫 Anthropic/Ollama 取得 AI 意見

        建議在 get_context() 之後呼叫,持續優化知識品質。

        Args:
            task:      當前任務描述(用於搜尋相關低信心節點)
            threshold: 信心門檻(低於此值觸發裁決,預設 0.5)
            use_llm:   是否允許呼叫 LLM(預設 True;rule-based 失敗時使用)
            workdir:   工作目錄(選填)

        Returns:
            {"resolved": N, "boosted": N, "downgraded": N, "deprecated": N,
             "unchanged": N, "details": [...]}
        """
        srv.rate_check()
        t_clean = _safe_str(task, MAX_QUERY_LEN, "task")
        b = srv.resolve_brain(workdir)
        try:
            from project_brain.nudge_engine import NudgeEngine
            ne = NudgeEngine(b.graph, brain_db=b.db)
            return ne.auto_resolve_batch(
                t_clean,
                threshold=float(threshold),
                use_llm=bool(use_llm),
            )
        except Exception as e:
            logger.error("auto_resolve_knowledge error: %s", e)
            return {"resolved": 0, "boosted": 0, "downgraded": 0,
                    "deprecated": 0, "unchanged": 0, "details": [], "error": str(e)}

    # ── Tool: generate_questions ───────────────────────────────────

    @mcp.tool()
    def generate_questions(task: str, threshold: float = 0.5,
                           workdir: str = "") -> list:
        """DEEP-04: 列出低信心節點供 AI 主動確認(明確確認路徑)。

        一般情況下 auto_resolve_knowledge() 會自動處理,
        此工具適合 AI 需要明確列出「尚不確定的知識」再逐一裁決時使用。

        Args:
            task:      當前任務描述
            threshold: 信心門檻(低於此值列出,預設 0.5)
            workdir:   工作目錄(選填)

        Returns:
            [{"node_id": ..., "question": "...", "current_confidence": 0.38}]
        """
        srv.rate_check()
        t_clean = _safe_str(task, MAX_QUERY_LEN, "task")
        b = srv.resolve_brain(workdir)
        try:
            from project_brain.nudge_engine import NudgeEngine
            ne = NudgeEngine(b.graph, brain_db=b.db)
            return ne.generate_questions(t_clean, threshold=float(threshold))
        except Exception as e:
            logger.error("generate_questions error: %s", e)
            return []

    # ── Tool: krb_pre_screen ───────────────────────────────────────

    @mcp.tool()
    def krb_pre_screen(
        limit: int = 50,
        auto_approve_threshold: float = 0.0,
        auto_reject_threshold: float = 0.0,
        max_api_calls: int = 10,
        workdir: str = "",
    ) -> dict:
        """
        AI-assisted KRB review — pre-screen pending staged nodes with Claude Haiku.

        Routes each pending knowledge node into one of three lanes:
          approve lane  — AI confident the knowledge is clear and actionable
          review lane   — needs human judgment (always used for Pitfall nodes)
          reject lane   — likely noise, too vague, or duplicate

        Call this after brain scan or any large batch import to reduce
        manual review burden. Human still has final say — auto-approve and
        auto-reject are OFF by default (set threshold > 0 to enable).

        Args:
            limit:                   Max pending nodes to process (default 50).
            auto_approve_threshold:  AI confidence >= this -> auto-approve.
                                     0.0 = disabled (recommended default).
                                     Pitfall nodes are NEVER auto-approved.
            auto_reject_threshold:   AI confidence >= this AND recommends reject
                                     -> auto-reject. 0.0 = disabled.
            max_api_calls:           Cost guard: max Haiku API calls (default 10).
            workdir:                 Project working directory (optional).

        Returns:
            {
              "total":          nodes processed,
              "approve_lane":   count routed to approve,
              "review_lane":    count routed to human review,
              "reject_lane":    count routed to reject,
              "auto_approved":  count actually auto-approved,
              "auto_rejected":  count actually auto-rejected,
              "api_calls_used": Haiku API calls consumed,
            }
        """
        import os as _os

        srv.rate_check()

        api_key = _os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return {"error": "ANTHROPIC_API_KEY 未設定，無法執行 AI 預篩"}

        b = srv.resolve_brain(workdir)
        bd = b.brain_dir

        try:
            import anthropic
            from project_brain.graph import KnowledgeGraph
            from project_brain.review_board import KnowledgeReviewBoard
            from project_brain.krb_ai_assist import KRBAIAssistant

            graph = KnowledgeGraph(bd)
            krb = KnowledgeReviewBoard(bd, graph)
            client = anthropic.Anthropic(api_key=api_key)
            assist = KRBAIAssistant(krb, client)

            aa = auto_approve_threshold if auto_approve_threshold > 0.0 else None
            ar = auto_reject_threshold if auto_reject_threshold > 0.0 else None

            summary = assist.pre_screen(
                limit=max(1, min(200, limit)),
                auto_approve_threshold=aa,
                auto_reject_threshold=ar,
                max_api_calls=max(1, min(50, max_api_calls)),
            )
            summary.pop("results", None)
            return summary

        except ImportError:
            return {"error": "anthropic 套件未安裝，請執行：pip install anthropic"}
        except Exception as e:
            logger.error("krb_pre_screen 內部錯誤：%s", e)
            return {"error": "預篩失敗，請檢查日誌"}
