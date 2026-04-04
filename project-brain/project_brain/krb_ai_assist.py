"""
project_brain/krb_ai_assist.py — PH3-03 AI-Assisted KRB Review

由 AI（Claude Haiku 或本地 Ollama 模型）預篩 KRB staging 中的待審知識，降低人工審查負擔。

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
  - client 參數 duck-typed：支援 anthropic.Anthropic 或 OllamaClient

成本估算：
  50 條待審 / 5 條每呼叫 = 10 次 Haiku → ~$0.002
  Ollama 本地運行 → $0（需本地 GPU/CPU）

後端選擇：
  雲端（預設）：KRBAIAssistant(krb, anthropic.Anthropic())
  本地 Ollama ：KRBAIAssistant.from_ollama(krb)  # 使用 llama3.2，零成本
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── 常數 ──────────────────────────────────────────────────────────
MAX_ITEMS_PER_CALL   = 5       # 每次 API 呼叫處理的節點數
MAX_CONTENT_PROMPT   = 400     # 單條知識送入 Prompt 的最大字元
CACHE_HOURS          = 24      # 相同節點不在 24 小時內重複預篩
DEFAULT_MODEL        = "claude-haiku-4-5-20251001"
DEFAULT_OLLAMA_MODEL = "llama3.2"           # 預設本地模型
DEFAULT_OLLAMA_URL   = "http://localhost:11434"

# Prompt Injection 防護（同 knowledge_validator.py）
_INJECTION_PATTERNS = re.compile(
    r"\b(ignore|forget|override|disregard|pretend|jailbreak|"
    r"act as|new instruction|system:|<\|im_start\|>)\b",
    re.IGNORECASE,
)


# ══════════════════════════════════════════════════════════════════
#  OllamaClient — anthropic.Anthropic 的本地替代（零外部依賴）
# ══════════════════════════════════════════════════════════════════

class _OllamaContent:
    """模擬 anthropic ContentBlock，提供 .text 屬性"""
    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text


class _OllamaResponse:
    """模擬 anthropic Message，提供 .content[0].text"""
    __slots__ = ("content",)

    def __init__(self, text: str) -> None:
        self.content = [_OllamaContent(text)]


class _OllamaMessages:
    """模擬 anthropic.Anthropic().messages，提供 .create()"""

    def __init__(self, base_url: str, timeout: int) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout  = timeout

    def create(
        self,
        model:      str,
        max_tokens: int,
        messages:   list[dict],
        **_kwargs,
    ) -> _OllamaResponse:
        """
        呼叫 Ollama /api/chat，回傳與 anthropic 相容的 _OllamaResponse。

        使用 format="json" 強制模型輸出 JSON，減少解析失敗率。
        """
        payload = json.dumps({
            "model":    model,
            "messages": messages,
            "stream":   False,
            "options":  {"num_predict": max_tokens},
            "format":   "json",
        }).encode()

        req = urllib.request.Request(
            f"{self._base_url}/api/chat",
            data    = payload,
            headers = {"Content-Type": "application/json"},
            method  = "POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = json.loads(resp.read())
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Ollama 連線失敗（{self._base_url}）：{exc.reason}。"
                "請確認 Ollama 已啟動（ollama serve）。"
            ) from exc

        text = body["message"]["content"]
        return _OllamaResponse(text)


class OllamaClient:
    """
    本地 Ollama 後端，介面與 anthropic.Anthropic() 相容。

    使用方式：
        client = OllamaClient()                        # 預設 localhost:11434
        client = OllamaClient(base_url="http://...")   # 自訂位址
        assist = KRBAIAssistant(krb, client, model="llama3.2")

    或使用工廠方法（更簡潔）：
        assist = KRBAIAssistant.from_ollama(krb)
    """

    def __init__(
        self,
        base_url: str = DEFAULT_OLLAMA_URL,
        timeout:  int = 120,
    ) -> None:
        self.messages = _OllamaMessages(base_url, timeout)

    @staticmethod
    def list_models(base_url: str = DEFAULT_OLLAMA_URL) -> list[str]:
        """回傳 Ollama 已下載的模型名稱列表（便於 CLI 選擇）"""
        req = urllib.request.Request(f"{base_url.rstrip('/')}/api/tags")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            return [m["name"] for m in data.get("models", [])]
        except Exception as exc:
            logger.debug("OllamaClient.list_models failed: %s", exc)
            return []


def make_client(
    provider: str = "anthropic",
    **kwargs,
):
    """
    工廠函數：依 provider 建立對應的 LLM client。

    Args:
        provider: "anthropic"（預設，需安裝 anthropic 套件）
                  "ollama"   （本地，零外部依賴）
        **kwargs: 傳入對應 client 的建構子
                  anthropic → 透傳給 anthropic.Anthropic(**kwargs)
                  ollama    → base_url, timeout

    Returns:
        anthropic.Anthropic 實例 或 OllamaClient 實例

    範例：
        client = make_client()                        # Claude Haiku（雲端）
        client = make_client("ollama")                # llama3.2（本地）
        client = make_client("ollama", base_url="http://gpu-box:11434")
    """
    if provider == "ollama":
        return OllamaClient(**kwargs)
    try:
        import anthropic  # type: ignore
        return anthropic.Anthropic(**kwargs)
    except ImportError as exc:
        raise ImportError(
            "anthropic 套件未安裝。請執行 `pip install anthropic` "
            "或改用 provider='ollama'。"
        ) from exc

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

    雲端後端（需 anthropic 套件）：
        import anthropic
        assist = KRBAIAssistant(krb, anthropic.Anthropic())

    本地 Ollama 後端（零外部依賴）：
        assist = KRBAIAssistant.from_ollama(krb)
        assist = KRBAIAssistant.from_ollama(krb, model="mistral", base_url="http://gpu:11434")

    使用工廠函數選擇後端：
        from project_brain.krb_ai_assist import make_client
        assist = KRBAIAssistant(krb, make_client("ollama"), model="llama3.2")
    """

    def __init__(
        self,
        krb,
        client,           # anthropic.Anthropic 實例 或 OllamaClient 實例（duck-typed）
        model: str = DEFAULT_MODEL,
    ):
        self.krb    = krb
        self.client = client
        self.model  = model
        self._brain_dir: Path = Path(krb.brain_dir)
        self._cache_db  = self._brain_dir / "krb_ai_cache.db"
        self._setup_cache()

    @classmethod
    def from_ollama(
        cls,
        krb,
        model:    str = DEFAULT_OLLAMA_MODEL,
        base_url: str = DEFAULT_OLLAMA_URL,
        timeout:  int = 120,
    ) -> "KRBAIAssistant":
        """
        便捷方法：以本地 Ollama 後端建立 KRBAIAssistant。

        Args:
            krb:      KnowledgeReviewBoard 實例
            model:    Ollama 模型名稱（預設 "llama3.2"）
            base_url: Ollama 服務位址（預設 "http://localhost:11434"）
            timeout:  單次請求逾時秒數（預設 120）

        範例：
            assist = KRBAIAssistant.from_ollama(krb)
            assist = KRBAIAssistant.from_ollama(krb, model="mistral")
        """
        return cls(krb, OllamaClient(base_url=base_url, timeout=timeout), model=model)

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
        except Exception as _e:
            logger.debug("cache check failed", exc_info=True)
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
