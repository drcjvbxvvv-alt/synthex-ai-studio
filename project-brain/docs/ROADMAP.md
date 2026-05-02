# Project Brain — 總體開發路線圖

> **主要規劃文件**。設計、開發、實作、測試的完整依賴鏈。
>
> **版本**：v2.0
> **最後更新**：2026-05-02
> **基準版本**：v0.52.0（~1618 passed，不含 chaos/benchmark）
> **維護原則**：每個 Phase 完成後在對應區塊標記 `[DONE vX.Y.Z]`，不刪除內容。

---

## 目錄

1. [文件導覽](#1-文件導覽)
2. [系統現況快照](#2-系統現況快照)
3. [Phase A — 基礎鞏固](#3-phase-a--基礎鞏固-done-v0340)
4. [Phase B — 可觀測性與維護性](#4-phase-b--可觀測性與維護性-done-v0350)
5. [Phase C — 架構演進](#5-phase-c--架構演進-done-v0400)
6. [Phase D — 生產就緒](#6-phase-d--生產就緒-目標-v100)
7. [Phase E — 團隊共享腦](#7-phase-e--團隊共享腦-目標-v200)
8. [完整依賴關係圖](#8-完整依賴關係圖)
9. [模型選擇速查表](#9-模型選擇速查表)
10. [品質門檻](#10-品質門檻)
11. [歸檔文件索引](#11-歸檔文件索引)

---

## 1. 文件導覽

| 文件 | 用途 | 狀態 |
|------|------|------|
| `docs/ROADMAP.md` | **本文件**：規劃、設計、實作、測試全覽 | 主動維護 |
| `docs/ARCHITECTURE_REVIEW.md` | 系統缺陷審計報告（v1.2）；各項缺陷的根因、驗證方法、修法細節 | 審計存檔（規劃已遷移至本文件） |
| `docs/SYSTEM_DEEP_REVIEW_2026-05-02.md` | v0.46.0 深度系統審查；可靠度、誠實性、記憶檢索品質、成本、缺陷與修復優先級 | 主動參考 |
| `docs/AUTO_KNOWLEDGE_PIPELINE.md` | Pipeline Layer 1-5 設計文件（v0.3.4）；Prompt 設計、資料模型、可靠性策略 | 技術參考（Layer 1-5 已實作） |
| `docs/EXPERIMENT_REPORT.md` | REV-01/02、KRB 效果的數據記錄範本 | 待填寫 |
| `CHANGELOG.md` | 各版本變更歷史 | 主動維護 |
| `tests/TEST_PLAN.md` | 測試套件全覽與真實數據量測計劃 | ✅ v1.0（D-05 已更新） |
| `COMMANDS.md` | CLI 命令使用者參考 | 主動維護 |
| `docs/archive/` | 過時文件歸檔 | 唯讀 |

---

## 2. 系統現況快照

### 2.1 版本與測試狀態

| 指標 | 數值 |
|------|------|
| 版本 | v0.52.0 |
| Unit tests | ~1618 passed（不含 chaos/benchmark） |
| 測試覆蓋率 | ≥ 50%（`fail_under = 50` in pyproject.toml） |
| 基準 recall@3 | 29%（IDF+diversity 改進後，eval.py 實測） |
| 基準 avg 查詢延遲 | ≤ 500ms |
| Schema 版本 | v28（feedback_log 表） |

### 2.2 模組完成度

```
project_brain/
├── core/
│   ├── brain_db.py          [STABLE] Schema v28，_execute_write 統一入口，WAL+lock
│   ├── session_store.py     [STABLE] TTL + cleanup daemon
│   └── constants.py         [STABLE] sys.modules 別名，monkey-patch 安全
│
├── pipeline/
│   ├── signal.py            [STABLE] Layer 1+2：Signal/SignalKind（含 MCP_TOOL_CALL/TEST_FAILURE/KNOWLEDGE_CONFLICT）
│   ├── executor.py          [STABLE] Layer 4：KnowledgeExecutor（確定性寫入）
│   ├── llm_judgment.py      [STABLE] Layer 3：LLMJudgmentEngine（統一 LLMClient + signal hints）
│   └── worker.py            [STABLE] Layer 3.5：PipelineWorker daemon
│
├── engines/
│   ├── context.py           [STABLE] ContextEngineer，向量搜尋 + synonym 展開（無 lru_cache）
│   ├── nudge_engine.py      [STABLE] effective_confidence 排序，零 LLM 費用
│   ├── decay_engine.py      [STABLE] F1-F7 多因子衰減
│   ├── review_board.py      [STABLE] KRB staging（C-01 簡化為單 graph.add_node）
│   ├── memory_synthesizer.py [STABLE] L2 合成
│   ├── conflict_resolver.py  [STABLE]
│   └── knowledge_validator.py [STABLE] ValidationReport.to_dict()
│
├── interfaces/
│   ├── mcp_server.py        [STABLE] BrainServer class，22 MCP tools，feedback_log 整合
│   ├── http_transport.py    [STABLE] AuthMiddleware + RateLimit + CORS + HTTPBrainServer（E-01 ✅）
│   ├── api_server.py        [STABLE]
│   ├── cli*.py              [STABLE] brain validate/eval/health --ci/--json
│   └── web_ui/              [STABLE] 行內編輯 + KRB Staging API + 管理面板（Table 視圖）+ 59 tests（D-02 ✅）
│
├── embedder.py              [STABLE] 5 backends（multilingual/ollama/openai/voyage/tfidf）+ lazy probe + warmup
├── eval.py                  [STABLE] RecallEvaluator（recall@K/MRR/nDCG）+ brain eval CLI
├── rbac.py                  [STABLE] ROLE_HIERARCHY + TOOL_PERMISSIONS + has_permission（E-02 ✅）
│
└── integrations/
    ├── llm_client.py        [STABLE] LLMClient Protocol + Ollama/Anthropic/Fallback/Noop
    ├── federation.py        [TESTED] 75 tests（PII/dedup/subscription）
    └── graphiti_adapter.py  [STABLE]
```

### 2.3 各 Phase 完成狀態

| Phase | 版本目標 | 狀態 | 核心目標 |
|-------|----------|------|---------|
| Phase A | v0.31~v0.34 | ✅ **DONE** | 止血 + 架構深化（11 項） |
| Phase B | v0.35 | ✅ **DONE** | 可觀測性、資料同步、維護性（7 項） |
| Phase C | v0.40 | ✅ **DONE** | 架構統一、LLM 介面、Pipeline 擴展（5 項） |
| Phase D | v1.0 | 🔄 **4/5 DONE** | 生產就緒、CI 全覆蓋（D-02~D-05 ✅）；D-01 LoRA 待 GPU |
| Phase E | v2.0 | ✅ **6/6 DONE** | E-01~E-06 全部完成 |

---

## 3. Phase A — 基礎鞏固 [DONE v0.34.0]

> 所有項目已完成，此節作為歷史記錄與依賴基礎。

### A-01 BLOCKER-02：Review Board 雙 DB 寫入原子化 [DONE v0.31.0]

**問題**：`review_board.approve()` KG 寫入成功但 BrainDB FTS5 失敗時只記 warning，staging 仍標記 approved → 知識「消失」於搜尋。

**修復**：先寫 BrainDB，失敗拋出；再寫 KG；兩者都成功才更新 staged_nodes。

**測試**：並發 approve + 注入 BrainDB 寫入失敗 → staging 保持 pending。

---

### A-02 HIGH-02：BUG-07 假 ERROR log [DONE v0.31.0]

**問題**：`brain init` 在已初始化的 DB 觸發 legacy migration，找不到 sessions/memories 表卻輸出 ERROR，使用者誤以為失敗。

**修復**：先檢查 `sqlite_master` 確認表存在；錯誤等級改為 `debug`。

---

### A-03 HIGH-04：multi_brain_query workdir 驗證 [DONE v0.31.0]

**問題**：`multi_brain_query(extra_brain_dirs=[...])` 未對每個額外路徑呼叫 `_validate_workdir()`，存在路徑遍歷 + symlink 攻擊面。

**修復**：對每個 extra_brain_dir 呼叫 `_validate_workdir()`。

---

### A-04 MEDIUM-05：同義詞展開硬上界 [DONE v0.31.0]

**問題**：`BRAIN_EXPAND_LIMIT=10000` 導致 FTS5 MATCH 包含 10,000 個 OR 子句，執行計畫爆炸。

**修復**：`EXPAND_LIMIT = min(..., 100)`

---

### A-05 BLOCKER-01：Pipeline Layer 3 LLMJudgmentEngine [DONE v0.32.0]

**問題**：SignalQueue 收集信號但無任何程式碼負責 Signal → KnowledgeDecision 的轉換，Auto Pipeline 完全不可用。

**實作**：`pipeline/llm_judgment.py`（LLMJudgmentEngine）+ `pipeline/worker.py`（PipelineWorker daemon）+ MCP server 整合。

**測試**：28 tests（J-01~J-14 + W-01~W-12）。

---

### A-06 BLOCKER-03：Federation 完整測試套件 [DONE v0.33.0]

**問題**：849 行 federation 程式碼，零專用測試，PII 清理與 import 去重未驗證。

**修復**：`tests/unit/test_federation.py` 75 tests，涵蓋 PII/dedup/subscription/multi_brain_query/workdir 驗證。

---

### A-07 HIGH-01：KnowledgeGraph CAS 樂觀鎖 [DONE v0.33.0]

**問題**：`add_node()` 有 `version` 欄位和 `ConcurrentModificationError` 類別，但 UPDATE 分支從不遞增 version，CAS 為死代碼。

**修復**：`expected_version: Optional[int] = None` kwarg；UPDATE 分支遞增 version；`with self._lock:` 序列化讀-檢-寫。

**測試**：17 tests（TestBackwardCompat / TestCASHappyPath / TestCASConflict / TestCASConcurrency）。

---

### A-08 HIGH-03：find_conflicts O(n→K·log n) 優化 [DONE v0.33.0]

**問題**：O(n²) 字串比對 + 硬編碼 LIMIT 500，1000 節點實際上 skip 掉 90%+ 的衝突。

**修復**：FTS5 候選者前置過濾（`_find_conflict_candidates`），每個 anchor 只比對 top-K 相似節點；移除 LIMIT 500。

**測試**：20 tests，含 600+ / 1000 節點擴展驗證。

---

### A-09 MEDIUM-01：BrainDB `_execute_write()` 統一入口 [DONE v0.33.0]

**問題**：8 個 runtime commit 路徑在 `_write_guard` 外，鎖保護不一致。

**修復**：`_execute_write(sql, params)` + `_execute_writescript(script)`；重構 8 個路徑。

**測試**：18 tests（50 threads 序列化 / 錯誤 rollback / caller 獨立驗證）。

---

### A-10 MEDIUM-04：KRB staging 自動清理 [DONE v0.34.0]

**問題**：`rejected` 和過期 `pending` 節點永久堆積，`brain.toml [review.staging_ttl_days]` 從未被讀取。

**修復**：`cleanup_expired_staging(ttl_days=None)` — pending→skipped_stale，rejected→archived。

**測試**：15 tests（邊界 / 隔離 / TTL / return value）。

---

### A-11 MEDIUM-07：CI Benchmark Baseline [DONE v0.34.0]

**問題**：有 benchmark 腳本但無回歸門檻，性能退化無法被 CI 捕捉。

**修復**：`baseline.json`（門檻）+ `test_baseline_regression.py`（4 benchmark tests）+ `update_baseline.py`（CLI tool）+ `test_benchmark_baseline_meta.py`（5 cheap meta tests）。

---

## 4. Phase B — 可觀測性與維護性 [DONE v0.35.0]

> **前提依賴**：Phase A 全部完成（v0.34.0 ✅）
>
> **核心目標**：解決 KG/BrainDB 資料不一致根因、提供運行健康診斷、降低技術債。
>
> **實際結果**：+235 tests（684 → 919 passed）

### B-01 KRB Cleanup Daemon 整合 [DONE v0.35.0]

**設計**：`cleanup_expired_staging()` 已實作（A-10），在 decay daemon 啟動流程中呼叫。每次 decay daemon 觸發（預設每 24h）順帶清理 KRB staging。

**實作**：`mcp_server.py` 的 `_run_maintenance_cycle` 中加入 KRB cleanup 呼叫，含 try/except 容錯。

**測試**：16 tests（`test_krb_daemon_integration.py`）

**驗收**：
- [x] decay daemon 每輪執行後，過期 staging 被自動清理
- [x] cleanup 失敗不中斷 decay（try/except + log）

---

### B-02 MEDIUM-02：KG/BrainDB 事件驅動同步 [DONE v0.35.0]

**設計**：Observer pattern — `KnowledgeGraph._listeners: list[Callable]`，`add_node()` / `update_node()` 成功後 emit `"node_upserted"` 事件。`ProjectBrain.__init__` 連線：`graph.add_listener(brain_db.sync_from_graph_node)`。

**實作**：
1. `graph.py`：新增 `_listeners`、`add_listener`、`remove_listener`、`_emit`
2. `brain_db.py`：新增 `sync_from_graph_node(event, data)`
3. `engine.py`：`__init__` 中掛接 listener

**測試**：9 tests（`test_kg_braindb_sync.py`）

**驗收**：
- [x] `graph.add_node()` 後 `brain_db.search_nodes()` 能找到節點
- [x] listener 失敗不中斷 graph 寫入
- [x] 50 threads 並發測試通過

---

### B-03 `brain health` 診斷命令 [DONE v0.35.0]

**設計**：

```bash
$ brain health
Project Brain Health Check — v0.40.0
======================================
[OK]  brain.db          accessible (1247 nodes, 389 edges)
[OK]  Single DB mode    knowledge_graph.db merged (C-01)
[OK]  KRB staging       3 pending, 0 stale (oldest: 2d)
[OK]  Pipeline worker   running (last processed: 4m ago)
[OK]  Decay daemon      running (last run: 6h ago)
[OK]  Signal queue      12 pending signals
[OK]  Benchmark         last run: 2d ago
======================================
Overall: OK (0 warnings, 0 errors)
```

**實作**：`project_brain/health.py` 新模組，`cli_admin.py` 呼叫，支援 `--json`、`--no-color`。

**測試**：21 tests（`test_health.py`）

---

### B-04 Pipeline Metrics Dashboard [DONE v0.35.0]

**設計**：`brain pipeline-stats [--prometheus] [--days N] [--json]`

**實作**：`BrainDB.get_pipeline_stats(days=7)` + CLI subcommand

**測試**：19 tests（`test_pipeline_stats.py`）

---

### B-05 MEDIUM-03：MCP Server BrainServer 重構 [DONE v0.35.0]

**設計**：封裝 7 個 module-level 可變狀態進 `class BrainServer`，`create_server()` 工廠不變（無 breaking change）。

**實作**：`mcp_server.py` 全面重構，新增 `BrainServer.emit_signal()` 非阻塞信號發送。

**測試**：18 tests（`test_mcp_server_isolation.py`）

---

### B-06 MEDIUM-06：`_count_tokens` 移除 LRU cache [DONE v0.35.0]

**設計**：移除 `@lru_cache(maxsize=1024)`，改為確定性 O(n) CJK 估算（無快取管理成本）。

**實作**：`engines/context.py`，擴展 CJK 範圍至 Extension A（U+3400）+ Compatibility Ideographs（U+F900）。

**測試**：30 tests（`test_perf03_token_cache.py`）

---

### B-07 LOW-01~04：錯誤處理批次修復 [DONE v0.35.0]

| ID | 位置 | 問題 | 修法 |
|----|------|------|------|
| LOW-01 | `context.py:92` | `except Exception: pass` 吞掉 config 讀取失敗 | `logger.warning(...)` |
| LOW-02 | `brain_db.py:68` | `except OSError: pass` 備份清理靜默 | `logger.debug(...)` |
| LOW-03 | `brain_db.py:93` | `close()` 無 idempotent 保護 | `if self._conn is None: return` |
| LOW-04 | `federation.py` | `_strip_pii` 未處理 UUID / token 格式 | 新增 UUID + sk-/ghp_/xoxb- regex |

**測試**：21 tests（`test_low_fixes.py`）

---

## 5. Phase C — 架構演進 [DONE v0.40.0]

> **前提依賴**：Phase B 全部完成（v0.35.0 ✅）
>
> **核心目標**：統一資料層、統一 LLM 介面、擴展 Pipeline 信號類型
>
> **實際結果**：+448 tests（919 → 1367 passed）

### C-01 ARCH-01：統一 DB（knowledge_graph.db 合併進 brain.db）[DONE v0.40.0]

**設計**：

```
v0.35 (two DBs)              v0.40 (single DB)
──────────────────           ──────────────────────────
brain.db                     brain.db  ← 唯一資料庫
  nodes (FTS5 mirror)          nodes（kind 欄位，統一 schema）
  edges                        nodes_fts（standalone FTS5，tokenize=unicode61）
knowledge_graph.db             edges（含 weight/confidence/trigger_condition）
  nodes (真相源)               temporal_edges
  edges (duplicate)            episodes / sessions / staged_nodes
                               signal_queue / pipeline_metrics
                               node_history / feedback_log
```

**關鍵技術決策**：
- FTS5 改為 standalone 模式（`tokenize='unicode61'`），棄用 `content='nodes'` content-backed 模式，解決 KG-first 初始化時的 FTS5 衝突
- KG 接受 `conn=` 參數共享連線，`_owns_conn=False` 時跳過 close
- `_migrate_kg_to_unified()` 一次性遷移，冪等，完成後改名 `.db.bak`

**Schema 遷移**：v22 → v27（edges 對齊 + indexes）→ v28（feedback_log）

**實作**：
1. `brain_db.py`：migration v27，`_migrate_kg_to_unified()`
2. `graph.py`：`db_path = brain_dir/"brain.db"`，`conn=` 參數，FTS5 standalone
3. `engine.py`：移除 Observer wiring，傳入 `conn=self.db.conn`
4. `review_board.py`：移除雙重寫入，只呼叫 `graph.add_node()`
5. `health.py`：single-DB 報告
6. `cli_fed.py`：修正 3 個路徑 bug（`KnowledgeGraph(bd/"brain.db")` → `KnowledgeGraph(bd)`）
7. `tests/test_web_ui.py`：fixture 改為 BrainDB-first + 共享 conn

**測試**：25 tests（`test_db_unification.py`）

**驗收**：
- [x] 新安裝不建立 knowledge_graph.db
- [x] `brain health` 顯示 single DB mode
- [x] 50 threads 並發測試在統一 DB 上通過

---

### C-02 integrations/llm_client.py — 統一 LLM 介面 [DONE v0.40.0]

**設計**：

```python
class LLMClient(Protocol):
    def complete(self, prompt: str, *, timeout=30, max_retries=2, temperature=0.1) -> str: ...

class OllamaLLMClient:    # 本地 Ollama
class AnthropicLLMClient:  # Anthropic API
class FallbackLLMClient:   # primary → fallback 自動切換
class NoopLLMClient:       # CI/測試環境佔位符

def from_brain_config(section, brain_dir) -> LLMClient:  # 工廠函式
```

**實作**：`integrations/llm_client.py`（新模組），`pipeline/llm_judgment.py` 遷移使用統一介面。

**測試**：28 tests（`test_llm_client.py`）

---

### C-03 ARCH-02：KnowledgeValidator CI 集成 [DONE v0.40.0]

**設計**：`brain validate [--ci] [--json] [--output report.json] [--max-api-calls N]`

- `--ci` 模式：LLM 不可用時只跑 Rule + 統計兩階段
- JSON report：`{"passed": bool, "rule_violations": [...], "stats": {...}}`
- exit code 1 when `passed: false`（供 CI 解析）

**實作**：`ValidationReport.to_dict()`、`_ValidatorLLMAdapter`、`cmd_validate()`

**測試**：11 tests（`test_knowledge_validator_ci.py`）

---

### C-04 ARCH-04：Pipeline Phase 2 — MCP_TOOL_CALL / TEST_FAILURE / KNOWLEDGE_CONFLICT [DONE v0.40.0]

**設計**：

| 信號類型 | 觸發時機 | 知識提取目標 |
|---------|---------|------------|
| `MCP_TOOL_CALL` | 每次 MCP tool 呼叫 | 學習使用模式、高頻 Pitfall |
| `TEST_FAILURE` | `complete_task` lessons 含 error | 記錄測試失敗模式 |
| `KNOWLEDGE_CONFLICT` | `find_conflicts()` 發現新衝突 | 主動偵測矛盾知識 |

**實作**：`signal.py` 新增 3 個 SignalKind；`llm_judgment.py` 新增 `_SIGNAL_HINTS` dict；`mcp_server.py` `BrainServer.emit_signal()` 非阻塞發送。

**測試**：20 tests（`test_pipeline_phase2_signals.py`）

---

### C-05 Pipeline Layer 5 — Feedback Loop [DONE v0.40.0]

**設計**：

```python
# feedback_log 表（Schema v28）
CREATE TABLE feedback_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT, signal_kind TEXT, was_useful INTEGER,
    notes TEXT, conf_before REAL, conf_after REAL,
    created_at TEXT DEFAULT (datetime('now'))
)

# 維護週期自動觸發
def _adjust_signal_confidence(brain):
    """30 天內 >30% 負面回饋 → 下調 signal 信心值（floor 0.3）"""
    for signal_kind in tracked_kinds:
        rate = ft.get_negative_rate(signal_kind, days=30)
        if rate > 0.30 and sample_count >= 5:
            new_conf = max(0.3, current_conf - 0.1)
            brain.db.conn.execute("INSERT OR REPLACE INTO brain_meta ...")
```

**實作**：`feedback_tracker.py`（`log_feedback` + `get_negative_rate`）；`mcp_server.py` `_adjust_signal_confidence` + `_run_maintenance_cycle` 整合。

**測試**：19 tests（`test_feedback_loop.py`）

---

## 6. Phase D — 生產就緒 [目標 v1.0]

> **前提依賴**：Phase C 全部完成（v0.40.0 ✅）
>
> **核心目標**：研究級功能（LoRA 蒸餾）、WebUI 完整化、CI 全覆蓋、生產驗證
>
> **總估計工作量**：~90h（主要為研究 + 測試工作）

### D-01 ARCH-03：KnowledgeDistiller Layer 3 LoRA 🕐 待實作

**ID**：ARCH-03
**優先**：P4（需要 GPU 環境）
**依賴**：C-02（統一 LLM 介面），需本地 GPU（≥ 16GB VRAM）
**狀態**：⏳ 待實作 — 等待 GPU 資源（≥ 16GB VRAM）；可在 D-02~D-05 完成後平行進行或使用 Google Colab T4

#### 設計

```
知識庫 ──[KnowledgeDistiller]──▶ Q&A 訓練資料集
                                      │
                                      ▼
                                [LoRA 訓練]（unsloth/axolotl）
                                      │
                                      ▼
                                brain.lora.adapter
                                      │
                           ┌──────────┘
                           ▼
                    Ollama 載入 adapter → 直接回答專案問題（無需 RAG）
```

#### 實作步驟

1. **`project_brain/engines/knowledge_distiller.py`**（新模組）
   - `KnowledgeDistiller.generate_dataset(brain_dir, output_path)` — 從 L3 節點生成 Q&A pairs
   - Q&A 格式：`{"instruction": "...", "input": "", "output": "..."}`
   - 節點選擇策略：confidence ≥ 0.7，kind in [Rule, Decision, Pitfall]

2. **`scripts/train_lora.py`**
   - 使用 unsloth（速度優先）或 axolotl（彈性優先）
   - 支援 Llama-3-8B / Mistral-7B base model
   - 輸出 adapter 至 `.brain/brain.lora.adapter/`

3. **`brain.toml` 整合**
   ```toml
   [distiller]
   adapter_path = ".brain/brain.lora.adapter"
   base_model = "llama3:8b"
   enabled = false  # 需要顯式啟用
   ```

4. **推論整合**：`llm_client.py` 新增 `LoRALLMClient`，`from_brain_config` 工廠支援

5. **評估腳本**：`scripts/eval_lora.py` — recall@3 / answer accuracy vs RAG 基線對比

#### 測試計劃

```python
# tests/unit/test_knowledge_distiller.py
class TestDatasetGeneration:
    def test_generates_qa_pairs_from_nodes(self, tmp_path):
        """知識庫 10 個高信心節點 → 生成 ≥ 8 個 Q&A pairs"""
    def test_filters_low_confidence_nodes(self, tmp_path):
        """confidence < 0.7 的節點不納入訓練集"""
    def test_output_format_is_alpaca_compatible(self, tmp_path):
        """每條 Q&A 含 instruction/input/output 欄位"""
    def test_deduplication_in_dataset(self, tmp_path):
        """相同 title 的節點只生成一條（dedup）"""
    def test_empty_brain_returns_empty_dataset(self, tmp_path):
        """空知識庫不 crash，回傳空 list"""

class TestLoRAClientIntegration:
    def test_lora_client_falls_back_when_adapter_missing(self, tmp_path):
        """adapter 不存在時 fallback 到 Ollama"""
    def test_from_brain_config_creates_lora_client(self, tmp_path):
        """brain.toml [distiller.enabled=true] 建立 LoRALLMClient"""
```

#### 驗收條件

- [ ] `brain distill` 命令可生成 Q&A 資料集
- [ ] 生成資料集包含 ≥ 80% 的高信心節點
- [ ] `LoRALLMClient` 可載入 adapter，fallback 到 Ollama 時無 crash
- [ ] 訓練腳本在 RTX 3090（24GB）環境完整執行
- [ ] adapter 推論 recall@3 ≥ RAG 基線

**推薦模型**：Opus 4.6 (1M)（ML 研究級設計）
**估計工作量**：40h+（含 GPU 訓練時間）

---

### D-02 ARCH-05：WebUI 完整化（行內編輯 + KRB 管理 + 管理面板）[DONE v0.47.0]

**ID**：ARCH-05
**優先**：P4
**依賴**：C-01（統一 DB 讓前端 API 更穩定）

#### 設計

目前 WebUI 只讀（`web_ui/`，零測試）。目標新增：

**前端功能**：
- 節點行內編輯（title / content / confidence / kind）
- KRB staging 管理界面（approve / reject / needs_changes）
- 全文搜尋 + 種類過濾
- 知識圖譜視覺化（D3.js force-directed graph，已部分實作）

**API 端點**（新增）：

| 端點 | 方法 | 功能 |
|------|------|------|
| `/api/node/<id>` | PATCH | 更新節點欄位 |
| `/api/node/<id>` | DELETE | 刪除節點 |
| `/api/staging` | GET | 列出 KRB pending |
| `/api/staging/<id>/approve` | POST | 核准 |
| `/api/staging/<id>/reject` | POST | 拒絕 |
| `/api/search` | GET | FTS5 全文搜尋（已有，補測試） |

#### 實作步驟

1. **後端 API**（`web_ui/server.py`）：
   - 新增 PATCH `/api/node/<id>` — 更新 title/content/confidence（驗證欄位白名單）
   - 新增 DELETE `/api/node/<id>` — 邏輯刪除（is_deleted flag）
   - 新增 GET/POST `/api/staging/*` — KRB 管理端點

2. **前端更新**（`web_ui/templates/`）：
   - 節點卡片新增「編輯」按鈕 → inline form
   - Staging panel（右側欄位）
   - 搜尋框 + 即時過濾

3. **測試補全**：`tests/integration/test_web_ui.py` 新增 API 測試（目前 4 個 failing 測試需修正）

#### 測試計劃

```python
# tests/integration/test_web_ui_edit.py
class TestNodeEdit:
    def test_patch_node_updates_title(self, client):
        """PATCH /api/node/n1 {"title": "new"} → 更新成功"""
    def test_patch_rejects_unknown_fields(self, client):
        """未在白名單內的欄位回傳 400"""
    def test_delete_node_removes_from_graph(self, client):
        """DELETE /api/node/n1 → 節點不再出現於 /api/graph"""

class TestKRBManagement:
    def test_staging_list_returns_pending(self, client): ...
    def test_approve_moves_to_l3(self, client): ...
    def test_reject_updates_staging_status(self, client): ...
```

#### 驗收條件

- [x] 行內編輯儲存後立即反映於圖譜視圖（JS 即時更新圖形顏色/標籤）
- [x] KRB staging 管理界面可正常 approve/reject（`/api/staging/*` 端點）
- [x] `pytest tests/unit/test_web_ui_edit.py` 33/33 passed（零 regression）
- [x] 覆蓋率從 0 提升至 33 tests（後端 API 全覆蓋）
- [x] 管理面板（Table 視圖）：`📊 圖譜 / 📋 管理` Tab + 分頁 + sort/filter（v0.47.0）
- [x] `/api/nodes` 分頁端點：`page`/`page_size`/`q`/`kind`/`sort`/`order` 參數（v0.47.0）
- [x] Graph 效能修復：`/api/graph` limit 100（預設）+ 前端節點上限控制（v0.47.0）
- [x] `pytest tests/integration/test_web_ui.py` 26/26 passed（v0.47.0 新增）

**實際實作**：
- `_validate_node_patch` + `_sync_fts` + `_load_staging` 三個共用 helper（v0.41.0）
- `kind` API 欄位自動映射到 DB 的 `type` 欄位
- `_route_nodes()` + `/api/nodes` 分頁端點（v0.47.0）
- 前端 `switchView()`、`loadTablePage()`、Table view DOM（v0.47.0）
- WebUI FTS sync 改用 `BrainDB._ngram()` 確保中文索引一致性（v0.47.0，P1-3）

**測試**：`tests/unit/test_web_ui_edit.py`（33）+ `tests/integration/test_web_ui.py`（26）= 59 tests

**推薦模型**：Sonnet 4.6（前端 + API 整合）
**估計工作量**：16h

---

### D-03 完整 CI 集成 **[DONE v0.42.0]**

**優先**：P4
**依賴**：Phase B（`brain health --json`）、Phase C（`brain validate --ci`）

#### 實作成果

- **`.github/workflows/ci.yml`** — 5-job GitHub Actions pipeline
  - `unit`：矩陣 Python 3.11 + 3.12，排除 benchmark/chaos
  - `benchmark`：`pytest -m benchmark` baseline regression（4 tests）
  - `coverage`：覆蓋率門檻 ≥ 45%（現有 ~47%），上傳 Codecov
  - `health`：`brain health --json`，解析 `d["summary"]["overall"]`（非頂層 `overall`）
  - `validate`：`brain validate --ci`，解析 `d["passed"]`
- **`tests/unit/test_ci_integration.py`** — 45 tests，驗證 CI 所有依賴函式

#### 驗收條件

- [x] 所有 CI jobs 本地驗證通過
- [x] `pytest -m benchmark` 正常收集並執行（4 passed）
- [x] 覆蓋率門檻設定（≥ 45%，現有 ~47%）
- [x] health job 使用正確 JSON key：`d["summary"]["overall"]`（非 `d["overall"]`）
- [x] validate job 正確解析 `d["passed"]`
- [x] 45 tests 驗證 CI 基礎設施穩定性

---

### D-04 生產驗證 **[DONE v0.43.0]**

**優先**：P4

#### 實作成果

1. **Federation 生產驗證**（`tests/unit/test_prod_validation.py`，19 tests）
   - `TestCrossBrainSync`（7）：兩個真實 tmp brain dir 之間 export/import 完整 round-trip
   - `TestPIIAtScale`（5）：1000 節點中 200 含 PII；export 後驗證無 email / private IP / internal host
   - `TestDedupAtScale`（4）：1000 節點共享，300 重複 → 正確 skipped_dup=300，novel=200
   - `TestFederationBundleIntegrity`（3）：JSON 序列化、必要欄位、空庫

2. **E2E Pipeline 整合測試**（`tests/e2e/test_pipeline_e2e.py`，14 tests）
   - `TestSignalToL3Flow`（8）：stub judge 驗證完整資料流（enqueue→process→L3 write）
   - `TestPipelineLatency`（2）：single signal < 5s，batch 10 signals < 30s
   - `TestPipelineWorkerLifecycle`（3）：start/stop、double-start no-op、thread 處理
   - `TestPipelineOllama`（1）：真實 Ollama 測試（`BRAIN_TEST_OLLAMA=1` 才執行，CI 自動 skip）

3. **效能基準**（`tests/benchmarks/benchmark_perf_5k.py`，5 tests）
   - 5000 節點寫入吞吐量 ≥ 200 nodes/s ✅
   - FTS5 p99 延遲 ≤ 300ms ✅
   - FTS5 平均延遲 ≤ 100ms ✅
   - BrainDB hybrid search p99 ≤ 300ms ✅

#### 驗收條件

- [x] Federation cross-brain sync（2 個真實專案）測試通過
- [x] PII 清理完整性驗證：1000 節點 0 洩漏
- [x] Dedup 正確性：1000+ 節點中 300 重複全部被過濾
- [x] E2E pipeline 端到端延遲 < 5s（stub judge，本機）
- [x] 5000 節點 FTS5 p99 ≤ 300ms
- [x] 5000 節點寫入 ≥ 200 nodes/s
- [x] Ollama E2E 測試有 `BRAIN_TEST_OLLAMA=1` guard（CI 安全）
- [x] 新增 `e2e_ollama` pytest marker

---

### D-05 文件完整化 **[DONE v0.44.0]**

**優先**：P4

| 文件 | 狀態 |
|------|------|
| `COMMANDS.md` | ✅ v1.0 — 加入 `brain health` / `brain validate` / `brain pipeline-stats` 詳細說明 |
| `INSTALL.md` | ✅ 加入 GPU/LoRA 環境（CUDA + Axolotl / Unsloth + Colab 替代） |
| `tests/TEST_PLAN.md` | ✅ v1.0 — 更新至 1029+ tests 全覽，含 Phase B/C/D |
| `docs/EXPERIMENT_REPORT.md` | ✅ 填入 D-04 真實效能數據；REV-01/02 框架留待真實舊專案 |
| `README.md` | ✅ 新建 — 三層架構、快速開始、效能指標、文件導覽 |
| `tests/unit/test_docs_accuracy.py` | ✅ 51 tests — 驗證文件與程式碼一致性 |

---

### Phase D 完成驗收

```bash
# D-01：蒸餾功能
brain distill --output /tmp/dataset.json
python -c "import json; d=json.load(open('/tmp/dataset.json')); print(len(d), 'Q&A pairs')"

# D-03：CI 全部綠燈
gh run list --limit 5  # GitHub Actions

# D-04：效能基準
python benchmarks/update_baseline.py --min-nodes 5000
cat benchmarks/baseline.json | jq '.recall_at_3, .avg_latency_ms'
# 預期：≥ 0.70, ≤ 300

# 全量測試（≥ 1500 passed）
python -m pytest tests/ -q | tail -3
```

---

## 7. Phase E — 團隊共享腦 [目標 v2.0]

> **前提依賴**：Phase D 全部完成（v1.0 ✅）
>
> **核心目標**：讓整個團隊共享一個集中知識庫，每個人的 Claude Code（小龍蝦）都能連接並使用。
>
> **總估計工作量**：~120h
>
> **架構願景**：
>
> ```
>                   ┌─────────────────────────────────┐
>                   │     Central Brain Server         │
>                   │     (公司集中知識庫)               │
>                   │     brain.db (shared)            │
>                   │     HTTP MCP Server :3000        │
>                   │     API Key 認證                 │
>                   └──────────────┬──────────────────┘
>                                  │ HTTP/SSE MCP
>           ┌──────────────────────┼──────────────────────┐
>           │                      │                      │
>     [小龍蝦 A]              [小龍蝦 B]              [小龍蝦 C]
>     Claude Code             Claude Code             Claude Code
>     (工程師甲)              (工程師乙)              (工程師丙)
>     本地 brain (可選)        本地 brain (可選)        本地 brain (可選)
>           │                      │                      │
>           └──────────────────────┴──────────────────────┘
>                        所有人共享同一份知識
> ```

### E-01 HTTP MCP Transport（核心基礎）[DONE v0.45.0]

**ID**：E-01
**優先**：P1（Phase E 的基礎，其他項目依賴此項）
**依賴**：D 全部完成
**估計工作量**：20h

#### 設計

目前 MCP Server 只支援 stdio transport（本地進程通訊）。Phase E 需要 HTTP/SSE transport 讓遠端 Claude Code 連接。

**MCP 協定要求**：
- HTTP POST `/mcp` — 接收 JSON-RPC 請求
- GET `/mcp/sse` — Server-Sent Events 推送（Sampling、通知）
- 請求格式：MCP 1.x JSON-RPC over HTTP

**啟動方式**：
```bash
# 單機本地（不變）
brain serve --port 3000

# 網路可存取模式（新增）
brain serve --bind 0.0.0.0 --port 3000 --auth-key $BRAIN_API_KEY

# 多個 workdir（多專案）
brain serve --bind 0.0.0.0 --port 3000 --multi-project
```

**Claude Code 客戶端設定**（`claude_desktop_config.json`）：
```json
{
  "mcpServers": {
    "company-brain": {
      "url": "http://brain.company.internal:3000/mcp",
      "headers": {
        "Authorization": "Bearer ${BRAIN_API_KEY}"
      }
    }
  }
}
```

#### 實作步驟

**步驟 1**：研究 MCP 1.x HTTP transport 規格
- 閱讀 `mcp` package 的 HTTP transport 文件
- 確認 SSE 端點格式（`/mcp/sse` vs `/sse`）
- 確認 JSON-RPC over HTTP 的 session 管理方式

**步驟 2**：`interfaces/mcp_server.py` 新增 HTTP transport
```python
def create_http_server(brain_dir: Path, config=None,
                       bind: str = "127.0.0.1",
                       port: int = 3000,
                       auth_key: str = None) -> "HTTPBrainServer":
    """建立支援 HTTP/SSE 的 MCP Server"""
    srv = BrainServer(brain_dir, config)
    return HTTPBrainServer(srv, bind=bind, port=port, auth_key=auth_key)
```

**步驟 3**：`HTTPBrainServer` 類別
- 使用 `mcp` package 的 `http` transport（若支援）或用 Flask/FastAPI 包裝
- 請求驗證：`Authorization: Bearer {key}` header
- 連線計數 + rate limiting（per client IP）
- Graceful shutdown（SIGTERM handler）

**步驟 4**：`cli_serve.py` 更新 `brain serve` 命令
```python
def cmd_serve(args):
    if args.bind != "127.0.0.1" or args.auth_key:
        # 網路模式
        server = create_http_server(workdir, bind=args.bind,
                                    port=args.port, auth_key=args.auth_key)
    else:
        # 本地 stdio 模式（不變）
        server = create_server(workdir)
```

**步驟 5**：安全加固
- Rate limiting：每個 IP 每分鐘 ≤ 60 requests
- CORS：只允許明確設定的 origin（`--allow-origin`）
- TLS：支援 `--cert` / `--key` 或 nginx 反代文件

#### 測試計劃

```python
# tests/integration/test_http_mcp_server.py
class TestHTTPMCPBasic:
    def test_health_endpoint_accessible(self, http_server):
        """GET /health → 200"""
    def test_mcp_endpoint_rejects_unauthenticated(self, http_server):
        """POST /mcp without auth → 401"""
    def test_mcp_endpoint_accepts_valid_key(self, http_server):
        """POST /mcp with valid Bearer → 200"""
    def test_rate_limit_enforced(self, http_server):
        """61 requests/min from same IP → 429 on 61st"""
    def test_two_clients_independent_sessions(self, http_server):
        """兩個 client 的 session state 互不干擾"""

class TestMCPToolsOverHTTP:
    def test_brain_status_tool_works_over_http(self, http_server, mcp_client):
        """brain_status tool 透過 HTTP 可正常呼叫"""
    def test_add_knowledge_tool_works_over_http(self, http_server, mcp_client):
        """add_knowledge 寫入後 search_knowledge 可找到"""
    def test_concurrent_writes_from_two_clients(self, http_server):
        """兩個 client 同時 add_knowledge → 兩條都寫入成功"""

class TestSSETransport:
    def test_sse_endpoint_returns_event_stream(self, http_server):
        """GET /mcp/sse → Content-Type: text/event-stream"""
```

#### 驗收條件

- [x] `brain serve --mcp --auth-key $KEY` 可啟動 HTTP server（streamable-http / sse）
- [ ] Claude Code 可透過 `claude_desktop_config.json` 連接（manual test）
- [x] 未認證請求回傳 401（`hmac.compare_digest` timing-safe）
- [x] Rate limiting 正常運作（429，per-IP sliding window）
- [x] `/health` 端點免認證、不受限流（供負載均衡 + 監控）
- [x] `pytest tests/integration/test_http_mcp_server.py` 36/36 passed

#### 實際實作

- **`http_transport.py`**（新模組，290 行）：AuthMiddleware + RateLimitMiddleware + CORSMiddleware + HealthEndpoint + HTTPBrainServer
- **middleware 堆疊**（由外到內）：HealthEndpoint → CORS → Auth → RateLimit → FastMCP Starlette App
- **支援傳輸**：`streamable-http`（預設）、`sse`（向後兼容）
- **安全設計**：Bearer token + timing-safe 比較 + per-IP 限流 + CORS 白名單

---

### E-02 Central Brain 模式（多用戶寫入安全）[DONE v0.49.0]

> v0.46.0：知識歸屬（source/author）+ 衝突偵測（find_conflicts_for_node）
> v0.49.0：Write Queue 序列化 + RBAC 基礎 + `--mode central` CLI + 100 threads 0 丟失

**ID**：E-02
**優先**：P1（與 E-01 並行開發）
**依賴**：E-01（HTTP transport 基礎）
**估計工作量**：16h

#### 設計

當多個使用者同時寫入，需要確保資料一致性。

**並發模型**：
```
Client A ──write──▶ ┌─────────────┐
Client B ──write──▶ │ Write Queue │──▶ SQLite WAL
Client C ──write──▶ └─────────────┘      (單一 writer)
Client A ──read───▶ SQLite WAL（多 reader 並行）
```

**寫入序列化**：所有寫入操作透過 `asyncio.Queue` 或 threading `Queue` 序列化，讀取可並行。

**衝突偵測**：
- 相同 node_id 的並發寫入：後者基於最新版本（CAS，已有 A-07 基礎）
- 語意衝突：`find_conflicts()` 在寫入後非同步觸發

#### 實作步驟

**步驟 1**：`BrainDB` 新增 `WriteSerialization` mode
```python
class BrainDB:
    def __init__(self, brain_dir, *, serialized_writes=False):
        if serialized_writes:
            self._write_queue = queue.Queue()
            self._write_thread = threading.Thread(target=self._write_worker)
            self._write_thread.daemon = True
            self._write_thread.start()
```

**步驟 2**：`brain serve --mode central` flag
- 啟動時自動開啟 `serialized_writes=True`
- 讀取連線使用 connection pool（最多 10 個讀取連線）

**步驟 3**：知識歸屬（Attribution）
- `add_knowledge` tool 新增 `author` 欄位（從 API key 解析 user_id）
- `nodes.author` 欄位已存在，補充 audit 記錄

**步驟 4**：衝突通知
- 寫入後若 `find_conflicts()` 發現衝突 → emit `KNOWLEDGE_CONFLICT` signal
- 衝突摘要可透過 `brain_status` 工具回傳

#### 測試計劃

```python
# tests/unit/test_central_brain_writes.py
class TestSerializedWrites:
    def test_100_concurrent_writes_all_succeed(self, tmp_path):
        """100 threads 並發 add_knowledge → 100 條都寫入（無丟失）"""
    def test_write_order_preserved(self, tmp_path):
        """序列化後寫入順序 FIFO"""
    def test_read_does_not_block_write(self, tmp_path):
        """讀取操作不阻塞寫入佇列"""

class TestAttribution:
    def test_add_knowledge_records_author(self, tmp_path):
        """add_knowledge 附帶 author → nodes.author 有值"""
    def test_different_authors_coexist(self, tmp_path):
        """兩個 author 分別加入知識 → 查詢時可按 author 過濾"""
```

#### 驗收條件

- [x] 100 threads 並發寫入無資料丟失（`serialized_writes=True`，Write Queue FIFO）
- [x] 讀取不被寫入阻塞（WAL concurrent readers，測試驗證）
- [x] 每條知識有 `author`/`source` 歸屬記錄（v0.46.0 已完成）
- [x] `brain health` 顯示 central mode 狀態（`_check_central_mode()`）
- [x] RBAC：`api_keys` table + `store/resolve/revoke_api_key` + `has_permission`
- [x] MCP tools 權限守衛：`add_knowledge`/`complete_task`/`report_knowledge_outcome` 需 contributor+
- [x] `brain serve --mcp --mode central` CLI flag
- [x] 33 tests（`test_write_queue.py` 14 + `test_rbac.py` 19）

#### 實際實作

- **Write Queue**：`_WriteRequest` + `_write_worker` + `_enqueue_write_fn` + `@_serialize_if_needed` decorator
- **RBAC**：`rbac.py`（`ROLE_HIERARCHY`/`TOOL_PERMISSIONS`/`has_permission`）+ Schema v29（`api_keys` table）
- **Auth**：`AuthMiddleware` 雙模式（legacy key + RBAC）+ `contextvars.ContextVar("brain_role")`
- **Plumbing**：`BrainServer(mode=)` → `ProjectBrain(serialized_writes=)` → `BrainDB(serialized_writes=)`

---

### E-03 Client Connect 模式（個人 Brain 疊加查詢）[DONE v0.50.0]

**ID**：E-03
**優先**：P2
**依賴**：E-01（HTTP transport）、E-02（central mode）
**估計工作量**：12h

#### 設計

每個工程師的本地 Claude Code 可以：
1. **純連線模式**：直接連 central brain（無本地 brain）
2. **疊加模式**：本地 brain 優先，查詢不到才 fallback 到 central brain

**查詢流程（疊加模式）**：
```
get_context("JWT auth")
    │
    ├──▶ 本地 brain.db 搜尋 → 有結果 → 回傳（本地優先）
    │
    └──miss──▶ Central Brain (HTTP MCP) 搜尋 → 有結果 → 回傳
                  │
                  └──miss──▶ LLM fallback（現有行為）
```

**配置方式**（`brain.toml`）：
```toml
[team]
central_brain_url = "http://brain.company.internal:3000/mcp"
central_brain_key = "${BRAIN_API_KEY}"
mode = "overlay"  # "overlay" | "central-only" | "local-only"
overlay_threshold = 0.6  # local 結果 confidence < 0.6 時也查 central
```

#### 實作步驟

**步驟 1**：`BrainConfig` 支援 `[team]` section
```python
@dataclass
class TeamConfig:
    central_brain_url: str = ""
    central_brain_key: str = ""
    mode: str = "local-only"
    overlay_threshold: float = 0.6
```

**步驟 2**：`integrations/central_brain_client.py`（新模組）
```python
class CentralBrainClient:
    """透過 HTTP MCP 呼叫 central brain 的 MCP tools"""
    def __init__(self, url: str, api_key: str):
        self._url = url
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def search_knowledge(self, query: str, limit: int = 5) -> list[dict]:
        """呼叫 central brain 的 search_knowledge MCP tool"""
        ...

    def get_context(self, task: str, workdir: str) -> str:
        """呼叫 central brain 的 get_context MCP tool"""
        ...
```

**步驟 3**：`ProjectBrain.get_context()` 支援 overlay
```python
def get_context(self, task: str, **kw) -> ContextResult:
    local_result = self._local_search(task)
    if self._team_config.mode == "overlay":
        if local_result.confidence < self._team_config.overlay_threshold:
            central_result = self._central_client.get_context(task)
            return ContextResult.merge(local_result, central_result)
    return local_result
```

**步驟 4**：`brain connect` CLI 命令（新增）
```bash
# 設定連線到 central brain
brain connect http://brain.company.internal:3000 --key $BRAIN_API_KEY --mode overlay

# 測試連線
brain connect --test

# 中斷連線（回到本地模式）
brain connect --disconnect
```

#### 測試計劃

```python
# tests/unit/test_central_brain_client.py
class TestCentralBrainClient:
    def test_search_falls_back_to_central_on_local_miss(self, tmp_path, mock_central):
        """本地無結果 → fallback 到 mock central brain"""
    def test_overlay_merges_local_and_central(self, tmp_path, mock_central):
        """本地 + central 結果合併，本地排前"""
    def test_central_unavailable_returns_local_only(self, tmp_path):
        """central brain 不可達 → graceful degradation，只用本地"""
    def test_connect_cmd_writes_brain_toml(self, tmp_path):
        """brain connect ... → brain.toml [team] section 更新"""
    def test_local_only_mode_never_hits_central(self, tmp_path, mock_central):
        """local-only 模式下不發出任何 HTTP 請求"""

class TestOverlayThreshold:
    def test_high_confidence_local_skips_central(self, tmp_path, mock_central):
        """local confidence ≥ threshold → 不查 central"""
    def test_low_confidence_local_triggers_central(self, tmp_path, mock_central):
        """local confidence < threshold → 補查 central"""
```

#### 驗收條件

- [x] `brain connect` 命令設定成功，寫入 brain.toml（`[team]` section）
- [x] overlay 模式下本地優先，miss 時查 central（get_context + search_knowledge）
- [x] central 不可達時 graceful degradation（不 crash，返回空結果）
- [x] `brain connect --test` 驗證連線可用性（ping + search_knowledge probe）
- [x] `brain connect --disconnect` 回到 local-only 模式
- [x] env var override：`BRAIN_TEAM_URL` / `BRAIN_TEAM_KEY` / `BRAIN_TEAM_MODE`
- [x] 24 tests（`test_central_brain_client.py` 10 + `test_team_config.py` 14）

#### 實際實作

- **`brain_config.py`**：`TeamConfig` dataclass + `[team]` section parsing + env var override
- **`integrations/central_brain_client.py`**（新模組）：stdlib urllib JSON-RPC client，MCP session init + tools/call
- **`interfaces/mcp_server.py`**：`_get_central_client()` helper + overlay 邏輯於 get_context / search_knowledge
- **`interfaces/cli_connect.py`**（新模組）：`brain connect` CLI（connect/test/status/disconnect）
- **`interfaces/cli.py`** + **`cli_utils.py`**：dispatch + subparser 註冊

---

### E-04 知識 Ingestion Pipeline（公司文件匯入）[DONE v0.51.0]

**ID**：E-04
**優先**：P2
**依賴**：E-02（需要 central brain 運行）
**估計工作量**：24h

#### 設計

讓公司現有文件系統（Confluence、GitHub、Slack、本地檔案）的內容自動轉換為 Brain 知識節點。

**支援的資料源**：

| 資料源 | 命令 | 知識類型 |
|--------|------|---------|
| GitHub Issues/PRs | `brain ingest github` | Pitfall、Decision |
| GitHub README/Wiki | `brain ingest github --docs` | Rule、Component |
| Confluence | `brain ingest confluence` | Decision、Rule |
| Slack（匯出檔） | `brain ingest slack` | Pitfall、Note |
| 本地 Markdown | `brain ingest files` | 全部類型 |
| JIRA | `brain ingest jira` | Pitfall、Decision |

**Ingestion Pipeline**（每個資料源共用）：

```
原始文件
    │
    ▼
[Chunker]          按段落/章節分割，512 tokens max
    │
    ▼
[LLM Extractor]    提取 title、content、kind、confidence
    │
    ▼
[Deduplicator]     與現有知識庫比對，避免重複
    │
    ▼
[KRB Staging]      信心 < 0.7 → 進 staging 待審；≥ 0.7 → 直接寫入
    │
    ▼
brain.db（L3）
```

#### 實作步驟

**步驟 1**：`integrations/ingest/` 目錄結構
```
project_brain/integrations/ingest/
├── __init__.py
├── base.py          # IngestSource Protocol + IngestResult dataclass
├── github.py        # GitHubIngestSource
├── confluence.py    # ConfluenceIngestSource
├── slack.py         # SlackIngestSource
├── files.py         # LocalFilesIngestSource
└── chunker.py       # TextChunker（共用）
```

**步驟 2**：`base.py` — 共用介面
```python
class IngestSource(Protocol):
    def fetch(self) -> list[RawDocument]:
        """從資料源取得原始文件列表"""

    def extract_knowledge(self, doc: RawDocument,
                          llm: LLMClient) -> list[KnowledgeCandidate]:
        """用 LLM 從文件提取知識候選"""

@dataclass
class RawDocument:
    source: str        # "github:issues:123"
    title: str
    content: str
    url: str
    metadata: dict

@dataclass
class KnowledgeCandidate:
    title: str
    content: str
    kind: str
    confidence: float
    source_url: str
    tags: list[str]
```

**步驟 3**：`github.py` — GitHub Ingest
```python
class GitHubIngestSource:
    def __init__(self, repo: str, token: str, types=["issues", "prs", "wiki"]):
        self._repo = repo
        self._headers = {"Authorization": f"token {token}"}

    def fetch(self) -> list[RawDocument]:
        """GitHub REST API 取 issues/PRs/Wiki"""
        ...

    # Prompt template
    _EXTRACT_PROMPT = """
    以下是 GitHub Issue/PR 的內容。
    請提取其中可作為團隊知識保存的條目。

    標題：{title}
    內容：{body}
    標籤：{labels}

    若此 Issue 描述一個 bug 或問題 → kind=Pitfall
    若此 PR 描述一個架構決策 → kind=Decision
    若此內容描述一個規範或約束 → kind=Rule

    輸出 JSON 陣列（可能為空）：
    [{"title": "...", "content": "...", "kind": "...", "confidence": 0.0-1.0, "tags": [...]}]
    """
```

**步驟 4**：`files.py` — 本地 Markdown Ingest
```python
class LocalFilesIngestSource:
    def __init__(self, path: Path, glob: str = "**/*.md"):
        self._path = path
        self._glob = glob

    def fetch(self) -> list[RawDocument]:
        """遞迴掃描 Markdown 檔案，按標題分段"""
        ...
```

**步驟 5**：CLI 命令
```bash
brain ingest github --repo org/repo --token $GITHUB_TOKEN [--types issues,prs,wiki]
brain ingest confluence --url https://company.atlassian.net --user $USER --token $TOKEN --space PROJ
brain ingest slack --export-path ./slack-export.zip [--channels engineering,backend]
brain ingest files --path ./docs [--glob "**/*.md"] [--dry-run]
```

**步驟 6**：進度追蹤 + 限速
- 批次大小：50 文件 / 批
- LLM rate limiting：10 呼叫 / 分（避免超出 Ollama/Anthropic 限制）
- 進度顯示：`rich` progress bar（可選）
- 乾跑模式：`--dry-run` 只顯示會匯入的內容，不實際寫入

#### 測試計劃

```python
# tests/unit/test_ingest_github.py
class TestGitHubIngest:
    def test_fetch_issues_parses_correctly(self, mock_github_api):
        """mock API 回傳 issues → 正確解析為 RawDocument"""
    def test_bug_issue_extracts_as_pitfall(self, mock_llm):
        """含 bug 標籤的 issue → kind=Pitfall"""
    def test_closed_issues_have_lower_confidence(self, mock_llm):
        """已關閉且無評論的 issue → confidence ≤ 0.5"""
    def test_duplicate_detection_skips_existing(self, tmp_path, mock_github_api):
        """已存在相似節點 → 跳過，不重複匯入"""

# tests/unit/test_ingest_files.py
class TestLocalFilesIngest:
    def test_markdown_chunked_by_headings(self, tmp_path):
        """# 標題分段正確（每段 ≤ 512 tokens）"""
    def test_dry_run_writes_nothing(self, tmp_path):
        """--dry-run 模式下 brain.db 不被修改"""
    def test_glob_pattern_filters_files(self, tmp_path):
        """只匯入符合 glob pattern 的檔案"""

# tests/unit/test_ingest_chunker.py
class TestTextChunker:
    def test_chunks_respect_max_tokens(self):
        """每個 chunk ≤ 512 tokens"""
    def test_overlap_between_chunks(self):
        """相鄰 chunks 有 50 token overlap（避免語意斷裂）"""
    def test_cjk_text_chunks_correctly(self):
        """中文文字按段落分割，不截斷詞語"""
```

#### 驗收條件

- [x] `brain ingest files --path ./docs` 可匯入 Markdown（heading 切分 + heuristic/LLM extraction）
- [x] `brain ingest github --repo org/repo` 正確提取 Issues/PRs（label → kind hint）
- [x] 重複匯入冪等（exact title match + Jaccard ≥ 0.8 → skip）
- [x] `--dry-run` 模式不寫入任何資料
- [x] Confidence routing：≥ 0.7 → L3，< 0.7 → KRB staging
- [x] LLM failure graceful fallback to heuristic
- [x] 42 tests（chunker 14 + files 11 + pipeline 17）

#### 實際實作

- **`integrations/ingest/`** package（6 modules）：`base.py` / `chunker.py` / `files.py` / `github.py` / `pipeline.py` / `__init__.py`
- **`interfaces/cli_ingest.py`**：`brain ingest files|github` CLI
- LLM extraction prompt → JSON array + code fence stripping
- Heuristic extraction：keyword-based kind detection（Pitfall/Decision/Rule/Note）
- GitHub REST API via stdlib `urllib.request`（zero deps）

---

### E-05 個人知識推送到集中庫（Push to Central）[DONE v0.52.0]

**ID**：E-05
**優先**：P3
**依賴**：E-02（central mode）、E-03（client connect）
**估計工作量**：12h

#### 設計

工程師在本地 brain 積累了個人知識後，可以選擇性地推送到 central brain，讓全團隊受益。

**流程**：
```
本地 brain
    │
    ├──▶ brain push --filter "kind=Pitfall confidence>=0.8"
    │           │
    │           ▼
    │    [本地知識節點列表]
    │           │
    │           ▼
    │    [Central KRB Staging]  ← 推送的知識進 staging 待管理員審查
    │           │
    │           ▼（管理員 approve 後）
    │    [Central L3 知識庫]
    │
    └──▶ brain push --direct   # 需要 write 權限（管理員用）
```

**權限模型**：
```
角色          | add_knowledge | push | approve | admin
─────────────────────────────────────────────────────
reader        |      ❌       |  ❌  |    ❌   |  ❌
contributor   |      ✅       |  ✅  |    ❌   |  ❌
maintainer    |      ✅       |  ✅  |    ✅   |  ❌
admin         |      ✅       |  ✅  |    ✅   |  ✅
```

API Key 攜帶角色資訊：`brain admin create-key --role contributor --name "Alice"`

#### 實作步驟

**步驟 1**：`brain admin` 命令（新增子命令）
```bash
brain admin create-key --role contributor --name "Alice"
# 輸出：BRAIN_KEY_ALICE=brn_c_xxxxxxxx

brain admin list-keys
brain admin revoke-key brn_c_xxxxxxxx
brain admin list-users
```

**步驟 2**：API Key 結構
```python
@dataclass
class BrainAPIKey:
    key_id: str       # brn_{role_prefix}_{random}
    role: str         # reader/contributor/maintainer/admin
    name: str         # 人類可讀名稱
    created_at: str
    expires_at: str   # None = 不過期

# brain_meta 表儲存 key 列表（加密 hash）
# "api_keys" → JSON array of BrainAPIKey
```

**步驟 3**：`brain push` CLI 命令
```bash
# 推送本地高信心 Pitfall 到 central
brain push --to http://brain.company.internal:3000 \
           --key $BRAIN_API_KEY \
           --filter "kind=Pitfall" \
           --min-confidence 0.8 \
           --dry-run  # 先看要推送什麼

# 確認後實際推送
brain push --to http://brain.company.internal:3000 \
           --key $BRAIN_API_KEY \
           --filter "kind=Pitfall" \
           --min-confidence 0.8
```

**步驟 4**：`mcp_server.py` 新增 `push_to_central` MCP tool
```python
@mcp_tool("push_to_central")
def push_to_central(node_ids: list[str], target_url: str, api_key: str) -> dict:
    """推送指定節點到 central brain（進 staging）"""
    ...
```

#### 測試計劃

```python
# tests/unit/test_push_to_central.py
class TestPushToCentral:
    def test_push_sends_to_central_staging(self, tmp_path, mock_central):
        """push → central KRB staging 有新條目"""
    def test_push_dry_run_does_not_write(self, tmp_path, mock_central):
        """--dry-run → central 無任何變更"""
    def test_push_filter_by_confidence(self, tmp_path, mock_central):
        """--min-confidence 0.8 → 只推送高信心節點"""
    def test_contributor_cannot_push_direct(self, tmp_path):
        """contributor 角色無法使用 --direct 繞過 staging"""
    def test_admin_can_push_direct(self, tmp_path):
        """admin 角色可以直接寫入 L3"""

class TestAPIKeyManagement:
    def test_create_key_stores_in_brain_meta(self, tmp_path):
        """create-key → brain_meta 有加密 hash"""
    def test_revoked_key_rejected(self, tmp_path):
        """revoke-key 後，使用該 key 的請求被拒絕 (401)"""
    def test_contributor_key_cannot_approve(self, tmp_path):
        """contributor key 呼叫 approve 端點 → 403"""
```

#### 驗收條件

- [x] `brain push` 成功推送至 central KRB staging（via CentralBrainClient.add_knowledge）
- [x] 角色權限正確（push_to_central 需 contributor+，RBAC 驗證）
- [x] 管理員可透過 `brain admin create-key/list-keys/revoke-key` 管理 API keys
- [x] `--dry-run` 不寫入任何資料（preview 模式）
- [x] PII 清理（複用 federation._strip_pii）
- [x] 節點篩選：kind + min_confidence + max_nodes
- [x] 26 tests（`test_push_central.py` 18 + `test_admin_keys_cli.py` 8）

#### 實際實作

- **`integrations/push_central.py`**（新模組）：`PushTransport`（select/sanitize/push/preview）
- **`integrations/central_brain_client.py`**：新增 `add_knowledge()` 方法
- **`interfaces/cli_push.py`**（新模組）：`brain push` CLI
- **`interfaces/cli_admin_keys.py`**（新模組）：`brain admin create-key/list-keys/revoke-key`
- **`interfaces/mcp_server.py`**：`push_to_central` MCP tool
- **`rbac.py`**：新增 `push_to_central: contributor`

---

### E-06 運維 Agent 整合（公司級 DevOps AI）

**ID**：E-06
**優先**：P3（依賴 E-01~E-05 全部完成）
**依賴**：所有 Phase E 前置項目
**估計工作量**：24h

#### 設計願景

完成 E-01~E-05 後，整個系統可以支撐以下使用場景：

**場景一：新工程師加入**
```bash
# 新工程師的第一條命令
brain connect http://brain.company.internal:3000 --key $BRAIN_API_KEY --mode overlay

# 之後，任何 Claude Code 查詢都能取得公司知識
brain ask "我們的 JWT 簽名規範是什麼？"
# → 回答來自 central brain（所有同事的知識積累）
```

**場景二：事故後記錄**
```bash
# 事故發生後，工程師記錄教訓
brain add "PostgreSQL 連線池耗盡導致 API 全 timeout" --kind Pitfall

# 下次另一個工程師遇到類似問題
brain ask "為什麼 API 會 timeout？"
# → 直接取得同事記錄的 Pitfall
```

**場景三：自動從 PR/Issue 學習**
```bash
# CI 每天自動執行
brain ingest github --repo org/backend --since yesterday --token $GH_TOKEN
# → 自動從 merged PRs 和 closed issues 提取知識
```

#### 運維 Agent 設定（CLAUDE.md 範本）

每個工程師的 CLAUDE.md 加入：
```markdown
## Team Brain 整合

你連接到公司集中知識庫（central brain）。在開始任何任務前：

1. 呼叫 `get_context` 取得相關公司知識
2. 若你發現 bug 或架構決策，呼叫 `add_knowledge` 記錄
3. 完成任務後呼叫 `complete_task`

Central Brain URL：http://brain.company.internal:3000
（已透過 claude_desktop_config.json 設定，直接使用 MCP tools 即可）
```

#### 系統管理工具

**步驟 1**：`brain admin dashboard`（新增）
```bash
brain admin dashboard
# 輸出：
Team Brain Dashboard — 2026-05-01
=====================================
Total knowledge nodes: 4,821
Contributors: 12 (last 30 days: 8 active)
Top contributors:
  Alice: 342 nodes (Pitfall: 156, Decision: 89, Rule: 97)
  Bob:   287 nodes ...

Signal activity (last 7 days):
  MCP_TOOL_CALL: 1,247 signals, 89 → L3
  GIT_COMMIT:    412 signals, 156 → L3
  TEST_FAILURE:   67 signals, 23 → L3

Knowledge health:
  [OK] 0 conflicts detected
  [WARN] 12 nodes with confidence < 0.5 (review recommended)
```

**步驟 2**：`brain admin audit-log`
```bash
brain admin audit-log --since 2026-05-01 --user alice
# 輸出每一條知識的 who/what/when
```

**步驟 3**：Prometheus metrics 端點（`/metrics`）
```
# Central Brain Prometheus metrics
brain_nodes_total{kind="Pitfall"} 1823
brain_nodes_total{kind="Decision"} 734
brain_active_users_7d 8
brain_knowledge_added_today 34
brain_conflicts_open 0
```

#### 測試計劃

```python
# tests/integration/test_team_brain_e2e.py
class TestTeamBrainE2E:
    """完整的團隊共享腦 E2E 測試（需要本地 HTTP server）"""

    def test_new_engineer_connects_and_queries(self, central_server):
        """模擬新工程師：connect → ask → 取得知識"""

    def test_two_engineers_share_knowledge(self, central_server):
        """Alice add_knowledge → Bob get_context → Bob 取得 Alice 的知識"""

    def test_ingest_and_query(self, central_server, tmp_md_files):
        """ingest markdown → 等待處理 → search_knowledge 可找到"""

    def test_contributor_push_requires_approval(self, central_server):
        """contributor push → staging → maintainer approve → L3"""

    def test_admin_dashboard_shows_stats(self, central_server):
        """dashboard 顯示正確的 contributor 數和節點數"""
```

#### 驗收條件

- [ ] 新工程師可在 5 分鐘內完成設定並查詢公司知識
- [ ] 兩個工程師的知識在 central brain 正確合併（無衝突）
- [ ] Prometheus metrics 可被 Grafana 採集
- [ ] `brain admin dashboard` 顯示正確統計
- [ ] E2E 測試在 CI 環境通過（需要 mock HTTP server）

---

### Phase E 完成驗收

```bash
# E-01：HTTP server 啟動
brain serve --bind 0.0.0.0 --port 3000 --auth-key testkey &
curl -H "Authorization: Bearer testkey" http://localhost:3000/health
# 預期：{"status": "ok", "version": "2.0.0"}

# E-03：客戶端連線
brain connect http://localhost:3000 --key testkey --mode overlay
brain ask "JWT 簽名規範"
# 預期：取得 central brain 的知識

# E-04：Ingestion
brain ingest files --path ./docs --dry-run
# 預期：顯示會匯入的知識清單（不寫入）

# E-05：推送個人知識
brain push --to http://localhost:3000 --key testkey --min-confidence 0.8 --dry-run

# E-06：Dashboard
brain admin dashboard

# 全量測試（≥ 1800 passed）
python -m pytest tests/ -q | tail -3
```

---

## 8. 完整依賴關係圖

```
Phase A (v0.31~v0.34) ✅ 全部完成
├── A-01 雙 DB 寫入原子化
├── A-02 假 ERROR log 修復
├── A-03 workdir 路徑驗證
├── A-04 同義詞展開上界
├── A-05 LLMJudgmentEngine ──────────────────────────────┐
├── A-06 Federation 測試套件                              │
├── A-07 CAS 樂觀鎖                                      │
├── A-08 find_conflicts 優化                              │
├── A-09 _execute_write 統一入口 ────────────────────────┤
├── A-10 KRB staging 自動清理 ──────────────────────────┤
└── A-11 CI Benchmark Baseline                           │
                                                         │
Phase B (v0.35) ✅ 全部完成                              │
├── B-01 KRB Daemon 整合（依賴 A-10）                    │
├── B-02 KG/BrainDB 事件同步（依賴 A-01）◄───────────────┘
│    └──▶ B-03 brain health（依賴 B-02）
├── B-04 Pipeline metrics（依賴 A-05）
├── B-05 BrainServer 重構（獨立）
├── B-06 _count_tokens 無 cache（獨立）
└── B-07 LOW-01~04 錯誤處理（獨立）
         │
         ▼
Phase C (v0.40) ✅ 全部完成
├── C-01 統一 DB（依賴 B-02 事件同步）
├── C-02 統一 LLM 介面（獨立）
│    ├──▶ C-03 Validator CI（依賴 C-02）
│    └──▶ C-04 Pipeline Phase 2 信號（依賴 C-02）
│              └──▶ C-05 Feedback Loop（依賴 C-04）
│
▼
Phase D (v1.0) 4/5 DONE
├── D-01 LoRA 蒸餾（依賴 C-02，需 GPU）          ⏳ blocked on GPU
├── D-02 WebUI 完整化（依賴 C-01）                ✅ v0.47.0
├── D-03 CI 全覆蓋（依賴 B-03 + C-03）            ✅ v0.42.0
├── D-04 生產驗證（依賴所有 Phase C）               ✅ v0.43.0
└── D-05 文件完整化（依賴所有功能完成）              ✅ v0.44.0
         │
         ▼
Phase E (v2.0) 5/6 DONE
├── E-01 HTTP MCP Transport                       ✅ v0.45.0
│    └──▶ E-02 Central Brain 多用戶寫入安全        ✅ v0.49.0
│              └──▶ E-03 Client Connect 疊加查詢   ✅ v0.50.0
│                   └──▶ E-05 個人知識推送          ✅ v0.52.0
├── E-04 Ingestion Pipeline（依賴 E-02）           ✅ v0.51.0
└── E-06 運維 Agent 整合（依賴 E-01~E-05 全部）     ✅ v0.53.0
```

---

## 9. 模型選擇速查表

> 開發時用此表快速選擇 Claude 開發模型。

| 任務類型 | 推薦模型 | 理由 |
|---------|---------|------|
| 單行/單函式修補（< 20 行，< 1h） | **Haiku 4.5** | 成本最低，無需長 context |
| 測試編寫、標準功能實作（1-12h，2-4 個檔案） | **Sonnet 4.6** | 品質與成本平衡 |
| 事務/並發/安全邊界修改 | **Sonnet 4.6 最少** | 需要審慎推理 |
| 架構設計、新模組、Schema 遷移、跨 5+ 檔案 | **Opus 4.6 (1M)** | 需長 context + 一次吞下全貌 |
| HTTP 協定設計、多用戶安全 | **Opus 4.6 (1M)** | 安全邊界複雜，需整體把握 |
| LLM 研究（LoRA、Prompt 設計） | **Opus 4.6 (1M)** | 研究級複雜度 |

| Phase | 主要模型分佈 |
|-------|------------|
| A（已完成） | Haiku 4h / Sonnet 23h / Opus 12h |
| B（已完成） | Haiku 4h / Sonnet 12h / Opus 0h |
| C（已完成） | Haiku 0h / Sonnet 16h / Opus 44h |
| D | Opus 40h+ / Sonnet 20h / Haiku 4h |
| E | Opus 48h / Sonnet 48h / Haiku 8h |

---

## 10. 品質門檻

每個 Phase 完成後必須滿足：

| 指標 | Phase C 實際 | Phase D 目標 | Phase E 目標 |
|------|------------|------------|------------|
| Unit tests passed | 1367 ✅ | ≥ 1500 | ≥ 1800 |
| 測試覆蓋率 | ≥ 50% | ≥ 60% | ≥ 65% |
| recall@3 | ≥ 60% | ≥ 70% | ≥ 75% |
| avg 查詢延遲（本地） | ≤ 500ms | ≤ 300ms | ≤ 300ms |
| avg 查詢延遲（central） | N/A | N/A | ≤ 500ms |
| 並發寫入（central） | N/A | N/A | 100 threads，0 丟失 |
| `brain health` 輸出 | all [OK] ✅ | all [OK] | all [OK] |
| CI 通過 | 手動 | GitHub Actions ✅ | GitHub Actions ✅ |
| Regression | 0 ✅ | 0 | 0 |

### 每項任務完成前的標準 checklist

```
[ ] get_context — 取得相關 Brain 知識，避免重蹈覆轍
[ ] 先讀相關程式碼，理解現有行為
[ ] 寫測試（先 fail）
[ ] 最小改動實作
[ ] pytest tests/ -q — 全量通過，零 regression
[ ] 更新 CHANGELOG.md（版本 + 變更摘要）
[ ] 更新本文件（標記任務為 [DONE vX.Y.Z]，更新快照數字）
[ ] complete_task（記錄 decisions/lessons/pitfalls）
[ ] 必要時 add_knowledge（Pitfall/Decision/Rule）
[ ] 若用到既有知識節點，report_knowledge_outcome（回饋有用/無用）
```

---

## 11. 歸檔文件索引

以下文件已移至 `docs/archive/`，僅供歷史參考：

| 文件 | 歸檔原因 | 替代文件 |
|------|---------|---------|
| `docs/archive/BRAIN_MASTER_v0.2.md` | v0.2.0（2026-04-03），架構已大幅演進 | 本文件 §2 系統現況快照 |
| `docs/archive/COMPLETED_HISTORY_pre_v0.30.md` | 記錄 v0.1.1~v1.0.0（舊版號）的 76 個已完成項目 | `CHANGELOG.md` |
| `docs/archive/IMPROVEMENT_PLAN_v0.30.md` | v0.30.0 改善規劃（2026-04-06），大部分已完成或整合進本文件 | 本文件 Phase B+ |

> **注意**：`docs/AUTO_KNOWLEDGE_PIPELINE.md` 保留為 Pipeline Layer 1-5 的**技術設計參考**（Prompt 設計、資料模型、可靠性策略），不歸檔。
