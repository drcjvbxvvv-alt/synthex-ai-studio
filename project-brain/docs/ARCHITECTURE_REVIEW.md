# Project Brain — 系統反思與重構架構書

> *「任何號稱『完美無缺』的系統都是在實驗室裡的玩具，承認缺陷，正是走向偉大的開始。」*

**文件版本**：v1.1
**撰寫日期**：2026-04-09
**更新日期**：2026-04-09（Phase 1 完成）
**基準版本**：v0.31.0 (231 nodes / 140 edges / 860 passed)
**分析方法**：程式碼靜態審查 + Brain 歷史 Pitfall 回溯 + 交叉驗證
**適用範圍**：此文件是誠實的自我檢討。所有缺陷附檔案:行號可驗證，非臆測。

---

## 目錄

1. [核心結論](#1-核心結論)
2. [系統現況全景](#2-系統現況全景)
3. [已驗證的真實缺陷](#3-已驗證的真實缺陷)
4. [Myth Bust：非缺陷項目釐清](#4-myth-bust非缺陷項目釐清)
5. [優先修復矩陣](#5-優先修復矩陣)
6. [重構藍圖](#6-重構藍圖)
7. [功能深度強化方向](#7-功能深度強化方向)
8. [未來路線圖](#8-未來路線圖)
9. [實作指引](#9-實作指引)

---

## 1. 核心結論

### 1.1 系統整體健康度（含模型建議）

> **兩欄模型的含義**：
> - **開發 Model**：實作/重構此維度時，Claude Code 應使用的模型（依複雜度與風險評估）
> - **運行 Model**：此維度若有運行時 LLM 呼叫，應透過 `brain.toml` 指定的模型
> - `—` 表示該維度不需要 LLM（純資料層或規則引擎）

| 維度 | 評估 | 說明 | 開發 Model | 運行 Model (brain.toml) |
|------|------|------|-----------|------------------------|
| **L3 知識圖譜核心** | 🟢 穩固 | 231 節點 / 140 邊，schema v22 穩定，WAL 並發安全 | **Sonnet 4.6** (schema 變更需事務知識) | — |
| **L2 情節記憶** | 🟢 穩固 | SQLite 替代 FalkorDB，零依賴運作正常 | **Sonnet 4.6** | `[pipeline.llm]` gemma4:27b（memory_synthesizer 呼叫） |
| **L1a 工作記憶** | 🟢 穩固 | SessionStore 有完整 TTL + cleanup daemon | **Haiku 4.5** (純資料層) | — |
| **資料正確性** | 🟡 可改進 | BUG-02/BUG-B02 已修，但雙 DB 同步仍是風險點 | **Sonnet 4.6** (事務邊界分析) | — |
| **並發安全** | 🟡 可改進 | _write_guard 覆蓋良好，但 graph.py 未使用 version CAS | **Sonnet 4.6** (CAS 邏輯審慎) | — |
| **自動管線** | 🔴 半成品 | Layer 1/2/4 完成，Layer 3 LLM 判斷引擎**整層缺失** | **Opus 4.6 (1M)** (新模組架構設計 + prompt engineering) | `[pipeline.llm]` gemma4:27b → gemma4:31b → Haiku 4.5 fallback |
| **Federation** | 🔴 未驗證 | 849 行代碼，**零專用測試**，外部訂閱未驗證 | **Sonnet 4.6** (測試編寫) | — (純資料序列化) |
| **測試覆蓋** | 🟢 良好 | 975 個測試，核心模組覆蓋完整 | **Sonnet 4.6** / **Haiku 4.5** (新增單元測試) | — |
| **可觀測性** | 🟡 可改進 | 結構化 logging (OPT-09) 已做，但缺 metrics dashboard | **Sonnet 4.6** (dashboard 整合) | — |
| **KRB 審查** | 🟢 穩固 | KRBAIAssistant + auto_approve | **Sonnet 4.6** | `[review.model]` gemma4:31b（Dense，品質優先） |
| **知識驗證** | 🟡 可改進 | KnowledgeValidator 三階段但未 CI 集成 | **Sonnet 4.6** | Claude Haiku 4.5（成本優化，只做分類） |
| **知識蒸餾 (LoRA)** | ⚪ 未啟動 | Layer 1-2 實作，Layer 3 LoRA 待 GPU | **Opus 4.6 (1M)** (研究級複雜度) | 訓練：本地 GPU；推論：LoRA adapter |
| **Nudge Engine** | 🟢 穩固 | OPT-07 已套用 effective_confidence | **Haiku 4.5** | — (零費用原則，不用 LLM) |
| **Decay Engine** | 🟢 穩固 | F1-F7 因子，BUG-02/B02 已修 | **Sonnet 4.6** (多因子調參) | — (純規則引擎) |

### 1.2 一句話診斷

> **Project Brain v0.30.0 核心穩健，但自動化知識生產管線尚在「有骨骼、有肌肉、但神經未通」的狀態 —— SignalQueue 能收集，KnowledgeExecutor 能寫入，中間的 LLM 判斷引擎整層缺席。**

### 1.3 本次反思最重要的三個發現

1. **🔴 Pipeline Layer 3 完全未實作**：
   `pipeline.py` 的 docstring (line 283) 寫「由 LLMJudgmentEngine 產生」，但全 codebase grep 結果只在設計文件出現，**實作為零**。signal 會被收集但永遠不會被分析。

2. **🟡 Review Board approve() 雙資料庫寫入無協調**：
   `review_board.py:409-420` 顯示 KnowledgeGraph 已寫入成功時，BrainDB FTS5 同步失敗**只記 warning**，但 staged_nodes 仍被標記為 approved。造成「L3 有節點，FTS5 搜不到」的長期不一致。

3. **🟢 先前擔憂的多數缺陷已修復**：
   decay_engine 日期基準、雙重衰減、FTS5 事務原子化、Rate Limit 並發安全、Symlink 遍歷防護 —— 這些都在 v0.25~v0.30 的 Bug Blitz 中修復，系統比外界印象穩固。

### 1.4 模型配置哲學

> 此節明確定義本文件中「開發 Model」與「運行 Model」的選擇邏輯，所有後續章節的模型標註都依此準則。

#### 1.4.1 開發 Model 選擇原則（Claude Code）

| Claude 模型 | 適用場景 | 判準 |
|-------------|---------|------|
| **Haiku 4.5** `claude-haiku-4-5-20251001` | 瑣碎修補、單行改動、純測試 CRUD | 工作量 < 1h；單檔 / < 20 行；無事務風險；無跨模組影響 |
| **Sonnet 4.6** `claude-sonnet-4-6` | 標準功能實作、測試編寫、一般重構、安全修補 | 工作量 1-12h；跨 2-4 個檔案；需事務或並發思考；需測試搭配 |
| **Opus 4.6 (1M context)** `claude-opus-4-6[1m]` | 架構設計、新模組、複雜重構、大範圍影響 | 工作量 > 12h；跨 5+ 檔案；需長 context；設計級決策；研究性問題 |

**判斷順序**（由上往下）：
1. 修改是否涉及架構設計 / 新建模組？ → **Opus 4.6**
2. 修改是否涉及事務、並發、安全邊界？ → **Sonnet 4.6**（最少）
3. 是否只是單檔的 < 20 行修補或測試？ → **Haiku 4.5**
4. 當兩個模型都合理時，**偏向較便宜的**（Haiku > Sonnet > Opus），除非有明確品質需求

#### 1.4.2 運行 Model 選擇原則（brain.toml）

Project Brain 的 `brain_config.py:440-551` 已定義完整的四層優先鏈。本文件的運行模型建議均**遵循既有 brain.toml 結構**：

| brain.toml Section | 預設模型 | 用途 | Fallback Chain |
|-------------------|---------|------|----------------|
| `[pipeline.llm]` | **gemma4:27b** (MoE) | Phase 1 自動管線 ADD/SKIP 判斷；L2 memory_synthesizer | gemma4:31b → `claude-haiku-4-5-20251001` |
| `[pipeline.llm.fallback]` | `claude-haiku-4-5-20251001` | Ollama 不可用時的雲端備援 | — |
| `[pipeline.models.merge]` | **gemma4:31b** (Dense) | Phase 3+ MERGE 複雜推理（待啟用） | gemma4:27b |
| `[pipeline.models.contradict]` | **gemma4:31b** (Dense) | Phase 3+ 矛盾偵測（待啟用） | gemma4:27b |
| `[pipeline.models.synthesis]` | **gemma4:31b** (Dense) | Phase 3+ 跨片段合成（待啟用） | gemma4:27b |
| `[review.model]` | **gemma4:31b** (Dense) | KRB AI 審查（低頻高品質） | `[pipeline.llm]` 整條鏈 |
| `[embedder]` | **nomic-embed-text** (768d) | L3 向量搜尋 | TF-IDF（local，零依賴） |

**三個層次的品質/成本取捨**：
- **Phase 1 基線**：`gemma4:27b` （MoE，快、便宜、本地零費用）
- **高品質判斷**：`gemma4:31b` （Dense，KRB 審查、複雜推理）
- **雲端備援**：`claude-haiku-4-5-20251001` （Ollama 斷線時）

#### 1.4.3 為什麼不預設使用 Claude Sonnet / Opus 作為運行模型

運行期的自動管線需要「高頻、低成本、可離線」，Claude Sonnet/Opus 不適合：
- **頻率**：Pipeline Worker 每 60s 跑一次，每 git commit 觸發多次 → 高頻呼叫成本失控
- **延遲**：Opus 中位延遲 3-10s，會塞住 worker
- **隱私**：企業場景下，程式碼 diff 不適合送雲端
- **離線**：gemma4 本地執行不依賴網路

**決策**：運行模型以 Ollama 本地模型為主，Claude 只作為 fallback。**開發模型則反過來**：以 Claude 為主（Haiku/Sonnet/Opus），因為開發是低頻、高品質需求、可接受成本的情境。

---

## 2. 系統現況全景

### 2.1 架構分層（含運行模型標註）

> 每個模組標註「運行時 LLM 呼叫」：
> - 🟦 = 不呼叫 LLM（純程式碼 / 資料層）
> - 🟨 = 呼叫 `[pipeline.llm]`（gemma4:27b → gemma4:31b → Haiku）
> - 🟧 = 呼叫 `[review.model]`（gemma4:31b → `[pipeline.llm]` chain）
> - 🟩 = 呼叫 Embedder（`nomic-embed-text` → TF-IDF fallback）

```
┌────────────────────────────────────────────────────────────────┐
│                  [輸入層]                                       │
│  🟦 CLI (brain add/ask/review/...)                             │
│  🟦 MCP Server                                                  │
│  🟦 HTTP API                                                    │
└────────────────┬──────────────────────────────────────────────┘
                 │
┌────────────────▼──────────────────────────────────────────────┐
│                  [決策層]                                       │
│  🟦 ProjectBrain (engine.py)  —  統一入口 + 懶初始化           │
│  🟩 ContextEngineer (context.py)  —  Embedder 呼叫向量搜尋     │
│  🟦 NudgeEngine (nudge_engine.py)  —  零費用原則，不呼叫 LLM   │
│  🟦 KnowledgeReviewBoard (review_board.py)  —  Staging 管理    │
│  🟧 KRBAIAssistant (krb_ai_assist.py)  —  [review.model]       │
└────────────────┬──────────────────────────────────────────────┘
                 │
┌────────────────▼──────────────────────────────────────────────┐
│                  [資料層]                                      │
│  🟦 BrainDB (brain_db.py, 2026 行)   ← FTS5, 全文索引, trace │
│  🟦 KnowledgeGraph (graph.py, 1138 行) ← L3, 版本控制, 樂觀鎖 │
│  🟦 SessionStore (session_store.py) ← L1a, TTL cleanup        │
│  🟩 VectorStore (vector_store.py) ← Embedder 儲存查詢         │
│  🟦 FeedbackTracker (feedback_tracker.py) ← 採用率回饋        │
│                                                                │
│  [維護引擎]                                                    │
│  🟦 DecayEngine (decay_engine.py, 645 行) ← F1-F7 多因子衰減 │
│  🟨 MemorySynthesizer ← [pipeline.llm] 合成 L2 片段           │
│  🟨 KnowledgeDistiller ← [pipeline.llm] (Layer 3 未來用 LoRA) │
│  🟨 KnowledgeValidator ← Haiku 4.5（成本優化，規則+AI 三階段）│
│  🟨 ConflictResolver ← [pipeline.llm] 仲裁                    │
└────────────────┬──────────────────────────────────────────────┘
                 │
┌────────────────▼──────────────────────────────────────────────┐
│                  [自動管線層] — ⚠ Phase 1 半成品               │
│  🟦 SignalQueue (pipeline.py) ← Layer 1+2 ✓                   │
│  🟦 KnowledgeExecutor (pipeline.py) ← Layer 4 ✓               │
│  🟨 LLMJudgmentEngine ← Layer 3 ❌ 未實作 [pipeline.llm]      │
│  🟦 BackgroundWorker ← Layer 3.5 ❌ 未實作（純迴圈）          │
└───────────────────────────────────────────────────────────────┘
```

**模型流統計**：
- 🟦 純程式碼模組：**14 個**（佔 70%）— 零 LLM 費用
- 🟨 `[pipeline.llm]` 模組：**4 個**（MemorySynthesizer / Distiller / Validator / LLMJudgmentEngine）
- 🟧 `[review.model]` 模組：**1 個**（KRBAIAssistant）
- 🟩 Embedder 模組：**2 個**（ContextEngineer / VectorStore）

**推論**：Brain 的核心設計正確 —— 大部分重邏輯都在程式碼裡完成（規則驗證、並發、衰減、索引），LLM 只用在**真正需要語意判斷的邊界**（管線判斷、KRB 審查、知識合成）。這個架構本身是健康的，只是 Layer 3 未實作讓 🟨 的其中一塊斷鏈。

### 2.2 資料持久層雙源問題

```
┌──────────────────────────────────┐      ┌──────────────────────────┐
│    knowledge_graph.db            │      │      brain.db            │
│ (graph.py / KnowledgeGraph)      │      │  (brain_db.py / BrainDB) │
│                                  │      │                          │
│  ✓ nodes, edges                  │ <-->│  ✓ nodes (鏡像)          │
│  ✓ temporal_edges (L2)           │ sync │  ✓ nodes_fts (FTS5 獨有) │
│  ✓ version (CAS 預留)            │      │  ✓ sessions, memories    │
│  ✓ 樂觀鎖類別已定義              │      │  ✓ traces, synonym_index │
│                                  │      │  ✓ signal_queue (獨有)   │
│                                  │      │  ✓ pipeline_metrics       │
└──────────────────────────────────┘      └──────────────────────────┘
        真相源？                                  搜尋主入口？
            └──── 經常不一致 ────────────────────────┘
```

**問題本質**：沒有任何模組擔任「唯一真相源」，兩個 DB 透過 `review_board.approve()` 等路徑手動同步。一處失敗 → 長期不一致。

---

## 3. 已驗證的真實缺陷

每一項都附 **檔案:行號**，可直接驗證。優先度按實際生產影響評估。

### 🔴 BLOCKER-01 — Pipeline Layer 3 LLM 判斷引擎未實作

> **🎯 開發 Model**：**Opus 4.6 (1M context)** — 新模組架構設計 + prompt engineering + 需長 context 閱讀 pipeline.py / brain_config.py / mcp_server.py 全文並驗證整合點
> **🎯 運行 Model**：`[pipeline.llm]` gemma4:27b (預設) → gemma4:31b (fallback) → Haiku 4.5 (最終備援)

**位置**：
- `project_brain/pipeline.py:283`（docstring 只提「由 LLMJudgmentEngine 產生」）
- `project_brain/pipeline.py` 整個檔案**無 LLMJudgmentEngine 類別**
- `docs/AUTO_KNOWLEDGE_PIPELINE.md:6`（設計文件第 6 節定義的 Layer 3）

**驗證方法**：
```bash
rg "class LLMJudgmentEngine|class LLMAnalyzer" project_brain/
# → 零匹配，只在 docs/AUTO_KNOWLEDGE_PIPELINE.md 出現
```

**現象**：
- SignalQueue 接受 Signal，寫入 signal_queue 表（Layer 1+2 ✓）
- KnowledgeExecutor 能消費 KnowledgeDecision 寫入 L3（Layer 4 ✓）
- **但沒有任何程式碼負責 Signal → KnowledgeDecision 的轉換**
- 也沒有背景 worker 定時 `dequeue_batch()` → 分析 → `run(decision)`

**影響**：
- 所有 Phase 1 的自動知識生產**完全無法運作**
- signal_queue 會累積到 `MAX_QUEUE_SIZE=500` 後觸發背壓丟棄
- 30 天後 pending 信號被標記 `skipped`（`MAX_PENDING_AGE_DAYS=30`）
- 使用者期望「git commit → 自動提取知識」的功能實際未實現

**嚴重性**：**BLOCKER** — Phase 1 核心功能完全不可用

**根本修法**（需新增兩個元件）：

```python
# project_brain/llm_judgment.py (新檔)
class LLMJudgmentEngine:
    """Layer 3 — LLM 判斷引擎。

    接收 Signal，呼叫 LLM，輸出 KnowledgeDecision。
    """
    def __init__(self, brain_config):
        self._llm = get_llm_client("pipeline", brain_config.brain_dir)

    def analyze(self, signal: Signal, related: list[dict] = None) -> KnowledgeDecision:
        """回傳 KnowledgeDecision（add 或 skip）。LLM 失敗時安全降級為 skip。"""
        prompt = self._build_prompt(signal, related)
        try:
            raw = self._llm.complete(prompt, timeout=30, max_retries=2)
            return KnowledgeExecutor.validate(raw)
        except Exception as e:
            logger.warning("llm_judgment failed, fallback to skip: %s", e)
            return KnowledgeDecision(
                action="skip", reason=f"llm_error: {e}",
                signal_id=signal.id, llm_model=""
            )

# project_brain/pipeline_worker.py (新檔)
class PipelineWorker:
    """背景 worker：定時處理 signal_queue → 寫入 L3（或 KRB staging）。"""
    def __init__(self, queue, judge, executor, interval=60):
        self._queue, self._judge, self._executor = queue, judge, executor
        self._interval = interval
        self._stop = threading.Event()
        self._thread = None

    def start(self) -> None:
        if self._thread is not None: return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._process_once()
            except Exception as e:
                logger.error("pipeline_worker error: %s", e)
            self._stop.wait(self._interval)

    def _process_once(self) -> int:
        batch = self._queue.dequeue_batch(batch_size=5)
        processed = 0
        for sig in batch:
            try:
                decision = self._judge.analyze(sig)
                result = self._executor.run(decision, sig)
                if result.ok:
                    self._queue.mark_done(sig.id, json.dumps({"action": result.action, "node_id": result.node_id}))
                else:
                    self._queue.mark_failed(sig.id, result.error)
            except Exception as e:
                self._queue.mark_failed(sig.id, str(e))
            processed += 1
        return processed
```

**整合點**：
- `mcp_server.py:create_server()` 結尾啟動 PipelineWorker（仿 DecayDaemon）
- `brain.toml [pipeline.worker]` 新增 `enabled = true`, `interval_seconds = 60`
- 新增 `tests/unit/test_llm_judgment.py` + `tests/unit/test_pipeline_worker.py`

**修復工作量**：12h（含測試）

---

### 🔴 BLOCKER-02 — review_board.approve() 雙資料庫寫入，BrainDB 失敗靜默吞錯

> **🎯 開發 Model**：**Sonnet 4.6** — 事務邊界 + 回滾邏輯需要審慎推理，但不需長 context
> **🎯 運行 Model**：— （無 LLM 呼叫）

**位置**：`project_brain/review_board.py:400-437`

**完整問題代碼**：
```python
# review_board.py:400-446
# Step 1：寫入 KnowledgeGraph (graph.py)
l3_id = f"krb_{staged_id}"
self.graph.add_node(
    node_id=l3_id, node_type=row["kind"], title=row["title"],
    content=row["content"], meta={"confidence": node_conf},
)
node_id = l3_id

# Step 2：同步到 BrainDB FTS5 — 失敗只 log warning！
try:
    bdb = BrainDB(self.brain_dir)
    bdb.add_node(
        node_id=l3_id, node_type=row["kind"], title=row["title"],
        content=row["content"] or "", confidence=node_conf,
    )
except Exception as _e:
    logger.warning("krb_approve: brain.db FTS 同步失敗（不影響核准）: %s", _e)
    # ← ⚠️ staged_nodes 仍然會被更新為 approved

# Step 3：標記 staged_nodes 為 approved（無條件執行）
self._conn_().execute("""
    UPDATE staged_nodes
    SET status='approved', reviewer=?, review_note=?,
        reviewed_at=?, l3_node_id=?
    WHERE id=?
""", (reviewer, note, now, f"krb_{staged_id}", staged_id))
self._conn_().commit()
```

**故障場景**：
1. 使用者 `brain review approve <id>`
2. KnowledgeGraph.add_node() 成功（節點進入 knowledge_graph.db）
3. `BrainDB(self.brain_dir)` 建構失敗（檔案鎖、權限、磁碟滿）
4. 只記 warning，staged_nodes 被標記 approved
5. **結果**：L3 節點存在於 graph.py 但 **brain.db FTS5 中缺失**
6. **使用者透過 `brain ask` 或 `get_context` 永遠搜不到這個節點**
7. 沒有任何機制偵測或修復這個不一致

**影響**：
- 資料長期不一致，無法偵測
- 核准的知識「消失」於搜尋結果
- 違反 ACID 中的 A（Atomicity）原則

**嚴重性**：**BLOCKER**（資料正確性）

**根本修法**（三步）：

```python
# Step A：L3 與 BrainDB 寫入合併為單一原子操作（強制成對）
def approve(self, staged_id, reviewer="human", note=""):
    ...
    l3_id = f"krb_{staged_id}"
    node_conf = float(row["confidence"]) if "confidence" in row.keys() else 0.75

    # KRB-02 fix: 先寫 BrainDB（失敗直接中斷，不影響 graph）
    try:
        bdb = BrainDB(self.brain_dir)
        bdb.add_node(
            node_id=l3_id, node_type=row["kind"], title=row["title"],
            content=row["content"] or "", confidence=node_conf,
        )
    except Exception as e:
        logger.error("krb_approve: BrainDB 寫入失敗，staged_nodes 保持 pending: %s", e)
        raise  # ← 向上拋出，staged_nodes 不被修改

    # 兩個 DB 都成功才寫 graph（冪等操作）
    try:
        self.graph.add_node(
            node_id=l3_id, node_type=row["kind"], title=row["title"],
            content=row["content"], meta={"confidence": node_conf},
        )
    except Exception as e:
        # graph 失敗時回滾 BrainDB
        try:
            bdb.delete_node(l3_id)  # 需新增此方法
        except Exception as rollback_err:
            logger.error("krb_approve: graph 失敗後 BrainDB 回滾也失敗: %s", rollback_err)
        raise

    # Step B：再更新 staged_nodes
    self._conn_().execute("""
        UPDATE staged_nodes
        SET status='approved', reviewer=?, review_note=?,
            reviewed_at=?, l3_node_id=?
        WHERE id=?
    """, (reviewer, note, now, l3_id, staged_id))
    self._conn_().commit()
    ...
```

**補充修復**：新增 `BrainDB.delete_node(node_id)` 方法（目前沒有，造成回滾困難）

**修復工作量**：4h（含測試：並發 approve + 注入寫入失敗）

---

### 🔴 BLOCKER-03 — Federation 模組 849 行程式碼，零專用測試

> **🎯 開發 Model**：**Sonnet 4.6** — 測試編寫是 Sonnet 的強項；PII 清理邊界需要安全意識但不需要架構設計
> **🎯 運行 Model**：— （federation 本身是純資料序列化，不呼叫 LLM）

**位置**：
- `project_brain/federation.py`（849 行，完整實作）
- `tests/test_federation*` **不存在**
- 僅在 `tests/unit/test_core.py` 等幾處出現 `federation` 字串引用（非驗證）

**驗證方法**：
```bash
ls tests/**/test_federation* 2>/dev/null
# → 空結果
```

**涵蓋的未驗證功能**：
- `FederationExporter` 的 PII 清理（`_PII_EMAIL`, `_PII_INTERNAL`）
- `FederationImporter` 的去重與衝突解析
- `SubscriptionManager` 的領域訂閱過濾
- `multi_brain_query` 的跨知識庫查詢
- `federation_sync` MCP tool

**風險**：
- PII 清理若有漏網之魚，export bundle 流出企業邊界才發現
- import 去重邏輯若錯誤，跨專案知識污染
- multi_brain_query 未驗證 `_validate_workdir()`，存在路徑遍歷風險（見 HIGH-04）

**嚴重性**：**BLOCKER**（安全 + 資料正確性）

**修法**：
建立完整測試套件：

```python
# tests/unit/test_federation.py（新檔）
class TestPIIStripping:
    def test_email_stripped(self)
    def test_internal_path_stripped(self)
    def test_variable_name_not_stripped(self)
    def test_cjk_content_preserved(self)

class TestExportRoundTrip:
    def test_export_then_import_preserves_node_count(self, tmp_path)
    def test_import_deduplicates_existing_titles(self, tmp_path)
    def test_subscription_filter_excludes_unsubscribed(self, tmp_path)

class TestMultiBrainQuery:
    def test_validate_workdir_called_on_extra_dirs(self)
    def test_traversal_attack_rejected(self)
    def test_symlink_attack_rejected(self)

class TestConflictResolution:
    def test_same_title_different_content(self, tmp_path)
    def test_confidence_merge_strategy(self, tmp_path)
```

**修復工作量**：10h

---

### 🟠 HIGH-01 — KnowledgeGraph.add_node() 存在 version 欄位但未執行 CAS

> **🎯 開發 Model**：**Sonnet 4.6** — 樂觀鎖的 CAS 邏輯有陷阱（e.g., SQLite UPDATE...WHERE version=? 的原子性），需要審慎推理但範圍小
> **🎯 運行 Model**：—

**位置**：
- `graph.py:112`：`version INTEGER NOT NULL DEFAULT 0`（schema 已有）
- `graph.py:20-22`：`ConcurrentModificationError` 類別已定義
- `graph.py:243-280`：`add_node()` 使用 `INSERT ... ON CONFLICT DO UPDATE`，**未檢查 version**

**問題代碼**：
```python
# graph.py:261-280
self._conn.execute("""
    INSERT INTO nodes (id, type, title, content, tags, ...)
    VALUES (?, ?, ?, ?, ?, ...)
    ON CONFLICT(id) DO UPDATE SET
        type=excluded.type,
        title=excluded.title,
        content=excluded.content,
        ...
""", (...))
# ← 沒有 WHERE version=? 的 CAS 檢查
```

**問題**：
- Thread A 讀取 node (version=5)，準備更新
- Thread B 讀取同 node (version=5)，先更新並 +1 → version=6
- Thread A 執行 INSERT...ON CONFLICT → **直接覆蓋 Thread B 的更新**
- `ConcurrentModificationError` **從未被 raise**（類別存在但死代碼）

**嚴重性**：**HIGH**（靜默資料遺失）

**修法**：
```python
def add_node(self, node_id, node_type, title, content="",
             tags=None, ..., expected_version: Optional[int] = None):
    ...
    with self._lock:
        if expected_version is not None:
            current = self._conn.execute(
                "SELECT version FROM nodes WHERE id=?", (node_id,)
            ).fetchone()
            if current and current[0] != expected_version:
                raise ConcurrentModificationError(
                    f"node={node_id} expected={expected_version} actual={current[0]}"
                )

        self._conn.execute("""
            INSERT INTO nodes (id, type, title, content, tags, ..., version)
            VALUES (?, ?, ?, ?, ?, ..., COALESCE(
                (SELECT version+1 FROM nodes WHERE id=?), 0))
            ON CONFLICT(id) DO UPDATE SET
                type=excluded.type, title=excluded.title, ...,
                version=version+1
        """, (..., node_id))
```

**修復工作量**：3h

---

### 🟠 HIGH-02 — BUG-07：`brain init` 對既有 DB 產生假 ERROR log

> **🎯 開發 Model**：**Haiku 4.5** — 30 分鐘 / 三行改動 / 已有完整修法；Haiku 即可精準執行
> **🎯 運行 Model**：—

**位置**（已在 IMPROVEMENT_PLAN.md 列為 P2，但一直沒修）：
- `project_brain/setup_wizard.py:126-130`
- `project_brain/brain_db.py:1959-1978`

**現象**：
在已初始化的專案執行 `brain init`，終端輸出：
```
ERROR project_brain.brain_db: session migration table failed: no such table: sessions
ERROR project_brain.brain_db: session migration table failed: no such table: memories
```

使用者誤以為初始化失敗（實際成功）。

**根本原因**：
1. Guard 條件不精確：`session_store.db` 存在就觸發 legacy migration
2. 未先驗證表存在性：直接 `SELECT * FROM sessions`
3. 錯誤等級不對：「找不到表」是預期情境，應為 debug

**IMPROVEMENT_PLAN.md 已列出三步修法**（Step A + B 即可 5 分鐘解決）。

**建議優先修**（使用者可見度高，信任度損傷）。

**修復工作量**：0.5h

---

### 🟠 HIGH-03 — find_conflicts() O(n²) 字串比對，500 節點上限

> **🎯 開發 Model**：**Sonnet 4.6** — 演算法改寫 + FTS5 查詢優化；若採方案 B 向量搜尋則需要 Opus 4.6 來設計索引策略
> **🎯 運行 Model**：🟩 Embedder（若採方案 B，用 nomic-embed-text）

**位置**：`brain_db.py:1516-1580`

**問題代碼**：
```python
def find_conflicts(self, similarity_threshold: float = 0.7) -> list:
    nodes = [dict(r) for r in self.conn.execute(
        "SELECT id, type, title, content FROM nodes LIMIT 500"  # ← 硬編碼上限
    ).fetchall()]

    conflicts = []
    _contra = [
        ("must", "must not"), ("should", "should not"),
        ("use", "do not use"), ...
    ]

    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:  # ← O(n²)
            # 字串比對矛盾 pairs
            ...
```

**問題**：
- 500 節點 O(n²) = 125,000 次迴圈 + 字串操作
- 真實知識庫達 5000 節點時這個函數會 skip 掉 90% 的可能衝突
- 硬編碼 LIMIT 500 掩蓋了問題

**嚴重性**：**HIGH**（可擴展性）

**修法**：
選項 A（最小改動）：使用 FTS5 做前置過濾
```python
def find_conflicts(self, similarity_threshold: float = 0.7) -> list:
    conflicts = []
    for anchor in self.conn.execute(
        "SELECT id, type, title, content FROM nodes WHERE type IN ('Rule','Decision')"
    ):
        # 用 FTS5 找相似節點，O(log n)
        similar = self.search_nodes(anchor['title'], limit=5)
        for candidate in similar:
            if candidate['id'] == anchor['id']: continue
            # 只比對 top-k 相似節點
            ...
```

選項 B（徹底重構）：使用 vector similarity 取代字串比對
```python
def find_conflicts(self) -> list:
    # 用 VectorStore 取所有節點 embedding
    # 用 FAISS/HNSW 做 O(log n) nearest neighbor
    # 只對 top-k 相似的節點做矛盾分析
```

**修復工作量**：4h（選項 A）/ 12h（選項 B）

---

### 🟠 HIGH-04 — multi_brain_query / federation_sync 缺 workdir 驗證

> **🎯 開發 Model**：**Sonnet 4.6** — 安全關鍵修補，Haiku 可能漏掉 edge case（symlink 雙層解析 / Windows 路徑）
> **🎯 運行 Model**：—

**位置**：`mcp_server.py` `multi_brain_query()` 和 `federation_sync()`

**問題**：
- `_validate_workdir()` 於 SEC-01/02 做了完整的 symlink + 遍歷防護
- 但這些防護只套用到主 workdir
- `multi_brain_query(extra_brain_dirs=[...])` 和 `federation_sync(remote_paths=[...])` 接受額外路徑但**未驗證**
- 攻擊者可透過 federation import 讓程式讀 `/etc/passwd`

**嚴重性**：**HIGH**（安全）

**修法**：
```python
def multi_brain_query(..., extra_brain_dirs=None):
    for d in (extra_brain_dirs or []):
        _validate_workdir(d)  # 對每個額外目錄都做完整驗證
    ...

def federation_sync(..., remote_bundle_path=""):
    if remote_bundle_path:
        p = Path(remote_bundle_path).resolve()
        # 檢查不在 _FORBIDDEN_ROOTS
        for root in _FORBIDDEN_ROOTS:
            if str(p).startswith(root):
                raise ValueError(f"forbidden path: {p}")
    ...
```

**修復工作量**：2h

---

### 🟡 MEDIUM-01 — brain_db.py 部分 commit() 在 _write_guard 外

> **🎯 開發 Model**：**Sonnet 4.6** — 16 個 commit 路徑的系統性重構，需要確認每個位置的事務語意
> **🎯 運行 Model**：—

**位置**：`brain_db.py`
- 已確認**在 _write_guard 內**：line 644 (add_node), 694 (update_node), 558 (build_synonym_index)
- 確認**不在 _write_guard 內**的 commit：
  - `line 174`（`_setup` schema 建立）
  - `line 377`（schema migration）
  - `line 776`（search_nodes 的 traces INSERT）
  - `line 797`（prune_episodes DELETE）
  - `line 819, 842, 904, 1088, 1117, 1267, 1296, 1357, 1396`

**分析**：
- SQLite WAL + busy_timeout=5000 會處理跨程序與多執行緒的序列化
- Python-level `_write_lock` 是額外的 TOCTOU 保護（SELECT 後 UPDATE 需同鎖）
- 大部分未鎖的 commit 是單步 INSERT/UPDATE/DELETE，SQLite 自行處理
- **但這種不一致使除錯與審計困難**

**嚴重性**：**MEDIUM**（可維護性 > 正確性）

**修法**：
選項 A（最小改動）：為所有寫入 commit 路徑加上 `_write_guard()`
選項 B（統一抽象）：所有寫操作經過 `self._execute_write(sql, params)` 單一入口

**建議選項 B**：
```python
def _execute_write(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
    """所有寫路徑統一入口，保證 lock + commit + 錯誤處理一致。"""
    with self._write_guard():
        try:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur
        except Exception:
            self.conn.rollback()
            raise
```

**修復工作量**：6h（含單元測試）

---

### 🟡 MEDIUM-02 — Knowledge Graph 與 BrainDB 雙源同步無中央協調

> **🎯 開發 Model**：
> - 方案 A (統一單一 DB) → **Opus 4.6 (1M)**（Schema v31 遷移 + 全檔掃）
> - 方案 B (唯一真相源) → **Sonnet 4.6**（路徑收束）
> - 方案 C (事件驅動，推薦短期) → **Sonnet 4.6**（事件匯流排）
> **🎯 運行 Model**：—

**背景**：`knowledge_graph.db` 與 `brain.db` 是兩個獨立 SQLite 檔案，必須手動保持同步。

**觀察到的同步路徑**：
1. `review_board.approve()`：寫 graph.py → 同步寫 brain_db.py（BLOCKER-02 問題所在）
2. `brain scan`：先寫 graph.py，後 brain_db.py（未驗證一致性）
3. `brain add`：只寫 graph.py（？需驗證）
4. `brain_db.migrate_from_legacy()`：單次遷移

**嚴重性**：**MEDIUM**（架構債）

**根本修法**（選其一）：

**方案 A：統一 DB（推薦）**
把 `knowledge_graph.db` 合併進 `brain.db`，改為單一 SQLite 檔案。
- 優點：消除所有同步問題，所有 FTS5 + L2 + L3 在同一個 transaction 內
- 缺點：需要 v31 schema 遷移 + 修改 KnowledgeGraph 的所有呼叫方
- 工作量：24h

**方案 B：確立唯一真相源**
`knowledge_graph.db` = 真相源，`brain.db` = 只讀 FTS5 快取。
- 寫入只走 graph.py
- brain.db 透過 `sync_from_graph()` 定期或觸發式更新
- 工作量：8h

**方案 C：事件驅動同步（最小侵入）**
在 `graph.add_node()` 結尾發 `node_added` 事件，`BrainDB` 訂閱後同步。
- 仍有最終一致性延遲
- 但不影響現有呼叫方
- 工作量：4h

**建議：短期方案 C（4h），中期方案 A（下個 milestone）**

---

### 🟡 MEDIUM-03 — MCP Server module-level singleton 狀態

> **🎯 開發 Model**：**Sonnet 4.6** — 跨檔案重構（封裝 state 成 class 實例），需確保測試不破
> **🎯 運行 Model**：—

**位置**：`mcp_server.py:51-68`

**問題**：
```python
_call_times: list[float] = []      # module-level，非 thread-local
_rate_lock = threading.Lock()
_session_nodes: dict[str, list[str]] = {}
_snodes_lock = threading.Lock()
_session_served: dict[str, set[str]] = {}
_cleanup_daemon_started = False
_decay_daemon_started = False
```

**影響**：
- 同一程序內跑多個 Brain 實例時，這些狀態是共享的
- 測試環境可能互相污染（pytest-xdist 並行時）
- 不符合單一實例 pattern

**嚴重性**：**MEDIUM**（測試穩定性 + 擴展性）

**修法**：封裝進 `class BrainMCPServer` 實例狀態，透過 `create_server()` 工廠產生

**修復工作量**：6h（需動到許多 helper 函式）

---

### 🟡 MEDIUM-04 — KRB staging 缺自動清理機制

> **🎯 開發 Model**：**Haiku 4.5** — 單函式 + 定時器整合；brain.toml 已定義 staging_ttl_days
> **🎯 運行 Model**：—

**位置**：`review_board.py` — 無 `auto_cleanup_expired_staging()` 方法

**問題**：
- `rejected` 節點永久保留於 `staged_nodes` 表
- 舊 `pending` 節點若無人審查，永遠累積（設計文件 AUTO_KNOWLEDGE_PIPELINE.md 提過 `staging_ttl_days`，但 KRB 未實作）
- `brain.toml [review]` 已定義 `staging_ttl_days` 欄位，但 `review_board.py` 未讀取

**嚴重性**：**MEDIUM**（記憶體 + 可用性）

**修法**：
```python
def cleanup_expired_staging(self, ttl_days: int = 90) -> int:
    """清理超過 ttl_days 的 rejected 和 pending staging 節點。"""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=ttl_days)).isoformat()
    cur = self._conn_().execute("""
        UPDATE staged_nodes
        SET status = CASE status
            WHEN 'pending'  THEN 'skipped_stale'
            WHEN 'rejected' THEN 'archived'
            ELSE status
        END
        WHERE status IN ('pending','rejected') AND created_at < ?
    """, (cutoff,))
    self._conn_().commit()
    return cur.rowcount
```

加上每日 daemon 呼叫（搭配 decay daemon）。

**修復工作量**：3h

---

### 🟡 MEDIUM-05 — 同義詞擴展無硬上界（潛在 DOS）

> **🎯 開發 Model**：**Haiku 4.5** — 單行 min() 截斷
> **🎯 運行 Model**：—

**位置**：`context.py:62`

```python
EXPAND_LIMIT = int(os.environ.get("BRAIN_EXPAND_LIMIT", "15"))
# ← 無上界限制
```

攻擊者（或誤設的 CI）設 `BRAIN_EXPAND_LIMIT=10000` → 單次查詢 FTS5 MATCH 條件包含 10,000 個 OR 子句 → FTS5 執行計畫爆炸。

**修法**：
```python
EXPAND_LIMIT = min(int(os.environ.get("BRAIN_EXPAND_LIMIT", "15")), 100)
```

**修復工作量**：0.5h

---

### 🟡 MEDIUM-06 — _count_tokens LRU 快取飽和後退化

> **🎯 開發 Model**：**Haiku 4.5** — 單函式改寫為確定性計算
> **🎯 運行 Model**：—

**位置**：`context.py:108`

```python
@functools.lru_cache(maxsize=1024)
def _count_tokens(text: str) -> int:
    ...
```

對於大型知識庫（5000+ 節點），快取命中率會降到 20% 以下，LRU 持續驅逐 + 重算 → 浪費 CPU。

**修法**：
- 方案 A：改為「節點 ID → token 數」的字典，隨 add_node/update_node 維護
- 方案 B：停用快取，改為確定性 O(n) 計算（中文 ≈ 1 token/char, ASCII ≈ 1/4 token/char）

**建議方案 B**（消除快取管理成本）

**修復工作量**：2h

---

### 🟡 MEDIUM-07 — 測試有 benchmark 但無 CI baseline

> **🎯 開發 Model**：**Haiku 4.5** — CI 設定檔 + baseline JSON 建立
> **🎯 運行 Model**：—

**位置**：`tests/benchmarks/`

**問題**：
- 已有 benchmark 檔案（效能測試）
- 但無 CI 集成，無 baseline 對比
- 效能回歸無法及時發現

**修法**：
- 建立 `tests/benchmarks/baseline.json` 儲存歷史基準
- 在 CI 執行 benchmark 並與 baseline 比對（退化 > 20% 則 fail）

**修復工作量**：4h

---

### 🟢 LOW 級問題摘要

> **所有 LOW 項目推薦使用 Haiku 4.5**：單檔瑣碎改動，可一次批次完成。

| ID | 位置 | 問題 | 工作量 | 開發 Model |
|----|------|------|-------|-----------|
| LOW-01 | `context.py:92` | except Exception: pass 吞錯（config.json 讀取失敗無日誌） | 0.5h | Haiku 4.5 |
| LOW-02 | `brain_db.py:68` | except OSError: pass（備份清理靜默） | 0.5h | Haiku 4.5 |
| LOW-03 | `brain_db.py:93` | close() 無 idempotent 保護 | 0.5h | Haiku 4.5 |
| LOW-04 | `federation.py:63-71` | _strip_pii 未處理 UUID/序列號 | 2h | Sonnet 4.6 (邊界需思考) |
| LOW-05 | `brain_db.py:1525` | find_conflicts 硬編碼 LIMIT 500（應從 config 讀） | 0.5h | Haiku 4.5 |

---

## 4. Myth Bust：非缺陷項目釐清

以下項目經實際程式碼驗證，並**非**缺陷（避免未來文件誤導）：

### ✓ MYTH-01 — "decay_engine.py 日期基準混亂"

**查驗**：`decay_engine.py:287-290`
```python
created  = row["created_at"] or ""
updated  = row.get("updated_at") or ""
ref_time = updated if updated > created else created  # ← 正確取 MAX
```
以及 `_factor_time()` 直接接 `ref_time` 參數。

**結論**：BUG-B02 修復已完整套用。

---

### ✓ MYTH-02 — "brain_db._effective_confidence() 日期邏輯錯誤"

**查驗**：`brain_db.py:432-434`
```python
updated  = node.get("updated_at") or ""
ref_time = updated if updated > created else created
ref_dt = datetime.fromisoformat(ref_time.replace("Z", "+00:00"))
```

**結論**：已使用 MAX(created, updated)。

---

### ✓ MYTH-03 — "nudge_engine 未用 effective_confidence"

**查驗**：`nudge_engine.py:283-284`
```python
# OPT-07: use decay-adjusted effective_confidence instead of raw confidence
conf = float(r.get("effective_confidence") or r.get("confidence", 0.8) or 0.8)
```

**結論**：OPT-07 已實作。

---

### ✓ MYTH-04 — "test_pipeline_executor.py 不存在"

**查驗**：
```bash
wc -l tests/unit/test_pipeline_executor.py
# → 352 行
```

**結論**：測試已存在，只是 Pipeline Layer 3 未實作無法實際運作。

---

### ✓ MYTH-05 — "auto_approve_by_confidence 從未被呼叫"

**查驗**：`engine.py:640`
```python
l3_id = krb.auto_approve_by_confidence(sid)
if l3_id:
    auto_approved += 1
```
透過 `brain scan` 流程使用。

**結論**：已整合。

---

### ✓ MYTH-06 — "總測試數只有 624"

**查驗**：
```bash
python -m pytest --collect-only -q | tail -1
# → 975 tests collected in 0.56s
```

**結論**：實際 975 個測試，遠超估計。

---

## 5. 優先修復矩陣

> **開發 Model 欄位**判準參考 § 1.4.1。**運行 Model** 欄只列出修復後會影響到的運行時配置（若無則留空）。

### Phase 1 — 血流失止血（本週，P0）✅ 完成於 2026-04-09

| 序 | ID | 描述 | 工作量 | 開發 Model | 運行 Model 影響 | 驗收條件 | 狀態 |
|----|----|------|--------|-----------|----------------|---------|------|
| 1 | BLOCKER-02 | Review Board 雙 DB 寫入原子化 | 4h | **Sonnet 4.6** (事務+回滾邏輯) | — | 並發 approve + 注入 BrainDB 失敗測試通過 | ✅ |
| 2 | HIGH-02 | BUG-07 假 ERROR log | 0.5h | **Haiku 4.5** (單檔小改) | — | `brain init` 在既有 DB 上無 ERROR 輸出 | ✅ |
| 3 | HIGH-04 | multi_brain_query workdir 驗證 | 2h | **Sonnet 4.6** (安全關鍵) | — | 遍歷/符號連結攻擊被拒 | ✅ |
| 4 | MEDIUM-05 | 同義詞擴展硬上界 | 0.5h | **Haiku 4.5** (單行改動) | — | `BRAIN_EXPAND_LIMIT=10000` 被截斷至 100 | ✅ |

**總工作量**：**7h**（1 個工作日）
**模型成本分佈**：Haiku 1h / Sonnet 6h / Opus 0h
**測試結果**：860 passed（14 pre-existing WebUI/schema-version failures 不受影響）

---

### Phase 2 — 架構深化（2 週，P1）

| 序 | ID | 描述 | 工作量 | 開發 Model | 運行 Model 影響 |
|----|----|------|-------|-----------|----------------|
| 5 | BLOCKER-01 | LLMJudgmentEngine + PipelineWorker 實作 | 12h | **Opus 4.6 (1M)** (新模組 + prompt engineering + 長 context 閱讀 pipeline.py 全文) | 🟨 `[pipeline.llm]` gemma4:27b（預設）；Dense 任務可升 gemma4:31b |
| 6 | BLOCKER-03 | Federation 完整測試套件 | 10h | **Sonnet 4.6** (測試編寫 + PII 邊界驗證) | — |
| 7 | HIGH-01 | KnowledgeGraph CAS 實施 | 3h | **Sonnet 4.6** (並發 + 樂觀鎖邏輯) | — |
| 8 | HIGH-03 | find_conflicts O(n²) 優化 | 4h | **Sonnet 4.6** (演算法改寫) | 🟩 Embedder (若用 VectorStore 方案 B) |
| 9 | MEDIUM-01 | brain_db._execute_write() 統一入口 | 6h | **Sonnet 4.6** (跨 16 個 commit 路徑重構) | — |
| 10 | MEDIUM-04 | KRB staging 自動清理 | 3h | **Haiku 4.5** (單函式 + 定時器) | — |

**總工作量**：**38h**（約 1 週，1 人力）
**模型成本分佈**：Haiku 3h / Sonnet 23h / Opus 12h

> **關鍵**：BLOCKER-01 是整個路線圖中唯一建議使用 Opus 4.6 的 Phase 2 項目，原因是 Layer 3 需要設計全新的 prompt schema、validate LLM 輸出結構、處理降級邏輯，且要長 context 讀取 pipeline.py 全文 + brain_config.py + mcp_server.py 等多檔。Sonnet 4.6 也能完成，但 Opus 4.6 (1M context) 在「一次吞下整個 pipeline 生態系」上優勢明顯。

---

### Phase 3 — 品質基建（1 個月，P2）

| 序 | ID | 描述 | 工作量 | 開發 Model | 運行 Model 影響 |
|----|----|------|-------|-----------|----------------|
| 11 | MEDIUM-02 | KG / BrainDB 雙源同步（方案 C：事件） | 4h | **Sonnet 4.6** (事件匯流排設計) | — |
| 12 | MEDIUM-03 | MCP Server singleton → 實例化 | 6h | **Sonnet 4.6** (跨檔重構) | — |
| 13 | MEDIUM-06 | _count_tokens 停用快取 | 2h | **Haiku 4.5** (單函式) | — |
| 14 | MEDIUM-07 | CI benchmark baseline | 4h | **Haiku 4.5** (CI 設定檔) | — |
| 15 | LOW-01~05 | 錯誤處理統一 + 小優化 | 4h | **Haiku 4.5** (瑣碎改動批次處理) | — |

**總工作量**：**20h**
**模型成本分佈**：Haiku 10h / Sonnet 10h / Opus 0h

---

### Phase 4 — 深度重構（3 個月，P3）

| 序 | ID | 描述 | 工作量 | 開發 Model | 運行 Model 影響 |
|----|----|------|-------|-----------|----------------|
| 16 | ARCH-01 | 統一單一 DB（合併 knowledge_graph.db 進 brain.db） | 24h | **Opus 4.6 (1M)** (schema 遷移 + 全檔掃 + 事務設計) | — |
| 17 | ARCH-02 | KnowledgeValidator 三階段驗證 CI 集成 | 16h | **Sonnet 4.6** (CI pipeline 整合) | 🟨 Haiku 4.5（validator 運行模型） |
| 18 | ARCH-03 | KnowledgeDistiller Layer 3 (LoRA) | 40h | **Opus 4.6 (1M)** (ML 研究 + 訓練 pipeline 設計) | 本地 GPU 訓練；推論用 LoRA adapter |
| 19 | ARCH-04 | Pipeline Phase 2：MCP_TOOL_CALL / TEST_FAILURE 信號 | 16h | **Opus 4.6 (1M)** (Signal schema 擴展 + prompt 設計) | 🟨 `[pipeline.llm]` gemma4:27b |
| 20 | ARCH-05 | WebUI 行內編輯 (FEAT-08) | 16h | **Sonnet 4.6** (前端 + API 整合) | — |

**總工作量**：**112h**（約 3 週集中開發）
**模型成本分佈**：Haiku 0h / Sonnet 32h / Opus 80h

> **總體建議**：Phase 4 有 71% 工作量建議使用 Opus 4.6，因為都是**架構級設計 + 長 context + 高風險**的重構。如果預算有限，可用 Sonnet 4.6 替代 ARCH-01 和 ARCH-04，但 ARCH-03（LoRA 研究）仍建議堅持 Opus。

---

### 5.5 四階段模型成本總覽

| Phase | Haiku 4.5 | Sonnet 4.6 | Opus 4.6 (1M) | 總工時 |
|-------|-----------|------------|----------------|--------|
| Phase 1 | 1h | 6h | 0h | **7h** |
| Phase 2 | 3h | 23h | 12h | **38h** |
| Phase 3 | 10h | 10h | 0h | **20h** |
| Phase 4 | 0h | 32h | 80h | **112h** |
| **總計** | **14h** (7.5%) | **71h** (38.2%) | **92h** (49.5%) | **177h** |

**成本策略**：
1. Phase 1-3（前 65h）— Haiku + Sonnet 混用，**幾乎不用 Opus**（只有 BLOCKER-01 12h）
2. Phase 4（後 112h）— 70% Opus，因為重構與研究需要高能力模型
3. **理想分佈**：前期修缺陷（便宜模型），後期做架構（貴模型但確保一次做對）

---

## 6. 重構藍圖

### 6.1 核心原則

1. **單一真相源**：最終每類資料只存一份（消除 KG/BrainDB 雙源）
2. **事務邊界清晰**：所有跨模組寫入有明確 begin/commit/rollback
3. **元件可替換**：LLM、Embedder、VectorStore 都有清楚的介面
4. **非同步與可降級**：核心查詢不依賴 LLM 可用性
5. **觀測友善**：所有失敗路徑有 log，所有慢路徑有 metric

### 6.2 建議新檔案結構

```
project_brain/
├── core/                    # 新目錄 — 核心不變數據層
│   ├── brain_db.py          # 唯一真相源（合併 graph.py 進來）
│   ├── session_store.py     # L1a
│   └── constants.py
│
├── pipeline/                # 新目錄 — 自動管線
│   ├── __init__.py
│   ├── signal.py            # 從 pipeline.py 拆出 Signal/SignalQueue
│   ├── executor.py          # KnowledgeExecutor
│   ├── llm_judgment.py      # 🆕 Layer 3 LLM 判斷引擎
│   ├── worker.py            # 🆕 背景 worker 迴圈
│   └── README.md            # Layer 1-5 架構說明
│
├── engines/                 # 新目錄 — 處理引擎
│   ├── context_engineer.py
│   ├── nudge_engine.py
│   ├── decay_engine.py
│   ├── review_board.py
│   ├── memory_synthesizer.py
│   ├── conflict_resolver.py
│   └── knowledge_validator.py
│
├── interfaces/              # 新目錄 — 外部介面
│   ├── cli.py
│   ├── mcp_server.py
│   ├── api_server.py
│   └── web_ui/
│
└── integrations/
    ├── federation.py
    ├── graphiti_adapter.py
    └── llm_client.py        # 🆕 統一 LLM 介面
```

**備註**：這是**建議方向**，實際是否拆分需視團隊容量。短期優先修 BLOCKER，長期才考慮目錄重組。

### 6.3 DB Schema 統一路徑（方案 A）

```
v30 (now)                    v31 (refactor target)
────────────                 ──────────────────────
brain.db                     brain.db (sole DB)
├── nodes                    ├── nodes (合併 KG nodes + BrainDB nodes)
├── nodes_fts                ├── nodes_fts
├── edges                    ├── edges
├── sessions                 ├── temporal_edges (從 KG 遷入)
├── episodes                 ├── episodes
├── traces                   ├── sessions
├── signal_queue             ├── node_vectors
├── pipeline_metrics         ├── synonym_index
└── node_history             ├── signal_queue
                             ├── pipeline_metrics
knowledge_graph.db           ├── staged_nodes (從 KRB 遷入)
├── nodes (duplicate!)       ├── knowledge_history
├── edges (duplicate!)       ├── node_history
└── temporal_edges           └── brain_meta (schema version)
```

**遷移腳本**：
```python
def migrate_v30_to_v31(brain_dir: Path):
    """合併 knowledge_graph.db 進 brain.db。"""
    bdb = BrainDB(brain_dir)
    kg_path = brain_dir / "knowledge_graph.db"
    if not kg_path.exists():
        return  # 早期版本沒有 KG

    kg = sqlite3.connect(str(kg_path))
    try:
        # 複製 KG nodes 進 brain.db（以 brain.db 為主，KG 的 version 寫入 meta）
        for row in kg.execute("SELECT * FROM nodes"):
            bdb.add_node(...)  # upsert

        # 複製 temporal_edges
        for row in kg.execute("SELECT * FROM temporal_edges"):
            bdb.conn.execute("INSERT OR IGNORE INTO temporal_edges ...")

        bdb.conn.commit()

        # 備份後刪除舊 DB
        kg_path.rename(brain_dir / f"knowledge_graph.db.bak.{today}")
    finally:
        kg.close()
```

---

## 7. 功能深度強化方向

### 7.1 Brain 的「神經元」—— Pipeline 完整化

> **🎯 開發 Model**：**Opus 4.6 (1M)** (Layer 3 設計 + Layer 5 回饋迴路)
> **🎯 運行 Model**：🟨 `[pipeline.llm]` gemma4:27b（Phase 1）；Phase 3+ MERGE 可升 gemma4:31b

**現狀**：Signal 收集完整，但 LLM 判斷與背景 worker 空白

**強化方向**：
1. **Layer 3 LLMJudgmentEngine** — BLOCKER-01 修法詳見 § 3
2. **Layer 5 Feedback Loop** — 設計文件 P5 提過但未實作：
   - 每次 `report_knowledge_outcome` 寫入 `feedback_log`
   - 週期性統計：該信號類型轉 add 後，多久被標記 `was_useful=False`
   - 若 > 30% 負面回饋 → 降低該信號類型的 auto_confidence

### 7.2 Brain 的「眼睛」—— Nudge Engine 強化

> **🎯 開發 Model**：**Sonnet 4.6** (context-aware 匹配邏輯 + session fatigue 追蹤)
> **🎯 運行 Model**：— (維持零 LLM 費用原則，純規則匹配)

**現狀**：靜態 Pitfall 搜尋（OPT-07 已套用 effective_confidence）

**強化方向**：
1. **Context-aware nudging**：根據當前 `current_file` 的程式碼特徵（import / function name）主動匹配相關 Pitfall
2. **Confidence-weighted 排序**：高信心 > 新近 > 高 access_count
3. **Nudge fatigue 避免**：同 session 不重複推同一 Pitfall（session_store 追蹤）

### 7.3 Brain 的「嘴巴」—— Context Engineer 優化

> **🎯 開發 Model**：**Sonnet 4.6** (scope 推導 + recency decay + 聚類演算法)
> **🎯 運行 Model**：🟩 Embedder `nomic-embed-text` (向量搜尋 + 語意聚類)

**現狀**：Token budget + per-type limit 已完整

**強化方向**：
1. **動態 scope 推導**：根據 `cwd` 自動推導 scope（IMPROVEMENT_PLAN S4）
2. **Recency decay**：除了 confidence，還要考慮節點的相關性新鮮度
3. **Semantic clustering**：回傳前對相似節點聚類，避免語意重複

### 7.4 Brain 的「記憶整合」—— Memory Synthesizer

> **🎯 開發 Model**：**Opus 4.6 (1M)** (cross-layer synthesis + 矛盾偵測 + 自動 edge 推導，需長 context 理解 L2/L3 互動)
> **🎯 運行 Model**：🟨 `[pipeline.llm]` gemma4:27b (合成片段) → gemma4:31b (複雜矛盾判斷)

**現狀**：v0.24.0 MEM-07 提到已實作 updated_at 基準

**強化方向**：
1. **Cross-layer synthesis**：整合 L2 episode + L3 node，發現「這個 commit 觸發過這條 Rule」的鏈接
2. **Contradiction detection**：新增知識時主動偵測與既有 Rule 的矛盾
3. **自動 edge 推導**：「每次 A 被引用時 B 也被引用」→ 自動建立 `CORRELATES_WITH` 邊

---

## 8. 未來路線圖

### 8.1 v0.31 — 緊急修復版（本週）

> **🎯 主要開發 Model**：**Sonnet 4.6** (6h) + **Haiku 4.5** (1h)
> **🎯 運行 Model 影響**：無（全部無 LLM）

**目標**：止血，修 BLOCKER + 可見錯誤
- ✅ BLOCKER-02：Review Board 雙 DB 原子化 `[Sonnet 4.6]`
- ✅ HIGH-02：BUG-07 假 ERROR log `[Haiku 4.5]`
- ✅ HIGH-04：Federation/multi_brain workdir 驗證 `[Sonnet 4.6]`
- ✅ MEDIUM-05：EXPAND_LIMIT 上界 `[Haiku 4.5]`

### 8.2 v0.32 — Pipeline 神經接通（2 週）

> **🎯 主要開發 Model**：**Opus 4.6 (1M)** — 整個 Phase 是一個新模組的架構設計
> **🎯 運行 Model**：🟨 `[pipeline.llm]` gemma4:27b → gemma4:31b → Haiku 4.5

**目標**：讓 Auto Knowledge Pipeline Phase 1 真正運作
- LLMJudgmentEngine 實作 `[Opus 4.6 (1M)]`
- PipelineWorker 背景 daemon `[Opus 4.6 (1M)]`
- `brain.toml [pipeline.worker]` 配置 `[Sonnet 4.6]`
- 端對端測試：git commit → signal → llm → executor → L3 `[Sonnet 4.6]`

**理由**：Opus 需要在一個 context window 內同時理解 pipeline.py（479 行）+ brain_config.py（579 行）+ mcp_server.py 創建流程（1402 行）+ brain.toml schema，才能設計出與既有架構無縫整合的 LLMJudgmentEngine。Sonnet 會因 context 分片導致遺漏整合點。

### 8.3 v0.33 — 資料正確性強化（2 週）

> **🎯 主要開發 Model**：**Sonnet 4.6** (大部分是審慎的重構)
> **🎯 運行 Model**：無直接影響（但 Federation 驗證涉及 PII，需小心）

- BLOCKER-03：Federation 完整測試 `[Sonnet 4.6]`
- HIGH-01：KnowledgeGraph CAS `[Sonnet 4.6]`
- HIGH-03：find_conflicts 優化 `[Sonnet 4.6]`（或 **Opus 4.6** 若採向量方案）
- MEDIUM-01：_execute_write 統一入口 `[Sonnet 4.6]`

### 8.4 v0.34 — 可觀測性與可維護性（3 週）

> **🎯 主要開發 Model**：**Sonnet 4.6** + **Haiku 4.5** 混用
> **🎯 運行 Model**：無

- MEDIUM-02：KG/BrainDB 事件同步 `[Sonnet 4.6]`
- MEDIUM-07：CI benchmark baseline `[Haiku 4.5]`
- Pipeline metrics dashboard（Grafana 可讀）`[Sonnet 4.6]`
- 新增 `brain health` 命令（自動 detect 常見不一致）`[Sonnet 4.6]`

### 8.5 v0.40 — 架構重構（長期）

> **🎯 主要開發 Model**：**Opus 4.6 (1M)** — 架構級決策
> **🎯 運行 Model**：不變（仍用現有 brain.toml 配置）

- 統一單一 DB（方案 A）`[Opus 4.6 (1M)]`（24h，Schema v31 遷移）
- 目錄重構（core/pipeline/engines/interfaces）`[Opus 4.6 (1M)]`
- LLM 介面統一（llm_client.py）`[Opus 4.6 (1M)]`

### 8.6 v1.0 — 生產就緒

> **🎯 綜合**：混用三個模型，依各項 Phase 1-4 建議

- 完整 CI 集成 `[Haiku/Sonnet]`
- 所有 BLOCKER/HIGH 修復 `[依原 Phase 建議]`
- Performance baseline 穩定 `[Haiku]`
- WebUI FEAT-08 行內編輯 `[Sonnet]`
- Federation 生產驗證 `[Sonnet]`
- 文件完善 `[Haiku 4.5]`

---

## 9. 實作指引

### 9.1 驗收流程

每個修復必須：
1. **先寫測試**（TDD）— 測試先 fail
2. **最小改動實作**
3. **全量測試通過**（`pytest tests/ -x --tb=short`）
4. **Brain 記錄**（complete_task + add_knowledge）
5. **CHANGELOG 更新**（版本號 + 變更摘要）

### 9.2 測試基準維護

每次 commit 前：
```bash
cd project-brain
python -m pytest -q 2>&1 | tail -5
# 975 passed (baseline, 2026-04-09)
```

### 9.3 Brain 知識回寫約定

本文件撰寫完成後，以下項目應寫回 Brain：
- **Decision**：「ARCHITECTURE_REVIEW.md 作為 v0.30 之後重構的 authoritative 計畫書」
- **Pitfall**：「BLOCKER-02 review_board 雙 DB 靜默失敗是 v0.30 最嚴重的資料正確性問題」
- **Pitfall**：「Pipeline Layer 3 LLMJudgmentEngine 在 v0.30 仍未實作，整個 Auto Pipeline 無法運作」
- **Rule**：「所有新增的 MCP tool 必須呼叫 `_validate_workdir()`，不得繞過」
- **Rule**：「跨 DB 寫入必須有明確回滾策略，不得只記 warning」

### 9.5 模型選擇快速決策樹（開發時用）

> 實作本文件任一項目時，用以下決策樹快速選擇 Claude 開發模型。

```
┌─────────────────────────────────────────┐
│ Q1: 是否需要新建模組或修改整體架構？     │
└────────────┬────────────────────────────┘
             │
    ┌────────┴────────┐
    │ YES             │ NO
    ▼                 ▼
┌─────────────┐   ┌─────────────────────────────────┐
│ Opus 4.6    │   │ Q2: 是否涉及事務/並發/安全邊界? │
│ (1M context)│   └──┬──────────────────────────────┘
└─────────────┘      │
                ┌────┴────┐
                │ YES     │ NO
                ▼         ▼
        ┌──────────┐  ┌────────────────────────┐
        │ Sonnet 4.6│  │ Q3: 工作量是否 < 1h?   │
        └──────────┘  └──┬──────────────────────┘
                         │
                    ┌────┴────┐
                    │ YES     │ NO
                    ▼         ▼
                ┌─────────┐  ┌──────────┐
                │ Haiku   │  │ Sonnet   │
                │ 4.5     │  │ 4.6      │
                └─────────┘  └──────────┘
```

#### 實例應用

**Q：修 MEDIUM-05 EXPAND_LIMIT 上界（0.5h，單行改動）**
- Q1: 新模組嗎？ NO
- Q2: 事務/並發/安全嗎？ NO（純效能上界）
- Q3: < 1h？ YES → **Haiku 4.5**

**Q：實作 BLOCKER-01 LLMJudgmentEngine（12h，新模組）**
- Q1: 新模組嗎？ YES → **Opus 4.6 (1M)**

**Q：修 BLOCKER-02 review_board 雙 DB 原子化（4h，跨 DB 事務）**
- Q1: 新模組嗎？ NO
- Q2: 事務/並發/安全嗎？ YES → **Sonnet 4.6**

**Q：撰寫 Federation 測試（10h，多檔測試）**
- Q1: 新模組嗎？ NO
- Q2: 事務/並發/安全嗎？ 部分（PII 清理） → **Sonnet 4.6**（保守選擇）

#### 成本對齊原則

1. **預設偏便宜**：兩個模型都能做時，選便宜的（Haiku > Sonnet > Opus）
2. **風險高時升級**：修安全/事務/資料正確性問題時，升一級（Haiku → Sonnet 或 Sonnet → Opus）
3. **重要任務不降級**：BLOCKER 級修復至少用 Sonnet，不要用 Haiku
4. **長 context 用 Opus**：需要同時看 > 3 個大檔案（> 500 行）時升 Opus 4.6 (1M context)
5. **研究性用 Opus**：LoRA、ML pipeline、全新的抽象設計時堅持 Opus

### 9.4 與現有文件的關係

- `CHANGELOG.md` — 版本歷史（已完成事項）
- `IMPROVEMENT_PLAN.md` — 規劃書（合併本文件的 Phase 1/2 內容）
- `docs/BRAIN_MASTER.md` — 內部架構記錄（更新「設計缺陷清單」章節，引用本文件）
- `docs/AUTO_KNOWLEDGE_PIPELINE.md` — Pipeline 設計文件（標記 Layer 3 為 NOT IMPLEMENTED）
- `docs/ARCHITECTURE_REVIEW.md` — **本文件，反思與重構的單一 Source of Truth**

---

## 結語

> **承認缺陷不是示弱，是對系統未來負責。**

Project Brain 走到 v0.30.0 已經是一個有骨有肉的系統：975 個測試、231 個知識節點、多因子衰減、KRB 審查流程、Federation 架構、MCP 整合。**這不是一個失敗的系統 —— 這是一個需要最後一哩路完成的系統**。

三個真正的 BLOCKER：
1. Pipeline Layer 3（LLM 判斷）— 整層缺席
2. Review Board 雙 DB 原子化 — 資料一致性
3. Federation 零測試 — 安全風險

這三個修掉，Brain 就從「玩具」變成「工業級」。其餘的 HIGH/MEDIUM 是深化，不是救命。

**行動順序建議**：
1. 本週：修 Phase 1（7h 止血）
2. 兩週內：完成 Phase 2（Pipeline 接通 + Federation 測試）
3. 月底前：完成 Phase 3（架構深化）
4. 季度末：評估是否啟動 Phase 4（重構）

願意面對缺陷，就已經走在變偉大的路上。

---

**文件結束**
**下次更新觸發**：Phase 1 修復完成後，或發現本文件列出的判斷錯誤時
