# 自動知識生產管線 — 設計文件

**文件版本**：v0.2
**建立日期**：2026-04-06
**更新日期**：2026-04-06
**狀態**：Phase 1 可實作
**作者**：架構討論 / Claude Sonnet 4.6

---

## 目錄

1. [背景與動機](#1-背景與動機)
2. [設計原則](#2-設計原則)
3. [系統架構總覽](#3-系統架構總覽)
4. [Layer 1 — 信號收集](#4-layer-1--信號收集)
5. [Layer 2 — 信號佇列](#5-layer-2--信號佇列)
6. [Layer 3 — LLM 判斷引擎](#6-layer-3--llm-判斷引擎)
7. [Layer 4 — 確定性執行器](#7-layer-4--確定性執行器)
8. [Layer 5 — 回饋迴路](#8-layer-5--回饋迴路)
9. [資料模型](#9-資料模型)
10. [Prompt 設計](#10-prompt-設計)
11. [非同步管線設計](#11-非同步管線設計)
12. [可靠性與 Fallback](#12-可靠性與-fallback)
13. [與現有 Project Brain 整合](#13-與現有-project-brain-整合)
14. [測試策略](#14-測試策略)
15. [風險與對策](#15-風險與對策)
16. [實作路線圖](#16-實作路線圖)
17. [成本與效能估算](#17-成本與效能估算)
18. [未解問題](#18-未解問題)

---

## 1. 背景與動機

### 1.1 現況缺口

Project Brain 目前的知識生產方式全部依賴**主動呼叫**：

```
現有知識入口                        問題
─────────────────────────────────────────────────────────
brain add / add_knowledge          人工呼叫，容易忘記
learn_from_commit (git hook)       只在 commit 時點觸發
complete_task                      只捕捉結束狀態，不捕捉過程
batch_add_knowledge                仍需人工組裝批次
```

**沉默區域（現在完全沒有捕捉）**：
- AI 對話過程中出現的洞見
- 同一錯誤在多個 session 重複發生
- 跨 session 累積的設計模式
- 已知知識與新觀察之間的矛盾
- 低信心節點自然升級的路徑

### 1.2 為什麼選擇 LLM 主導判斷

知識生產的核心問題是**語意判斷**，不是計算：

| 判斷問題 | 規則程式碼 | LLM |
|---------|-----------|-----|
| 這段 diff 記錄了什麼決策？ | 正則表達式，大量漏洞 | 語意理解，自然處理 |
| 兩個節點是否矛盾？ | 相似度閾值，誤判率高 | 理解語意脈絡後判斷 |
| 三個片段能合成為規則嗎？ | 無法做到 | 核心能力 |
| 這個知識的可信度是多少？ | 硬編碼公式 | 依據證據推理 |

**關鍵優勢**：LLM 能力只會隨模型迭代持續提升。今天寫的 prompt，明年由更強的模型執行，知識生產品質自動提升，不需改程式碼。

### 1.3 設計約束

必須在以下限制內運作：
- LLM API 延遲 1s～30s → **不可同步阻塞主流程**
- API 可能不可用 → **必須有 fallback，系統不能因此停擺**
- 知識寫入必須正確 → **DB 操作必須確定性執行，不容 LLM 直接操作**
- 本地優先 → **不可強制要求雲端 API（支援本地模型）**

---

## 2. 設計原則

### P1 — 判斷與執行嚴格分離

```
LLM 只做：「這是什麼？要做什麼？為什麼？」
程式碼只做：「把 LLM 的指令確定性地執行完」
```

LLM 不直接操作資料庫，也不做任何有副作用的操作。它只輸出結構化的 `KnowledgeDecision`，由 `Executor` 負責執行。

### P2 — 非同步、不阻塞

知識生產是後台任務。主流程（`get_context`、`add_knowledge`、`complete_task`）永遠同步立即回傳，不等待 LLM 分析結果。

### P3 — 可降級運作

LLM 不可用時，信號進入 pending 佇列，等 API 恢復後補處理。系統在無 LLM 的情況下仍能完整提供知識查詢與手動寫入。

### P4 — 結構化輸出，可審計

LLM 的每一個決策都輸出為 `KnowledgeDecision` JSON，記錄在 `signal_log` 表中，包含完整的輸入信號、LLM 的推理過程（`reason` 欄位）、最終操作結果。可事後審計、回滾。

### P5 — 回饋驅動品質

每一個由管線自動產生的知識節點，都標記 `source = "auto_pipeline"`，並接受 `report_knowledge_outcome` 的品質回饋。長期累積回饋資料，可用於：
- 調整 prompt
- 調整 confidence 起始值
- 決定哪類信號值得送 LLM 分析

### P6 — 本地模型相容

LLM 接口設計為可插拔，支援：
- Anthropic Claude API（預設）
- OpenAI 相容 API
- Ollama 本地模型（離線場景）

---

## 3. 系統架構總覽

```
┌──────────────────────────────────────────────────────────────────┐
│                    Auto Knowledge Pipeline                       │
│                                                                  │
│  ┌─────────────┐    ┌──────────────┐    ┌───────────────────┐   │
│  │   Layer 1   │    │   Layer 2    │    │     Layer 3       │   │
│  │  Signal     │───→│  Signal      │───→│  LLM Judgment     │   │
│  │  Collector  │    │  Queue       │    │  Engine           │   │
│  └─────────────┘    └──────────────┘    └────────┬──────────┘   │
│                                                  │               │
│                          KnowledgeDecision (JSON)↓               │
│                                                  │               │
│  ┌─────────────┐    ┌──────────────┐    ┌────────▼──────────┐   │
│  │   Layer 5   │    │   Layer 4    │    │     Layer 4       │   │
│  │  Feedback   │←───│  Knowledge   │←───│  Deterministic    │   │
│  │  Loop       │    │  Graph       │    │  Executor         │   │
│  └─────────────┘    └──────────────┘    └───────────────────┘   │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘

信號來源：
  git commit hook → SignalCollector
  MCP tool calls  → SignalCollector
  test failures   → SignalCollector
  manual trigger  → SignalCollector
```

**資料流**：

```
原始事件
   │
   ▼
Signal（標準化事件）
   │  非同步，不阻塞
   ▼
SQLite signal_queue 表（持久化，防止遺失）
   │
   ▼  background worker 取出
LLMAnalyzer.analyze(signal, related_nodes)
   │
   ▼
KnowledgeDecision（結構化 JSON）
   │
   ▼
KnowledgeExecutor.run(decision)
   │  確定性，有事務
   ▼
Knowledge Graph 更新 + signal_log 寫入
   │
   ▼
report_knowledge_outcome 回饋（人工或自動）
```

---

## 4. Layer 1 — 信號收集

### 4.1 信號類型定義

```python
from enum import Enum

class SignalKind(str, Enum):
    # ── Phase 1（基礎設施）──────────────────────────────────
    GIT_COMMIT       = "git_commit"       # git commit 事件
    TASK_COMPLETE    = "task_complete"    # complete_task 呼叫

    # ── Phase 2（信號擴展）──────────────────────────────────
    MCP_TOOL_CALL    = "mcp_tool_call"    # MCP 工具呼叫記錄
    TEST_FAILURE     = "test_failure"     # 測試失敗
    TEST_PASS        = "test_pass"        # 測試通過（追蹤解決）
    MANUAL           = "manual"           # 人工觸發分析

    # ── Phase 3+（待數據驗證後決定）──────────────────────────
    KNOWLEDGE_GAP    = "knowledge_gap"    # get_context 返回空結果
                                          # 注意：此信號的消費者（Note 節點的用途）
                                          # 尚未驗證，Phase 2 結束後視數據決定是否啟用
    CI_EVENT         = "ci_event"         # CI/CD pipeline 事件（未來）
    PR_COMMENT       = "pr_comment"       # PR review 留言（未來）
```

### 4.2 信號標準格式

```python
@dataclass
class Signal:
    id:          str           # UUID
    kind:        SignalKind
    workdir:     str           # 來源專案目錄
    timestamp:   str           # ISO 8601
    summary:     str           # 一行摘要（< 200 字），用於快速過濾
    raw_content: str           # 原始內容（diff / log / traceback 等）
    metadata:    dict          # 種類特定欄位（見下方）
    priority:    int = 5       # 1=最高, 10=最低，影響處理順序
```

**各種類的 metadata 結構**：

```python
# GIT_COMMIT
metadata = {
    "commit_hash": "abc1234",
    "author": "ahern",
    "message": "fix: login token expiry",
    "files_changed": ["auth.py", "tests/test_auth.py"],
    "diff_lines": 47,
}

# TEST_FAILURE
metadata = {
    "test_name": "test_jwt_expiry_handling",
    "file": "tests/test_auth.py",
    "error_type": "AssertionError",
    "error_message": "Expected 401, got 200",
    "consecutive_failures": 3,   # 連續失敗次數，越高 priority 越高
}

# KNOWLEDGE_GAP
metadata = {
    "query": "JWT RS256 configuration",
    "result_count": 0,
    "caller_tool": "get_context",
}

# MCP_TOOL_CALL
metadata = {
    "tool": "add_knowledge",
    "args_summary": "title=JWT..., kind=Pitfall",
    "success": True,
    "related_task": "fix login bug",
}
```

### 4.3 信號收集器實作位置

| 收集點 | 實作位置 | 觸發方式 | 階段 |
|--------|---------|---------|------|
| git commit | `extractor.py`（已有） | git hook | Phase 1 |
| task complete | `mcp_server.py` `complete_task` 內 | 工具呼叫時 | Phase 1 |
| MCP tool call | `mcp_server.py` middleware | 每次工具呼叫後 | Phase 2 |
| test failure | `pytest plugin` 或 CI webhook | pytest hook | Phase 2 |
| knowledge gap | `mcp_server.py` `get_context` 內 | 返回結果為空時 | Phase 3+ |

### 4.4 MCP 工具呼叫 Middleware

在 `mcp_server.py` 的工具呼叫外層加輕量觀察者：

```python
def _observe_tool_call(
    tool_name: str,
    args:      dict,
    result:    Any,
    workdir:   str,
) -> None:
    """非同步記錄工具呼叫信號，不阻塞主流程。"""
    # 只觀察有知識生產意義的工具
    OBSERVED_TOOLS = {
        "add_knowledge", "complete_task", "get_context",
        "batch_add_knowledge", "mark_helpful",
    }
    if tool_name not in OBSERVED_TOOLS:
        return

    summary = f"{tool_name}: {str(args)[:100]}"
    signal = Signal(
        id=str(uuid.uuid4()),
        kind=SignalKind.MCP_TOOL_CALL,
        workdir=workdir,
        timestamp=_now_iso(),
        summary=summary,
        raw_content=json.dumps({"args": args, "result_summary": str(result)[:200]}),
        metadata={"tool": tool_name, "success": result is not None},
        priority=8,  # 低優先，背景處理
    )
    # 非同步寫入佇列，不等待
    _signal_queue.put_nowait(signal)
```

---

## 5. Layer 2 — 信號佇列

### 5.1 設計目標

- **持久化**：進程重啟不遺失信號
- **有序處理**：priority queue，高優先先處理
- **去重**：同一 commit hash 或同一測試失敗不重複分析
- **背壓**：佇列滿時丟棄低優先信號（不阻塞主流程）

### 5.2 儲存後端

使用現有的 `.brain/brain.db` 新增 `signal_queue` 表：

```sql
CREATE TABLE IF NOT EXISTS signal_queue (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    workdir     TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    summary     TEXT NOT NULL,
    raw_content TEXT NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}',
    priority    INTEGER NOT NULL DEFAULT 5,
    status      TEXT NOT NULL DEFAULT 'pending',
      -- pending | processing | done | failed | skipped
    attempts    INTEGER NOT NULL DEFAULT 0,
    error       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    processed_at TEXT,

    -- 快速查詢索引
    CHECK (status IN ('pending','processing','done','failed','skipped'))
);

CREATE INDEX IF NOT EXISTS idx_signal_queue_status_priority
    ON signal_queue (status, priority, created_at);

-- 去重索引（同種類 + 同 workdir + 同內容摘要，24 小時內不重複）
CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_dedup
    ON signal_queue (kind, workdir, summary)
    WHERE status = 'pending';
```

### 5.3 佇列管理器

```python
class SignalQueue:
    MAX_QUEUE_SIZE = 500          # 超過時丟棄 priority >= 8 的信號
    MAX_PENDING_AGE_DAYS = 7      # 超過 7 天的 pending 自動標記 skipped
    MAX_ATTEMPTS = 3              # 最多重試 3 次

    def enqueue(self, signal: Signal) -> bool:
        """寫入信號。若佇列已滿且信號低優先，返回 False（丟棄）。"""

    def dequeue_batch(self, batch_size: int = 5) -> list[Signal]:
        """取出一批待處理信號（優先順序：priority ASC, created_at ASC）。"""

    def mark_done(self, signal_id: str, decision: KnowledgeDecision) -> None:
        """標記完成，同時寫入 signal_log。"""

    def mark_failed(self, signal_id: str, error: str) -> None:
        """標記失敗，attempts += 1，若達上限則改 status='failed'。"""

    def cleanup_stale(self) -> int:
        """清理過期 pending 信號，回傳清理數量。"""
```

---

## 6. Layer 3 — LLM 判斷引擎

這是整個管線的核心，也是 LLM 替代規則程式碼最徹底的地方。

### 6.1 判斷引擎介面

```python
class LLMJudgmentEngine:
    """
    接收信號 + 相關現有知識，輸出結構化的 KnowledgeDecision。
    唯一與 LLM API 溝通的元件。
    """

    def __init__(self, brain_db: BrainDB, config: PipelineConfig):
        self._db     = brain_db
        self._config = config
        self._llm    = _build_llm_client(config)   # 可插拔

    async def analyze(self, signal: Signal) -> KnowledgeDecision:
        """
        主要判斷入口。

        步驟：
        1. 從知識庫取出與信號相關的現有節點（context enrichment）
        2. 構建 prompt（信號 + 現有知識 + 判斷指引）
        3. 呼叫 LLM，要求結構化 JSON 輸出
        4. 驗證輸出格式
        5. 回傳 KnowledgeDecision
        """
        related = self._db.hybrid_search(signal.summary, limit=5)
        prompt  = self._build_prompt(signal, related)
        raw     = await self._llm.complete(prompt, response_format=KnowledgeDecision)
        return self._validate(raw)
```

### 6.2 判斷類型

**Phase 1 只需要兩種決策**（其餘四種是終態設計，Phase 3+ 實作）：

```python
# Phase 1 — 最小可行版本
class DecisionAction(str, Enum):
    ADD   = "add"   # 新增知識節點
    SKIP  = "skip"  # 信號不值得記錄
```

**Phase 3+ 完整版（供參考，不在 Phase 1 實作）**：

```python
# Phase 3+ — 視回饋數據決定是否實作
class DecisionAction(str, Enum):
    ADD          = "add"           # 新增知識節點
    UPDATE       = "update"        # 更新現有節點（補充內容或調整信心）
    MERGE        = "merge"         # 合併兩個相似節點（需向量相似度計算 + 邊重定向）
    CONTRADICT   = "contradict"    # 標記矛盾，建立 CONTRADICTS 邊（需人工確認工作流）
    SKIP         = "skip"          # 信號不值得記錄
    DEFER        = "defer"         # 需要更多資訊，暫緩（重新入佇列）
```

### 6.3 分析策略（依信號種類）

不同信號需要不同的判斷策略：

```python
# Phase 1 策略（只有 GIT_COMMIT + TASK_COMPLETE）
ANALYSIS_STRATEGY: dict[SignalKind, AnalysisStrategy] = {
    SignalKind.GIT_COMMIT: AnalysisStrategy(
        prompt_template  = COMMIT_ANALYSIS_PROMPT,
        max_input_tokens = 2000,   # diff 截斷長度
        expected_kinds   = ["Decision", "Rule", "Pitfall", "ADR"],
        min_confidence   = 0.5,
    ),
    SignalKind.TASK_COMPLETE: AnalysisStrategy(
        prompt_template  = TASK_COMPLETE_PROMPT,
        max_input_tokens = 1500,
        expected_kinds   = ["Decision", "Pitfall", "Rule"],
        min_confidence   = 0.65,
    ),

    # ── Phase 2 新增 ──────────────────────────────────────────
    SignalKind.TEST_FAILURE: AnalysisStrategy(
        prompt_template  = TEST_FAILURE_PROMPT,
        max_input_tokens = 800,
        expected_kinds   = ["Pitfall"],
        min_confidence   = 0.6,
        gate = lambda s: s.metadata.get("consecutive_failures", 1) >= 3,
    ),

    # ── Phase 3+（待數據決定是否啟用）──────────────────────────
    # SignalKind.KNOWLEDGE_GAP: AnalysisStrategy(...)
    # 原設計：記錄知識空白為 Note 節點；但 Note 節點的消費者未定義，
    # 實際效益待 Phase 2 結束後的數據驗證再決定。
}
```

### 6.4 Context Enrichment（關鍵設計）

在送 LLM 之前，先把現有相關知識附上，讓 LLM 能做更準確的判斷（避免重複新增、正確識別矛盾）：

```python
def _enrich_context(self, signal: Signal) -> list[dict]:
    """
    取出與信號最相關的現有節點，作為 LLM 判斷的參考。
    """
    # 1. 語意搜尋（hybrid FTS + vector）
    semantic = self._db.hybrid_search(
        signal.summary, limit=5
    )

    # 2. 如果是 git commit，額外搜尋最近相關的決策
    if signal.kind == SignalKind.GIT_COMMIT:
        files = signal.metadata.get("files_changed", [])
        for f in files[:3]:
            file_nodes = self._db.search_nodes(
                Path(f).stem, node_type="Decision", limit=2
            )
            semantic.extend(file_nodes)

    # 去重並回傳
    seen = set()
    result = []
    for n in semantic:
        if n["id"] not in seen:
            seen.add(n["id"])
            result.append({
                "id":         n["id"],
                "title":      n["title"],
                "kind":       n.get("type", "Note"),
                "confidence": n.get("confidence", 0.5),
                "summary":    (n.get("content") or "")[:150],
            })
    return result[:8]
```

### 6.5 合成引擎（Episode → Semantic 晉升）

> **⚠ Phase 4 — 視數據決定是否實作**
>
> SynthesisEngine 依賴一個未驗證的假設：
> **三個低信心的相似節點合成後會產生一個高信心的好節點**。
> 這個假設在沒有真實數據之前無法驗證——三個低品質片段合成的結果可能仍是低品質。
>
> **實作前提條件**（缺一不可）：
> 1. 管線已跑至少 4 週，累積 ≥ 200 個 auto_pipeline 節點
> 2. 其中至少 50 個節點有 `report_knowledge_outcome` 回饋
> 3. 人工抽樣確認 auto 節點的有用率 ≥ 50%（劣質原料不值得合成）
>
> 設計細節見附錄 A（完整 `SynthesisEngine` 程式碼草稿保留供未來參考）。

---

## 7. Layer 4 — 確定性執行器

### 7.1 設計原則

Executor 是**無腦執行者**：不做任何判斷，只把 `KnowledgeDecision` 翻譯成確定性的 DB 操作。

```python
class KnowledgeExecutor:
    """
    執行 LLM 的決策。
    不含任何業務邏輯，只有 DB 操作。
    所有操作都在 SQLite 事務內執行。
    """

    def run(self, decision: KnowledgeDecision, signal: Signal) -> ExecutionResult:
        # Phase 1：只有 ADD 和 SKIP
        dispatch = {
            DecisionAction.ADD:  self._do_add,
            DecisionAction.SKIP: self._do_skip,
            # Phase 3+ — 暫未實作：
            # DecisionAction.UPDATE:     self._do_update,
            # DecisionAction.MERGE:      self._do_merge,
            # DecisionAction.CONTRADICT: self._do_contradict,
            # DecisionAction.DEFER:      self._do_defer,
        }
        handler = dispatch.get(decision.action)
        if handler is None:
            logger.warning("executor: unsupported action %s, treating as skip", decision.action)
            return ExecutionResult(ok=True, skipped=True)
        return handler(decision, signal)
```

### 7.2 各操作實作

**ADD**：
```python
def _do_add(self, d: KnowledgeDecision, signal: Signal) -> ExecutionResult:
    node_id = self._brain.add_knowledge(
        title       = d.node.title,
        content     = d.node.content,
        kind        = d.node.kind,
        confidence  = d.node.confidence,
        tags        = d.node.tags,
        description = d.node.description,
    )
    # 標記來源（可用於品質追蹤）
    self._db.conn.execute(
        "UPDATE nodes SET meta = json_set(meta, '$.source', ?, '$.signal_id', ?) WHERE id = ?",
        ("auto_pipeline", signal.id, node_id)
    )
    self._db.conn.commit()
    return ExecutionResult(ok=True, node_id=node_id)
```

**MERGE**：
```python
def _do_merge(self, d: KnowledgeDecision, signal: Signal) -> ExecutionResult:
    # 保留 confidence 高者的 id；合併 content；重定向邊
    keep_id   = d.merge.keep_node_id
    drop_id   = d.merge.drop_node_id
    keep_node = self._db.get_node(keep_id)
    drop_node = self._db.get_node(drop_id)

    with self._db._write_lock:
        # 合併內容
        merged_content = keep_node["content"] + "\n\n---\n" + drop_node["content"]
        merged_tags    = list(set(keep_node["tags"] + drop_node["tags"]))

        self._graph.update_node(keep_id, content=merged_content, tags=merged_tags)

        # 重定向邊
        self._db.conn.execute(
            "UPDATE edges SET source_id = ? WHERE source_id = ?",
            (keep_id, drop_id)
        )
        self._db.conn.execute(
            "UPDATE edges SET target_id = ? WHERE target_id = ?",
            (keep_id, drop_id)
        )

        # 廢棄被合併節點
        self._db.conn.execute(
            "UPDATE nodes SET is_deprecated = 1, meta = json_set(meta, '$.merged_into', ?) WHERE id = ?",
            (keep_id, drop_id)
        )
        self._db.conn.commit()
```

**CONTRADICT**：
```python
def _do_contradict(self, d: KnowledgeDecision, signal: Signal) -> ExecutionResult:
    # 建立 CONTRADICTS 邊
    self._graph.add_edge(
        d.contradict.node_a_id,
        d.contradict.node_b_id,
        relation="CONTRADICTS",
        note=d.reason,
        confidence=0.7,
    )
    # 兩個節點信心降低（矛盾存在時，各自可信度下降）
    for nid in [d.contradict.node_a_id, d.contradict.node_b_id]:
        node = self._db.get_node(nid)
        if node:
            new_conf = max(0.1, node["confidence"] - 0.1)
            self._graph.update_node(nid, confidence=new_conf)
    # 產生 nudge question（讓人工確認哪個更正確）
    self._nudge.create_question(
        node_ids=[d.contradict.node_a_id, d.contradict.node_b_id],
        question=f"這兩個節點似乎互相矛盾，哪一個更準確？原因為何？",
    )
```

---

## 8. Layer 5 — 回饋迴路

### 8.1 自動品質追蹤

每個 auto_pipeline 產生的節點都追蹤以下指標：

```sql
CREATE TABLE IF NOT EXISTS pipeline_metrics (
    node_id       TEXT NOT NULL,
    signal_id     TEXT NOT NULL,
    action        TEXT NOT NULL,      -- add/merge/update/...
    llm_model     TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    was_useful    INTEGER,            -- NULL=未評估, 1=有用, 0=無用
    feedback_at   TEXT,
    feedback_note TEXT,

    FOREIGN KEY (node_id) REFERENCES nodes(id)
);
```

### 8.2 自動品質信號

不需要人工介入，系統可自動判斷部分品質信號：

```python
class AutoFeedbackCollector:

    def collect_implicit_feedback(self):
        """每日執行，收集隱含的品質信號。"""

        # 信號 1：auto_pipeline 節點被 get_context 返回且未被 mark_helpful(False)
        # → 推斷為有用（弱信號，confidence += 0.02）

        # 信號 2：auto_pipeline 節點在 30 天內從未被 get_context 返回
        # → 推斷為無用或不相關（confidence -= 0.05）

        # 信號 3：auto_pipeline 產生的 Pitfall 節點，
        # 且在之後的 commit 中同一文件的測試從失敗變通過
        # → 推斷 Pitfall 記錄了真實問題（confidence += 0.1）
```

### 8.3 Prompt 品質追蹤

```python
class PromptPerformanceTracker:
    """追蹤不同 prompt 版本的知識生產品質。"""

    def record(self,
        prompt_version: str,
        signal_kind:    SignalKind,
        decision:       KnowledgeDecision,
        was_useful:     bool | None,
    ) -> None:
        ...

    def get_report(self) -> dict:
        """回傳各 prompt 版本的有用率，供人工調整 prompt 參考。"""
        ...
```

---

## 9. 資料模型

### 9.1 KnowledgeDecision（LLM 輸出格式）

**Phase 1 精簡版（實際實作此版本）**：

```python
from pydantic import BaseModel, Field
from typing import Literal, Optional

class NodeSpec(BaseModel):
    title:       str   = Field(max_length=200)
    content:     str   = Field(max_length=2000)
    kind:        Literal["Note", "Decision", "Pitfall", "Rule", "ADR"]
    confidence:  float = Field(ge=0.3, le=0.85)  # auto 最高 0.85
    tags:        list[str] = Field(default_factory=list, max_items=10)
    description: str   = Field(default="", max_length=300)

class KnowledgeDecision(BaseModel):
    action:     Literal["add", "skip"]  # Phase 1 只有兩種
    reason:     str                     # LLM 的決策理由（可審計）
    confidence: float = Field(ge=0.0, le=1.0)  # LLM 對自身判斷的信心
    node:       Optional[NodeSpec] = None       # ADD 時必填

    # 品質保證
    signal_id:  str   # 來源信號 ID（必填，用於審計）
    llm_model:  str   # 使用的模型版本
```

**Phase 3+ 完整版（供參考，不在 Phase 1 實作）**：

```python
class MergeSpec(BaseModel):
    keep_node_id: str
    drop_node_id: str
    reason:       str

class ContradictSpec(BaseModel):
    node_a_id: str
    node_b_id: str

class KnowledgeDecision(BaseModel):
    action:      DecisionAction          # 六種完整 action
    reason:      str
    confidence:  float
    node:        Optional[NodeSpec]       = None  # ADD / UPDATE
    update_id:   Optional[str]            = None  # UPDATE
    merge:       Optional[MergeSpec]      = None  # MERGE
    contradict:  Optional[ContradictSpec] = None  # CONTRADICT
    signal_id:   str
    llm_model:   str
```

### 9.2 PipelineConfig

```python
@dataclass
class PipelineConfig:
    # LLM 設定
    llm_provider:     str   = "anthropic"   # anthropic | openai | ollama
    llm_model:        str   = "claude-haiku-4-5-20251001"  # 預設用 Haiku 節省成本
    llm_timeout:      int   = 30
    llm_max_retries:  int   = 3

    # 信號過濾
    min_signal_priority: int   = 9    # 只處理 priority <= 9 的信號
    gate_test_failures:  int   = 3    # 測試失敗累積幾次才觸發

    # 合成設定
    promote_threshold:   int   = 3    # 幾個 draft → 促進合成
    synthesis_interval:  int   = 86400  # 合成週期（秒）

    # 佇列設定
    worker_batch_size:   int   = 5    # 每次從佇列取幾個
    worker_interval:     int   = 60   # worker 輪詢間隔（秒）
    max_queue_size:      int   = 500
```

---

## 10. Prompt 設計

### 10.1 Git Commit 分析 Prompt

```
SYSTEM:
你是一個工程知識提取專家。你的任務是分析 git commit 內容，
判斷其中是否包含值得記錄到知識庫的工程知識。

知識類型定義：
- Decision：重要的技術選擇或架構決策，以及背後的理由
- Rule：必須遵守的規範或限制
- Pitfall：已知的陷阱、Bug 模式或容易犯的錯誤
- ADR：影響整體架構的重大決策
- Note：有用的背景資訊，但不屬於以上類型
- skip：commit 不包含值得記錄的知識（例如：純格式調整、版本號更新）

現有相關知識（避免重複）：
{related_nodes_json}

輸出規則：
1. 輸出必須是合法的 JSON，符合 KnowledgeDecision schema
2. confidence 在 0.4～0.85 之間（自動提取，非人工驗證）
3. 若不確定，選擇 skip 而非輸出低品質知識
4. reason 欄位必須解釋決策依據

USER:
分析以下 git commit：

Commit: {commit_hash}
Author: {author}
Message: {message}

Changed files: {files_changed}

Diff:
{diff_truncated}
```

### 10.2 測試失敗 Prompt

```
SYSTEM:
你是一個工程 Pitfall 記錄專家。測試失敗通常揭露了值得記錄的陷阱。

已連續失敗 {consecutive_failures} 次的測試代表這是個真實且持續的問題，
值得以較高的 confidence 記錄。

現有相關知識：
{related_nodes_json}

USER:
以下測試持續失敗，請提取 Pitfall 知識：

測試檔案：{file}
測試名稱：{test_name}
錯誤類型：{error_type}
錯誤訊息：{error_message}

最近的相關 commit：{recent_commits}
```

### 10.3 合成 Prompt（Episode → Semantic）

```
SYSTEM:
你是一個知識合成專家。以下是多個來自不同時間點、描述相似問題的知識片段。
你的任務是將它們合成為一個更完整、更高品質的知識節點。

合成規則：
1. 保留所有片段中的重要資訊，不能遺漏
2. 消除重複，保持簡潔
3. 若片段間有矛盾，在 content 中明確說明（不要選邊站）
4. confidence 可以比原始片段高，但不超過 0.85
5. kind 選擇最能代表合成結果的類型

USER:
請合成以下 {count} 個知識片段：

{fragments_json}
```

### 10.4 矛盾偵測 Prompt

```
SYSTEM:
你需要判斷兩個知識節點是否互相矛盾。

矛盾的定義：兩個節點描述的是相同或相關的主題，但給出了不相容的建議、
事實或結論（不只是觀點不同，而是實際上不能同時為真）。

USER:
節點 A（id: {id_a}）：
標題：{title_a}
內容：{content_a}

節點 B（id: {id_b}）：
標題：{title_b}
內容：{content_b}

這兩個節點是否矛盾？如果是，請輸出 CONTRADICT action；
如果不是，請輸出 SKIP。
```

---

## 11. 非同步管線設計

### 11.1 背景 Worker 架構

```python
class PipelineWorker:
    """
    背景 worker，定期從佇列取出信號並送 LLM 分析。
    與 decay daemon、session cleanup daemon 並行運行。
    """

    def __init__(self, brain: ProjectBrain, config: PipelineConfig):
        self._brain    = brain
        self._config   = config
        self._queue    = SignalQueue(brain.db)
        self._engine   = LLMJudgmentEngine(brain.db, config)
        self._executor = KnowledgeExecutor(brain)
        self._running  = False

    def start(self) -> threading.Thread:
        t = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="brain-knowledge-pipeline",
        )
        t.start()
        self._running = True
        return t

    def _worker_loop(self):
        while True:
            time.sleep(self._config.worker_interval)
            try:
                self._process_batch()
            except Exception as e:
                logger.debug("pipeline worker error: %s", e)

    def _process_batch(self):
        signals = self._queue.dequeue_batch(self._config.worker_batch_size)
        if not signals:
            return

        for signal in signals:
            try:
                # 策略門控：此種信號現在值得分析嗎？
                strategy = ANALYSIS_STRATEGY.get(signal.kind)
                if strategy and strategy.gate and not strategy.gate(signal):
                    self._queue.mark_skipped(signal.id, "gate not met")
                    continue

                # 非同步 LLM 分析
                decision = asyncio.run(self._engine.analyze(signal))
                result   = self._executor.run(decision, signal)
                self._queue.mark_done(signal.id, decision)

            except (RateLimitError, TimeoutError) as e:
                self._queue.mark_failed(signal.id, str(e))
                # 速率問題：暫停後重試
                time.sleep(30)

            except Exception as e:
                self._queue.mark_failed(signal.id, str(e))
                logger.warning("pipeline: signal %s failed: %s", signal.id, e)
```

### 11.2 主流程不受影響

```python
# mcp_server.py 的 get_context — 完全同步，不等 pipeline
@mcp.tool()
def get_context(task: str, workdir: str = "") -> str:
    _rate_check()
    b = _resolve_brain(workdir)

    # 知識查詢（同步，毫秒級）
    result = b.get_context(task)

    # KNOWLEDGE_GAP 信號收集屬 Phase 3+（見 4.1 節），此處暫不實作

    return result  # 立即回傳，不等 pipeline
```

---

## 12. 可靠性與 Fallback

### 12.1 三級 Fallback

```
Level 1：LLM API 超時或速率限制
  → 信號保留在佇列（status='pending'），稍後重試
  → 主流程完全不受影響

Level 2：LLM API 完全不可用（API key 失效或服務中斷）
  → 所有新信號進入佇列，暫停 LLM 分析
  → 系統繼續提供知識查詢和手動寫入
  → 每小時嘗試一次 health check，可用後恢復處理

Level 3：本地模型 Fallback（可選配置）
  → 設定 fallback_llm_provider = "ollama"
  → 雲端不可用時，切換本地 Llama/Qwen 模型
  → 品質較低但維持運作
```

### 12.2 冪等性保證

```python
# 每個 KnowledgeDecision 帶有 signal_id
# 若因 crash 導致重複執行，通過 signal_id 去重

def _do_add(self, d: KnowledgeDecision, signal: Signal) -> ExecutionResult:
    # 檢查是否已處理過這個 signal
    existing = self._db.conn.execute(
        "SELECT node_id FROM pipeline_metrics WHERE signal_id = ? AND action = 'add'",
        (signal.id,)
    ).fetchone()
    if existing:
        return ExecutionResult(ok=True, node_id=existing[0], skipped=True)

    # 正常執行...
```

### 12.3 輸出驗證

```python
def _validate(self, raw: dict) -> KnowledgeDecision:
    """Pydantic 驗證 LLM 輸出，不合格則拋出 ValueError。"""
    try:
        decision = KnowledgeDecision(**raw)
    except ValidationError as e:
        logger.warning("LLM output validation failed: %s", e)
        # 無效輸出視為 SKIP
        return KnowledgeDecision(
            action=DecisionAction.SKIP,
            reason=f"LLM output invalid: {e}",
            confidence=0.0,
            signal_id=raw.get("signal_id", ""),
            llm_model="unknown",
        )

    # 額外安全檢查
    if decision.node and decision.node.confidence > 0.85:
        decision.node.confidence = 0.85  # auto 上限

    return decision
```

---

## 13. 與現有 Project Brain 整合

### 13.1 整合點一覽

```
現有元件                    整合方式
────────────────────────────────────────────────────────────
mcp_server.create_server()  啟動 PipelineWorker daemon
mcp_server._observe()       新增，每次工具呼叫後發信號
decay daemon (FEAT-01)      每日額外執行 SynthesisEngine
extractor.py                改為同時寫入 SignalQueue（不只 brain.add_knowledge）
brain.db (brain.db)         新增 signal_queue + pipeline_metrics 表
NudgeEngine                 接收 CONTRADICT 信號產生 question
report_knowledge_outcome    同時更新 pipeline_metrics
```

### 13.2 新增 MCP 工具

```python
@mcp.tool()
def pipeline_status(workdir: str = "") -> dict:
    """查看自動知識生產管線狀態。"""
    # 返回：佇列大小、待處理數、今日處理數、成功率、最近決策

@mcp.tool()
def trigger_synthesis(workdir: str = "") -> dict:
    """手動觸發合成（不等下次 daemon 週期）。"""

@mcp.tool()
def review_auto_knowledge(
    limit:   int = 10,
    workdir: str = "",
) -> list[dict]:
    """列出最近由管線自動產生、尚未人工確認的知識節點。"""
```

### 13.3 config.json 新增欄位

```json
{
  "pipeline": {
    "enabled": true,
    "llm_model": "claude-haiku-4-5-20251001",
    "worker_interval_seconds": 60,
    "gate_test_failures": 3,
    "promote_threshold": 3,
    "max_auto_confidence": 0.85,
    "observe_tools": ["add_knowledge", "complete_task", "get_context"]
  }
}
```

---

## 14. 測試策略

### 14.1 單元測試（不需要 LLM）

```python
class TestKnowledgeExecutor:
    """測試執行器——mock KnowledgeDecision 輸入，驗證 DB 狀態。"""

    def test_add_creates_node(self, tmp_path):
        decision = KnowledgeDecision(
            action=DecisionAction.ADD,
            node=NodeSpec(title="JWT RS256", content="...", kind="Rule", confidence=0.7),
            reason="test",
            signal_id="sig-001",
            llm_model="mock",
            confidence=0.9,
        )
        executor = KnowledgeExecutor(ProjectBrain(tmp_path))
        result = executor.run(decision, mock_signal())
        assert result.ok
        assert result.node_id != ""

    def test_merge_redirects_edges(self, tmp_path):
        ...

    def test_contradict_lowers_confidence(self, tmp_path):
        ...

    def test_idempotent_on_same_signal(self, tmp_path):
        ...
```

### 14.2 整合測試（mock LLM）

```python
class TestPipelineWorker:
    def test_processes_git_commit_signal(self, tmp_path, mock_llm):
        mock_llm.returns(KnowledgeDecision(action=ADD, ...))
        worker = PipelineWorker(brain, config_with_mock_llm)

        queue.enqueue(git_commit_signal())
        worker._process_batch()

        # 驗證知識節點已產生
        results = brain.db.search_nodes("JWT")
        assert len(results) > 0
        assert results[0]["meta"]["source"] == "auto_pipeline"
```

### 14.3 Prompt 品質評估（定期人工審計）

```
評估方式：
  1. 每週從 pipeline_metrics 隨機抽取 20 個 auto 節點
  2. 人工評分：有用 / 無用 / 有問題
  3. 記錄到 pipeline_metrics.was_useful
  4. 計算各 signal_kind 的有用率
  5. 有用率 < 50% 的 signal_kind 暫停，調整 prompt 後重啟
```

---

## 15. 風險與對策

| 風險 | 嚴重度 | 對策 |
|------|-------|------|
| LLM 幻覺產生錯誤知識 | 高 | 1. auto confidence 上限 0.85；2. source 標記可過濾；3. review_auto_knowledge 工具人工確認 |
| API 費用超出預期 | 中 | 1. 優先使用 Haiku（低成本）；2. gate 條件過濾低品質信號；3. 每日 token 用量上限 |
| 知識庫被大量低品質節點污染 | 高 | 1. 自動信心衰減（decay daemon）；2. 有用率追蹤 + 自動停用劣質信號；3. 隔離 auto 節點（可過濾查詢） |
| 管線 worker 消耗過多資源 | 低 | 1. daemon=True 可被主進程管控；2. worker_interval 可設定（降低輪詢頻率）；3. LLM 呼叫全為非同步 |
| 信號佇列無限增長 | 低 | 1. MAX_QUEUE_SIZE 限制；2. 7 天 pending 自動 skipped；3. 低優先信號在佇列滿時丟棄 |
| 多個 Brain 實例競爭處理 | 中 | SQLite 的 signal_queue 透過樂觀鎖（status CAS）確保每個信號只被一個 worker 處理 |

---

## 16. 實作路線圖

### Phase 1 — 基礎設施（約 2 週）

目標：管線可以跑，但 LLM 邏輯最簡單。

```
□ signal_queue + pipeline_metrics 表 schema
□ Signal dataclass + SignalQueue 類別
□ KnowledgeDecision Pydantic model
□ KnowledgeExecutor（ADD / SKIP 兩種操作即可）
□ PipelineWorker（基礎 daemon loop）
□ mcp_server._observe() middleware（只觀察 complete_task）
□ create_server() 啟動 worker daemon
□ 單元測試覆蓋 Executor
```

**可交付物**：Worker 在背景跑，`complete_task` 的 pitfalls/lessons 自動進入佇列，LLM 分析後寫入知識庫。

### Phase 2 — 信號擴展（約 1 週）

```
□ MCP 工具呼叫 middleware（add_knowledge / complete_task）
□ TEST_FAILURE 信號收集（pytest plugin 或 CLI 整合）
□ gate 條件（累積次數 >= N 才觸發）
□ pipeline_status MCP 工具
□ review_auto_knowledge MCP 工具
```

### Phase 3 — 完整判斷（約 2 週，視 Phase 2 數據決定範圍）

```
□ UPDATE 執行器操作
□ MERGE 執行器操作（需向量相似度計算）
□ CONTRADICT 執行器操作 + NudgeEngine 整合（需人工確認工作流）
□ AutoFeedbackCollector（隱含回饋收集）
□ PromptPerformanceTracker
```

### Phase 4 — 調優與可觀測性（持續，視數據決定）

```
□ SynthesisEngine（Episode → Semantic 晉升）
   前提：≥ 200 個 auto 節點 + ≥ 50 個有回饋 + 有用率 ≥ 50%（見 6.5 節）
□ KNOWLEDGE_GAP 信號（get_context 空結果）
   前提：確定 Note 節點的消費者和用途
□ 本地模型 Fallback（Ollama）
□ token 用量統計與上限
□ Prompt 版本管理
□ 有用率報表（pipeline report 指令）
□ 矛盾解消工作流（人工確認 UI）
□ trigger_synthesis MCP 工具
```

---

## 17. 成本與效能估算

### LLM 呼叫頻率估算

```
信號種類              預估每日信號數    門控後送 LLM 比例    每日 LLM 呼叫    階段
──────────────────────────────────────────────────────────────────────────
git_commit            5-20              100%                5-20           Phase 1
task_complete         3-10              100%                3-10           Phase 1
test_failure          0-10             只有累積 ≥3          0-3            Phase 2
──────────────────────────────────────────────────────────────────────────
Phase 1 合計                                               8-30 次/日
Phase 1+2 合計                                             8-33 次/日
```

### 費用估算（使用 claude-haiku-4-5）

```
每次呼叫 input tokens：約 1500（信號 + 相關節點 + prompt）
每次呼叫 output tokens：約 300（KnowledgeDecision JSON）

Haiku 價格：$0.80/M input tokens，$4.00/M output tokens

Phase 1 典型日費用（20 次/日）：
  input：20 × 1500 × $0.80/1M = $0.024
  output：20 × 300  × $4.00/1M = $0.024
  合計：~$0.05/日 = ~$1.50/月

極端情況（密集開發，100+ commits/日）：~$0.24/日 = ~$7/月
```

> **免責聲明**：以上費用假設每日 commit 頻率均勻分佈。實際情況：
> - 密集開發日可達 10× 平均值（sprint 衝刺、重構日）
> - 休假/停工日為零
> - 若使用本地 Ollama 模型（Gemma 4 / Llama 等），費用為零
>
> 建議在 `PipelineConfig` 設定 `daily_token_limit`，達到上限後當日暫停，避免費用失控。

### 效能影響

```
指標                    影響
────────────────────────────────────────────────────────────
主流程延遲              零（完全非同步）
SQLite 寫入競爭         輕微（signal_queue 寫入 < 1ms）
記憶體佔用              +~5MB（worker thread + 佇列）
磁碟佔用               +~10MB/年（signal_log 紀錄）
```

---

## 18. 設計決策記錄

以下問題在評估後已有定論：

1. **LLM 模型選擇** ✓
   - **決定**：ADD/SKIP 使用本地 Gemma 4（Ollama），費用為零
   - MERGE/SYNTHESIZE 延至 Phase 3+ 再決定模型，目前不需要選
   - 雲端備援：若本地模型不可用，降級至 Haiku（低成本）

2. **信號保留時間** ✓
   - **決定**：`signal_queue` 已處理記錄保留 **30 天**（除錯用途），之後清理
   - `signal_log`（審計紀錄）**永久保留**，但壓縮 `raw_content` 只保留摘要（< 500 chars）
   - 目前設計的 7 天太短，線上問題追查往往需要兩週以上

3. **矛盾處理的人工介入** ✓
   - **決定**：寫入 `CONTRADICTS` 邊，標記雙方節點，**不自動解消**
   - LLM 不選邊，人工決定哪個更準確後，loser 節點標記為 deprecated
   - 自動解消的風險高於保留矛盾狀態：一旦選錯就是靜默的錯誤知識

4. **分散式場景（多 Claude Code 實例競爭）** ✓
   - **決定**：現有 SQLite WAL + CAS 操作夠用
   - 實作：`UPDATE signal_queue SET status='processing', worker_id=? WHERE id=? AND status='pending'`
   - 不需要額外的分散式鎖設計，SQLite WAL 模式 + `busy_timeout=5000` 可處理

5. **回溯處理（現有 git history）** ✓
   - **決定**：提供 `brain pipeline backfill --since 30d` 指令，**預設關閉**
   - 回溯時必須加速率限制（每分鐘最多 N 次 LLM 呼叫），避免一次打爆 2 年 history
   - 建議從 `--since 7d` 開始試跑，驗證品質後再擴大範圍

---

---

## 附錄 A — SynthesisEngine 設計草稿（Phase 4 參考）

> 以下程式碼**不在任何當前 Phase 實作範圍內**。
> 待 Phase 2 結束後，根據累積數據決定是否進入 Phase 4。

```python
class SynthesisEngine:
    """
    跨 session 模式識別：
    多個低信心的相似信號 → 合成一個高信心的正式知識節點

    前提條件（見 6.5 節）：
    - ≥ 200 個 auto_pipeline 節點
    - ≥ 50 個有 report_knowledge_outcome 回饋
    - 人工抽樣有用率 ≥ 50%
    """
    PROMOTE_THRESHOLD = 3       # 最少幾個片段才觸發合成
    SIMILARITY_THRESHOLD = 0.78 # 語意相似度門檻

    async def run_synthesis_pass(self) -> SynthesisReport:
        drafts   = self._db.search_nodes(
            "", node_type=None, limit=200,
            filters={"source": "auto_pipeline", "max_confidence": 0.65}
        )
        clusters = self._cluster_by_similarity(drafts)
        for cluster in clusters:
            if len(cluster) >= self.PROMOTE_THRESHOLD:
                decision = await self._llm.synthesize(cluster)
                self._executor.run(decision)
```

---

*文件版本 v0.2 — Phase 1 可實作*
