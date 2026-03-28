"""
core/brain/knowledge_validator.py — Agent 自主知識驗證（v4.0）

功能：
  AI 定期審查 L3 知識圖譜中的每一筆知識，
  確認是否仍然準確、是否已被技術演進取代、是否與現有程式碼吻合。
  自動更新信心分數，標記過期或矛盾知識。

設計理念：
  「知識腐爛比沒有知識更危險。」
  一年前「用 HS256 就夠了」的決策，今天注入給 SHIELD 會製造安全漏洞。
  KnowledgeValidator 讓知識圖譜保持活的——不只是記錄，而是持續審查的系統。

驗證策略（三階段）：
  1. 規則驗證（本地，<1ms）
      → 字元長度、格式完整性、必要欄位、信心閾值
  2. 程式碼比對（本地，<100ms）
      → 知識中提到的組件是否還存在？函數是否還有這個簽名？
  3. Claude 語義驗證（API 呼叫，~2s）
      → 「根據現有程式碼，這條知識還準確嗎？」
      → 只對重要知識（高信心 + 高引用）觸發，控制成本

成本控制：
  - Claude 驗證只在滿足條件時觸發：
      confidence > 0.5 AND kind IN ('Decision','Rule') AND age_days > 30
  - max_api_calls 限制每次驗證的 API 呼叫數（預設 20）
  - 結果快取 7 天（同一筆知識不重複驗證）
  - 使用 Haiku（最廉價的前沿模型），每次 ~0.002 USD

安全設計：
  - Prompt Injection 防護：知識內容在送入 Claude 前清理
  - 驗證結果只更新 confidence（不刪除知識，保留歷史）
  - 所有操作記錄到 validation_log 表（可審計）
  - max_api_calls 強制上限（防止失控）
"""

from __future__ import annotations
from .output import OK, WARN, ERR, R, B, G, Y, C, RE, P, GR, D, W, hr, badge, conf_color

import re
import json
import time
import hashlib
import logging
import sqlite3
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── 常數 ──────────────────────────────────────────────────────
VALIDATION_CACHE_DAYS    = 7        # 同一知識的驗證快取天數
MIN_AGE_DAYS_FOR_AI      = 30       # 知識至少存在 30 天才觸發 AI 驗證
MIN_CONFIDENCE_FOR_AI    = 0.5      # 低信心不值得花 API 費用驗證
AI_VALIDATE_KINDS        = {"Decision", "Rule", "ADR"}  # 只驗證這些類型
MAX_CONTENT_FOR_PROMPT   = 800      # 知識內容送入 Claude 的最大字元數
MAX_CODE_CONTEXT         = 1_200    # 程式碼上下文的最大字元數

# Prompt Injection 防護：這些指令在知識內容中出現時過濾
_INJECTION_PATTERNS = re.compile(
    r"\b(ignore|forget|override|disregard|pretend|jailbreak|"
    r"act as|new instruction|system:|<\|im_start\|>)\b",
    re.IGNORECASE,
)

# ── 資料結構 ──────────────────────────────────────────────────

@dataclass
class ValidationResult:
    """單筆知識的驗證結果"""
    node_id:          str
    title:            str
    kind:             str
    original_conf:    float
    new_conf:         float
    is_valid:         bool
    validator:        str         # "rule" | "code" | "claude"
    reason:           str
    action:           str         # "keep" | "update" | "flag" | "invalidate"
    validated_at:     str         = field(default_factory=lambda: _now())

    @property
    def conf_delta(self) -> float:
        return self.new_conf - self.original_conf

    def to_summary_line(self) -> str:
        from .output import OK, WARN, ERR, badge, conf_color, R, GR, W, D
        delta_str = f"{self.conf_delta:+.2f}" if abs(self.conf_delta) > 0.01 else "="
        if self.is_valid and self.action == "keep":
            icon = OK
        elif self.action == "flag":
            icon = WARN
        else:
            icon = ERR
        c_old = conf_color(self.original_conf)
        c_new = conf_color(self.new_conf)
        b = badge(self.kind)
        title = self.title[:36]
        return (f"  {icon} {b:<32} {title:<38} "
                f"{c_old}{self.original_conf:.2f}{R}{GR}→{R}"
                f"{c_new}{self.new_conf:.2f}{R}{GR}({delta_str}){R}  "
                f"{D}[{self.validator}]{R}")


@dataclass
class ValidationReport:
    """一次驗證執行的完整報告"""
    run_id:           str
    total_checked:    int
    valid_count:      int
    flagged_count:    int
    invalidated_count: int
    api_calls_used:   int
    elapsed_ms:       int
    results:          list[ValidationResult] = field(default_factory=list)

    def summary(self) -> str:
        from .output import OK, WARN, ERR, R, B, G, Y, RE, C, GR, W, hr
        return (
            f"\n{C}{B}🔍  驗證報告{R}  {GR}[{self.run_id}]{R}\n{GR}{hr()}{R}\n"
            f"  {B}總計{R}    {W}{self.total_checked}{R} 筆\n"
            f"  {OK} 有效  {G}{B}{self.valid_count}{R}  "
            f"{WARN} 標記  {Y}{B}{self.flagged_count}{R}  "
            f"{ERR} 失效  {RE}{B}{self.invalidated_count}{R}\n"
            f"  {B}API 呼叫{R}  {W}{self.api_calls_used}{R} 次  "
            f"{GR}│{R}  {B}耗時{R}  {W}{self.elapsed_ms}{R} ms\n"
            f"{GR}{hr()}{R}"
        )


# ══════════════════════════════════════════════════════════════
#  KnowledgeValidator
# ══════════════════════════════════════════════════════════════

class KnowledgeValidator:
    """
    三階段自主知識驗證系統（v4.0）。

    使用方式：
        validator = KnowledgeValidator(graph, workdir, client=anthropic_client)
        report = validator.run(max_api_calls=20)
        print(report.summary())

    定期執行（例如每週）：
        validator.run_scheduled(interval_days=7)
    """

    def __init__(
        self,
        graph,                              # KnowledgeGraph 實例
        workdir:       Path,
        client         = None,              # anthropic.Anthropic 實例（AI 驗證用）
        model:         str = "claude-haiku-4-5-20251001",  # 最廉價的前沿模型
        brain_dir:     Path | None = None,
    ):
        self.graph    = graph
        self.workdir  = Path(workdir)
        self.client   = client
        self.model    = model
        self.brain_dir = brain_dir or (self.workdir / ".brain")
        self._lock    = threading.Lock()
        self._setup_db()

    def _setup_db(self) -> None:
        """建立驗證日誌資料庫"""
        self.brain_dir.mkdir(parents=True, exist_ok=True)
        db_path = self.brain_dir / "validation_log.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA busy_timeout=5000;

        CREATE TABLE IF NOT EXISTS validation_cache (
            content_hash  TEXT PRIMARY KEY,
            result_json   TEXT NOT NULL,
            validated_at  TEXT NOT NULL,
            expires_at    TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS validation_runs (
            run_id        TEXT PRIMARY KEY,
            total_checked INTEGER,
            valid_count   INTEGER,
            flagged_count INTEGER,
            invalid_count INTEGER,
            api_calls     INTEGER,
            elapsed_ms    INTEGER,
            run_at        TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS validation_details (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id     TEXT NOT NULL,
            node_id    TEXT NOT NULL,
            kind       TEXT,
            is_valid   INTEGER,
            validator  TEXT,
            action     TEXT,
            conf_old   REAL,
            conf_new   REAL,
            reason     TEXT,
            detail_at  TEXT NOT NULL
        );
        """)
        conn.commit()
        conn.close()

    def _db_conn(self) -> sqlite3.Connection:
        db_path = self.brain_dir / "validation_log.db"
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    # ── 主入口 ────────────────────────────────────────────────

    def run(
        self,
        max_api_calls: int = 20,
        kinds:         list[str] | None = None,
        dry_run:       bool = False,
    ) -> ValidationReport:
        """
        執行一次完整驗證。

        Args:
            max_api_calls: AI 語義驗證的最大 API 呼叫次數（成本控制）
            kinds:         只驗證這些類型（None = 全部）
            dry_run:       只輸出報告，不更新 confidence
        """
        import uuid
        run_id   = str(uuid.uuid4())[:8]
        t0       = time.monotonic()
        api_used = 0

        logger.info("validation_start", run_id=run_id, max_api=max_api_calls)
        print(f"\n{C}{B}🔍  知識驗證{R}  {GR}[{run_id}]{R}  max_api_calls={W}{max_api_calls}{R}\n{GR}{hr()}{R}")

        # 取得所有節點
        all_nodes = self._get_all_nodes(kinds)
        results   = []

        for node in all_nodes:
            # 階段 1：規則驗證（永遠執行）
            result = self._validate_rules(node)

            # 階段 2：程式碼比對（本地，不耗費 API）
            if result.is_valid:
                result = self._validate_code_reference(node, result)

            # 階段 3：Claude 語義驗證（按條件觸發）
            if (result.is_valid
                    and self.client is not None
                    and api_used < max_api_calls
                    and self._should_ai_validate(node)):
                ai_result = self._validate_with_claude(node)
                if ai_result is not None:
                    result  = ai_result
                    api_used += 1

            results.append(result)

            # 更新 confidence（除非 dry_run）
            if not dry_run:
                self._apply_result(node, result)

            print(result.to_summary_line())

        elapsed_ms    = int((time.monotonic() - t0) * 1_000)
        valid_count   = sum(1 for r in results if r.is_valid)
        flagged_count = sum(1 for r in results if r.action == "flag")
        invalid_count = sum(1 for r in results if r.action == "invalidate")

        report = ValidationReport(
            run_id            = run_id,
            total_checked     = len(results),
            valid_count       = valid_count,
            flagged_count     = flagged_count,
            invalidated_count = invalid_count,
            api_calls_used    = api_used,
            elapsed_ms        = elapsed_ms,
            results           = results,
        )

        if not dry_run:
            self._save_run(report)

        logger.info("validation_done", run_id=run_id, total=len(results),
                    api_calls=api_used, elapsed_ms=elapsed_ms)
        print(f"\n{report.summary()}")
        return report

    # ── 階段 1：規則驗證 ──────────────────────────────────────

    def _validate_rules(self, node: dict) -> ValidationResult:
        """快速規則驗證：格式、長度、必要欄位"""
        node_id = node.get("id", "?")
        title   = node.get("title", "")
        kind    = node.get("kind", "")
        content = node.get("content", node.get("description", ""))
        conf    = float(node.get("confidence", 0.5))

        issues = []

        # 必要欄位
        if not title.strip():
            issues.append("缺少標題")
        if not content.strip():
            issues.append("內容為空")
        if len(content) < 10:
            issues.append(f"內容過短（{len(content)} 字元）")

        # 信心分數
        if conf < 0.05:
            issues.append(f"信心分數過低（{conf:.2f}）")

        # Prompt Injection 徵兆（知識被污染）
        if _INJECTION_PATTERNS.search(title + " " + content):
            issues.append("疑似 Prompt Injection 污染")

        if issues:
            return ValidationResult(
                node_id      = node_id,
                title        = title,
                kind         = kind,
                original_conf= conf,
                new_conf     = max(0.1, conf * 0.8),
                is_valid     = False,
                validator    = "rule",
                reason       = "；".join(issues),
                action       = "flag",
            )

        return ValidationResult(
            node_id      = node_id,
            title        = title,
            kind         = kind,
            original_conf= conf,
            new_conf     = conf,
            is_valid     = True,
            validator    = "rule",
            reason       = "規則驗證通過",
            action       = "keep",
        )

    # ── 階段 2：程式碼比對 ────────────────────────────────────

    def _validate_code_reference(
        self, node: dict, prev: ValidationResult
    ) -> ValidationResult:
        """
        比對知識中提到的組件是否仍存在於程式碼中。
        若知識提到 'AuthService.login()' 但已找不到這個函數，降低信心。
        """
        content  = node.get("content", node.get("description", ""))
        tag_text = " ".join(node.get("tags", []))

        # 提取組件名稱（CamelCase 或 snake_case 的函數/類別）
        refs = set(re.findall(r'\b([A-Z][a-zA-Z]{2,}(?:\.[a-z]\w+)?)\b', content))
        refs.update(re.findall(r'\b([a-z_]{3,}\.[a-z_]{3,})\b', content))

        if not refs:
            return prev  # 沒有程式碼引用，跳過此階段

        missing   = []
        found_any = False

        for ref in list(refs)[:5]:  # 只查前 5 個（避免太慢）
            # 在工作目錄搜尋（簡單的 grep）
            try:
                import subprocess
                result = subprocess.run(
                    ["grep", "-r", "--include=*.py", "--include=*.ts",
                     "--include=*.js", "-l", ref.split(".")[0], str(self.workdir)],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    found_any = True
                else:
                    missing.append(ref)
            except Exception:
                pass  # grep 失敗不影響主流程

        if missing and not found_any:
            # 所有引用都找不到 → 可能是過期知識
            new_conf = max(0.15, prev.new_conf * 0.7)
            return ValidationResult(
                node_id      = node.get("id", "?"),
                title        = node.get("title", ""),
                kind         = node.get("kind", ""),
                original_conf= prev.original_conf,
                new_conf     = new_conf,
                is_valid     = True,  # 仍然有效，但信心降低
                validator    = "code",
                reason       = f"程式碼引用找不到：{', '.join(missing[:3])}",
                action       = "flag",
            )

        return prev

    # ── 階段 3：Claude 語義驗證 ───────────────────────────────

    def _should_ai_validate(self, node: dict) -> bool:
        """判斷是否值得花 API 費用驗證這筆知識"""
        kind  = node.get("kind", "")
        conf  = float(node.get("confidence", 0.5))
        kind_ok = kind in AI_VALIDATE_KINDS

        # 年齡檢查（太新的知識不驗證）
        created = node.get("created_at", "")
        if created:
            try:
                age = (datetime.now(timezone.utc) -
                       datetime.fromisoformat(created.replace("Z", "+00:00"))
                ).days
                if age < MIN_AGE_DAYS_FOR_AI:
                    return False
            except Exception:
                pass

        # 快取檢查（7 天內已驗證的不重複驗證）
        content_hash = hashlib.sha256(
            (node.get("title", "") + node.get("content",
             node.get("description", ""))).encode()
        ).hexdigest()[:16]
        if self._is_cached(content_hash):
            return False

        return kind_ok and conf >= MIN_CONFIDENCE_FOR_AI

    def _validate_with_claude(self, node: dict) -> ValidationResult | None:
        """Claude 語義驗證：AI 讀取知識 + 程式碼上下文，判斷是否仍然準確"""
        title   = node.get("title", "")
        content = node.get("content", node.get("description", ""))[:MAX_CONTENT_FOR_PROMPT]
        kind    = node.get("kind", "")
        conf    = float(node.get("confidence", 0.5))

        # 安全清理：移除 Prompt Injection 嘗試
        safe_content = _INJECTION_PATTERNS.sub("[filtered]", content)
        safe_title   = _INJECTION_PATTERNS.sub("[filtered]", title)

        # 程式碼上下文（從工作目錄的相關檔案）
        code_ctx = self._get_relevant_code(safe_title, safe_content)

        prompt = f"""你是一個程式碼知識驗證助手。請評估以下知識條目在現有程式碼中是否仍然準確。

知識類型：{kind}
知識標題：{safe_title}
知識內容：{safe_content}

{f'相關程式碼上下文：\n```\n{code_ctx[:MAX_CODE_CONTEXT]}\n```\n' if code_ctx else '（無直接程式碼上下文可供比對）'}

請以 JSON 格式回答（不要輸出其他任何文字）：
{{
  "is_accurate": true/false,
  "confidence": 0.0-1.0,
  "reason": "一句話說明",
  "action": "keep"/"flag"/"invalidate"
}}

判斷標準：
- keep：知識仍然準確，可以信任
- flag：有疑問，需要人工確認
- invalidate：確定過期或不準確，應降低信心"""

        try:
            resp = self.client.messages.create(
                model      = self.model,
                max_tokens = 256,
                messages   = [{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()

            # 清除 markdown 程式碼塊
            raw = re.sub(r"```(?:json)?|```", "", raw).strip()
            data = json.loads(raw)

            is_accurate = bool(data.get("is_accurate", True))
            new_conf    = float(data.get("confidence", conf))
            new_conf    = max(0.01, min(1.0, new_conf))  # 邊界保護
            action      = str(data.get("action", "keep"))
            reason      = str(data.get("reason", "Claude 驗證"))[:200]

            # 快取結果
            content_hash = hashlib.sha256(
                (title + content).encode()
            ).hexdigest()[:16]
            self._cache_result(content_hash, {
                "is_accurate": is_accurate,
                "new_conf": new_conf,
                "action": action,
                "reason": reason,
            })

            return ValidationResult(
                node_id      = node.get("id", "?"),
                title        = title,
                kind         = kind,
                original_conf= conf,
                new_conf     = new_conf,
                is_valid     = is_accurate,
                validator    = "claude",
                reason       = reason,
                action       = action,
            )

        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.warning("claude_validation_parse_failed | node_id=%s", node.get("id"), error=str(e)[:80])
            return None
        except Exception as e:
            logger.error("claude_validation_failed | node_id=%s", node.get("id"), error=str(e)[:100])
            return None

    def _get_relevant_code(self, title: str, content: str) -> str:
        """從工作目錄找到與知識相關的程式碼片段"""
        keywords = re.findall(r'\b[A-Z][a-zA-Z]{2,}\b', title + " " + content)
        if not keywords:
            return ""
        try:
            import subprocess
            result = subprocess.run(
                ["grep", "-r", "--include=*.py", "--include=*.ts",
                 "-n", "-m", "3", keywords[0], str(self.workdir)],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout[:MAX_CODE_CONTEXT] if result.returncode == 0 else ""
        except Exception:
            return ""

    # ── 結果應用 ──────────────────────────────────────────────

    def _apply_result(self, node: dict, result: ValidationResult) -> None:
        """將驗證結果應用到知識圖譜（更新 confidence）"""
        if abs(result.conf_delta) < 0.01 and result.action == "keep":
            return  # 無需更新

        try:
            conn = self.graph._conn
            if result.action == "invalidate":
                conn.execute(
                    "UPDATE nodes SET confidence=?, is_invalidated=1 WHERE id=?",
                    (result.new_conf, result.node_id)
                )
                logger.info("knowledge_invalidated",
                            node_id=result.node_id, reason=result.reason)
            elif abs(result.conf_delta) > 0.01:
                conn.execute(
                    "UPDATE nodes SET confidence=? WHERE id=?",
                    (result.new_conf, result.node_id)
                )
            conn.commit()
        except Exception as e:
            logger.error("apply_result_failed",
                         node_id=result.node_id, error=str(e)[:100])

    # ── 快取管理 ──────────────────────────────────────────────

    def _is_cached(self, content_hash: str) -> bool:
        """檢查驗證結果是否在快取內（7 天有效）"""
        try:
            conn = self._db_conn()
            row  = conn.execute(
                "SELECT expires_at FROM validation_cache WHERE content_hash=?",
                (content_hash,)
            ).fetchone()
            if row:
                expires = datetime.fromisoformat(row["expires_at"])
                if datetime.now(timezone.utc) < expires:
                    return True
            conn.close()
        except Exception:
            pass
        return False

    def _cache_result(self, content_hash: str, result: dict) -> None:
        """快取驗證結果（7 天）"""
        try:
            expires = (datetime.now(timezone.utc) +
                       timedelta(days=VALIDATION_CACHE_DAYS)).isoformat()
            conn = self._db_conn()
            conn.execute(
                "INSERT OR REPLACE INTO validation_cache "
                "(content_hash, result_json, validated_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (content_hash, json.dumps(result), _now(), expires)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("cache_write_failed | error=%s", str(e)[:80])

    # ── 資料存取 ──────────────────────────────────────────────

    def _get_all_nodes(self, kinds=None):
        """取得所有節點（適配 KnowledgeGraph 的 type 欄位）"""
        try:
            conn = self.graph._conn
            if kinds:
                ph = ",".join("?" * len(kinds))
                rows = conn.execute(
                    f"SELECT id, type as kind, title, content, tags, created_at "
                    f"FROM nodes WHERE type IN ({ph}) LIMIT 500", kinds
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, type as kind, title, content, tags, created_at "
                    "FROM nodes LIMIT 500"
                ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d.setdefault("confidence", 0.7)
                d.setdefault("description", "")
                result.append(d)
            return result
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("get_nodes_failed: %s", str(e)[:100])
            return []

    def _save_run(self, report: ValidationReport) -> None:
        """儲存驗證執行記錄"""
        try:
            conn = self._db_conn()
            conn.execute(
                "INSERT INTO validation_runs VALUES (?,?,?,?,?,?,?,?)",
                (report.run_id, report.total_checked, report.valid_count,
                 report.flagged_count, report.invalidated_count,
                 report.api_calls_used, report.elapsed_ms, _now())
            )
            for r in report.results:
                conn.execute(
                    "INSERT INTO validation_details "
                    "(run_id,node_id,kind,is_valid,validator,action,"
                    "conf_old,conf_new,reason,detail_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (report.run_id, r.node_id, r.kind, int(r.is_valid),
                     r.validator, r.action, r.original_conf,
                     r.new_conf, r.reason, r.validated_at)
                )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error("save_run_failed | error=%s", str(e)[:100])

    def history(self, limit: int = 10) -> list[dict]:
        """取得最近的驗證執行歷史"""
        try:
            conn = self._db_conn()
            rows = conn.execute(
                "SELECT * FROM validation_runs ORDER BY run_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            return []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
