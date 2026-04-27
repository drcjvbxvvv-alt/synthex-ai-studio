# Project Brain — 完整測試計劃文件

> **版本**：v1.0（v0.43.0，2026-04-27）
> **用途**：記錄所有測試項目的計劃、狀態、覆蓋範圍與品質門檻。
> **測試基準**：1029 passed（unit + e2e），零 regression（D-02~D-04 全程維持）

---

## 目錄

1. [測試套件全覽](#1-測試套件全覽)
2. [單元測試（Unit）](#2-單元測試-unit)
3. [E2E 測試](#3-e2e-測試)
4. [整合測試（Integration）](#4-整合測試-integration)
5. [Chaos & 負載測試](#5-chaos--負載測試)
6. [基準測試（Benchmark）](#6-基準測試-benchmark)
7. [文件準確性測試](#7-文件準確性測試)
8. [品質門檻總表](#8-品質門檻總表)
9. [執行指令速查](#9-執行指令速查)

---

## 1. 測試套件全覽

```
tests/
├── TEST_PLAN.md                           ← 本文件
├── unit/                                  ← 1016 tests
│   ├── test_core.py                       核心：BrainDB、Graph、Router、ContextEngineer
│   ├── test_session_store.py              L1a SessionStore
│   ├── test_health.py                     HealthChecker JSON 格式 (B-03)
│   ├── test_knowledge_validator_ci.py     KnowledgeValidator CI mode (C-03)
│   ├── test_ci_integration.py             CI pipeline 完整驗證 (D-03, 45 tests)
│   ├── test_prod_validation.py            生產驗證：Federation + PII + dedup (D-04, 19 tests)
│   ├── test_web_ui_edit.py               WebUI PATCH/DELETE + KRB staging (D-02, 33 tests)
│   ├── test_federation.py                Federation export/import/dedup/PII
│   ├── test_pipeline_signal.py           SignalQueue Layer 1/2
│   ├── test_pipeline_worker.py           PipelineWorker lifecycle + batch
│   ├── test_pipeline_executor.py         KnowledgeExecutor add/skip/idempotent
│   ├── test_pipeline_phase2_signals.py   Phase 2 signal types
│   ├── test_pipeline_stats.py            Pipeline Metrics Dashboard (B-04)
│   ├── test_llm_judgment.py              LLMJudgmentEngine + KnowledgeDecision
│   ├── test_feedback_loop.py             C-05 Feedback Loop (19 tests)
│   ├── test_find_conflicts.py            C-04 KnowledgeConflictDetector
│   ├── test_kg_braindb_sync.py           B-02 KG→BrainDB Observer sync
│   ├── test_krb_cleanup.py               MEDIUM-04 KRB staging auto-cleanup
│   ├── test_krb_daemon_integration.py    KRB daemon integration
│   ├── test_health.py                    B-03 HealthChecker
│   ├── test_db_unification.py            C-01 unified brain.db schema
│   ├── test_graph_cas.py                 CAS concurrent write safety
│   ├── test_mcp_server_isolation.py      MCP server session isolation
│   ├── test_mem_improvements.py          MEM-01~06 記憶系統改善
│   ├── test_llm_client.py               OllamaClient + fallback
│   ├── test_execute_write.py             write guard + idempotent
│   ├── test_low_fixes.py                 低優先修正項
│   ├── test_benchmark_baseline_meta.py   baseline.json schema validation
│   ├── test_arch_decisions_v01.py        ADR: WAL、衰減不刪節點
│   ├── test_arch_decisions_v02.py        ADR: BRAIN_WORKDIR、查詢展開
│   ├── test_arch_decisions_v03.py        ADR: OllamaClient、MultilingualEmbedder
│   ├── test_arch_decisions_v04.py        ADR: VISION-01~05 長期願景
│   ├── test_arch_decisions_v05.py        ADR: 靜默失效、FLY-01/02
│   ├── test_arch_decisions_v06.py        ADR: NudgeEngine、Synonym Map
│   ├── test_ref04_constants.py           REF-04 魔法數字提取
│   ├── test_perf03_token_cache.py        PERF-03 Token 計數快取
│   └── test_bug_a03_locking.py          BUG-A03 雙重加鎖修復
│
├── e2e/                                   ← 14 tests
│   └── test_pipeline_e2e.py              Signal→Judge→Executor→L3 E2E (D-04)
│
├── integration/                           ← 67 tests
│   ├── test_cli.py                        CLI 命令端對端
│   ├── test_phase2.py                     Phase 2 功能整合
│   ├── test_q2.py                         Q2 查詢流程
│   └── test_web_ui.py                     Web UI 端點（4 pre-existing failures）
│
├── chaos/                                 ← @pytest.mark.chaos
│   ├── test_chaos_and_load.py             Chaos & 負載測試
│   └── test_decay_load.py                 100K 節點衰減負載
│
├── benchmarks/                            ← @pytest.mark.benchmark
│   ├── benchmark_recall.py               50-node 召回率量測腳本
│   ├── benchmark_perf_5k.py              5000-node 效能基準 (D-04, 5 tests)
│   ├── benchmark_rev01.py                REV-01 量化對照實驗
│   ├── baseline.json                     MEDIUM-07 baseline 門檻
│   ├── test_baseline_regression.py       baseline 回歸檢查（4 tests，CI 必跑）
│   └── update_baseline.py                baseline.json 更新腳本
│
└── test_chaos_and_load.py                 ← chaos 舊路徑（保持相容）
```

**圖例**：
- ✅ 已通過 — 程式碼已實作，測試在 CI 中穩定通過
- 📋 測試計劃已寫 — 等待程式碼實作（D-01 LoRA 相關）
- △ 需真實數據 — 邏輯已實作，需累積線上數據後量測
- ⏳ 待規劃 — 尚未有測試文件

---

## 2. 單元測試（Unit）

### 2.1 核心功能 — `test_core.py` ✅

| 測試類別 | 覆蓋功能 | 狀態 |
|---------|---------|------|
| `TestBrainDB` | add/get/update/delete/search_nodes CRUD | ✅ |
| `TestKnowledgeGraph` | L3 圖節點 + FTS5 搜尋 | ✅ |
| `TestContextEngineer` | context.build() token 預算 + SR 排序 | ✅ |
| `TestRouter` | 三層路由（L1a / L2 / L3 並行） | ✅ |
| `TestDecayEngine` | 信心衰減計算、pinning 保護 | ✅ |
| `TestNudgeEngine` | check() 返回相關 nudge | ✅ |

### 2.2 Phase B — 可觀測性與維護性 ✅

| 測試檔案 | 功能 | tests | 狀態 |
|---------|------|-------|------|
| `test_health.py` | B-03 HealthChecker JSON 結構 | ~20 | ✅ |
| `test_pipeline_stats.py` | B-04 Pipeline Metrics Dashboard | ~25 | ✅ |
| `test_kg_braindb_sync.py` | B-02 KG→BrainDB Observer sync | ~15 | ✅ |
| `test_krb_cleanup.py` | MEDIUM-04 KRB auto-cleanup | ~10 | ✅ |
| `test_krb_daemon_integration.py` | KRB daemon integration | ~12 | ✅ |

### 2.3 Phase C — 架構演進 ✅

| 測試檔案 | 功能 | tests | 狀態 |
|---------|------|-------|------|
| `test_db_unification.py` | C-01 brain.db 統一 | ~20 | ✅ |
| `test_find_conflicts.py` | C-04 KnowledgeConflictDetector | ~15 | ✅ |
| `test_feedback_loop.py` | C-05 Feedback Loop（含 signal 類型統計）| 19 | ✅ |
| `test_knowledge_validator_ci.py` | C-03 KnowledgeValidator CI mode | ~15 | ✅ |

### 2.4 Phase D — Pipeline & 生產驗證 ✅

| 測試檔案 | 功能 | tests | 狀態 |
|---------|------|-------|------|
| `test_ci_integration.py` | D-03 CI pipeline 依賴驗證 | 45 | ✅ |
| `test_prod_validation.py` | D-04 Federation + PII + dedup | 19 | ✅ |
| `test_web_ui_edit.py` | D-02 WebUI PATCH/DELETE + staging | 33 | ✅ |

### 2.5 Auto-Pipeline ✅

| 測試檔案 | 功能 | 狀態 |
|---------|------|------|
| `test_pipeline_signal.py` | SignalQueue Layer 1/2：enqueue / dequeue / dedup / retry | ✅ |
| `test_pipeline_worker.py` | PipelineWorker lifecycle + batch | ✅ |
| `test_pipeline_executor.py` | KnowledgeExecutor add/skip/idempotent | ✅ |
| `test_pipeline_phase2_signals.py` | Phase 2 signal types（KNOWLEDGE_CONFLICT 等）| ✅ |
| `test_llm_judgment.py` | LLMJudgmentEngine + KnowledgeDecision | ✅ |

### 2.6 Federation ✅

| 測試類別 | 覆蓋功能 | 狀態 |
|---------|---------|------|
| `TestPIIStripping` | 6 個 regex：email / internal host / private IP / Slack / cloud URL | ✅ |
| `TestExportRoundTrip` | export → JSON → from_json 無損 | ✅ |
| `TestFederationImporter` | import_bundle：去重 / 低信心過濾 / KRB staging | ✅ |
| `TestSubscriptionManager` | subscribe / unsubscribe / list / is_subscribed | ✅ |
| `TestFederationAutoSync` | add/remove source + sync_all | ✅ |
| `TestPIIAtScale`（prod）| 1000 節點 PII 清理完整性 | ✅ |
| `TestDedupAtScale`（prod）| 300 重複 + 200 novel 節點正確分流 | ✅ |

### 2.7 Architecture Decisions ✅

| 測試檔案 | 版本 | 關鍵 ADR |
|---------|------|---------|
| `test_arch_decisions_v01.py` | v0.1.0 | WAL mode、衰減不刪節點 |
| `test_arch_decisions_v02.py` | v0.2.0 | BRAIN_WORKDIR 自動偵測、查詢展開 |
| `test_arch_decisions_v03.py` | v0.3.0 | OllamaClient、MultilingualEmbedder |
| `test_arch_decisions_v04.py` | v0.4.0 | VISION-01~05 長期願景 |
| `test_arch_decisions_v05.py` | v0.5.0 | 靜默失效、FLY-01/02 |
| `test_arch_decisions_v06.py` | v0.6.0 | NudgeEngine、Synonym Map |

---

## 3. E2E 測試

**檔案**：`tests/e2e/test_pipeline_e2e.py`（14 tests，1 skipped）

| 測試類別 | 覆蓋功能 | 狀態 |
|---------|---------|------|
| `TestSignalToL3Flow` | signal→stub judge→executor→BrainDB 完整資料流 | ✅ |
| `TestPipelineLatency` | 單 signal < 5s；batch 10 < 30s | ✅ |
| `TestPipelineWorkerLifecycle` | daemon thread start/stop/double-start/auto-process | ✅ |
| `TestPipelineOllama` | 真實 LLM（`BRAIN_TEST_OLLAMA=1` 才執行）| skip（CI 安全）|

**執行**：
```bash
# 無 Ollama（預設）
pytest tests/e2e/ -v

# 含 Ollama（本地開發）
BRAIN_TEST_OLLAMA=1 pytest tests/e2e/ -m e2e_ollama -v
```

---

## 4. 整合測試（Integration）

**目錄**：`tests/integration/`（67 tests）

| 測試檔案 | 覆蓋功能 | 狀態 |
|---------|---------|------|
| `test_cli.py` | CLI 命令端對端（init / add / ask / status） | ✅ |
| `test_phase2.py` | Phase 2 功能整合（scan / federation / pipeline）| ✅ |
| `test_q2.py` | Q2 查詢流程（context / search / review）| ✅ |
| `test_web_ui.py` | Web UI HTTP 端點 | ⚠️ 4 pre-existing failures（schema 不一致）|

> **pre-existing failures（test_web_ui.py 4 個）**：
> Raw `_Handler` 直接建立 KG-only schema，缺少 BrainDB 的 `scope` 欄位。
> 這是已知的架構不一致，不影響 Flask 路由（Flask 測試全部通過）。
> 已記錄為 technical debt，待 C-01 完整實作後修復。

---

## 5. Chaos & 負載測試

**執行條件**：`@pytest.mark.chaos`，需明確 `-m chaos` 才觸發

| 測試類別 | 覆蓋功能 | 狀態 |
|---------|---------|------|
| `TestV52L2HealthCheck` | L2 健康檢查函式存在性 | ⚠️ 1 pre-existing failure |
| `TestV81InterviewNonInteractive` | CLI interview dispatch audit | ⚠️ 1 pre-existing failure |
| `TestV81SSEEndpoint` | SSE 路由 + Cache-Control header | ⚠️ 2 pre-existing failures |
| `TestV90Schema` | schema migration 向下相容 | ⚠️ 1 pre-existing failure |
| `TestV90LocalOnlyInit` | local-only init env 設定 | ⚠️ 2 pre-existing failures |
| `TestDecayLoad` | 100K 節點衰減負載（時間 budget）| ⚠️ 1 pre-existing failure |

> **注意**：上述 chaos failures 為 pre-existing（v0.33 前遺留），不影響 CI `unit` job。

---

## 6. 基準測試（Benchmark）

**執行條件**：`@pytest.mark.benchmark`，`pytest -m benchmark`

### 6.1 基準回歸測試（CI 必跑）

**檔案**：`tests/benchmarks/test_baseline_regression.py`（4 tests）

| 測試 | 門檻 | 說明 |
|------|------|------|
| `test_recall_at_3_no_regression` | ≥ 0.60 | FTS5 召回率，50-node corpus |
| `test_avg_latency_no_regression` | ≤ 500ms | 平均查詢延遲 |
| `test_p100_latency_no_regression` | ≤ 2000ms | p100 查詢延遲 |
| `test_metric_envelope_sanity` | baseline.json schema 正確 | meta 驗證 |

### 6.2 5K 效能基準（D-04）

**檔案**：`tests/benchmarks/benchmark_perf_5k.py`（5 tests）

| 測試 | 門檻 | 說明 |
|------|------|------|
| `test_bulk_write_5000_nodes_throughput` | ≥ 200 nodes/s | 批次寫入吞吐量 |
| `test_fts5_search_p99_latency` | ≤ 300ms | FTS5 p99 搜尋延遲 |
| `test_fts5_search_avg_latency` | ≤ 100ms | FTS5 平均搜尋延遲 |
| `test_braindb_search_p99_latency` | ≤ 300ms | BrainDB hybrid search p99 |
| `test_braindb_search_returns_results` | isinstance(list) | 搜尋不 crash |

### 6.3 召回率量測腳本

```bash
# 執行 50-node recall 量測
python tests/benchmarks/benchmark_recall.py

# 更新 baseline.json
python tests/benchmarks/update_baseline.py
python tests/benchmarks/update_baseline.py --tighten   # 收緊門檻
```

---

## 7. 文件準確性測試

**檔案**：`tests/unit/test_docs_accuracy.py`（D-05 新增）

驗證文件與程式碼的一致性：

| 測試類別 | 覆蓋功能 |
|---------|---------|
| `TestCommandsDocAccuracy` | COMMANDS.md 列出的命令實際存在於 CLI |
| `TestVersionConsistency` | pyproject.toml / CHANGELOG / COMMANDS 版本一致 |
| `TestInstallDocStructure` | INSTALL.md 有必要章節 |
| `TestTestPlanStructure` | TEST_PLAN.md 有必要章節與目錄 |

---

## 8. 品質門檻總表

| 指標 | 門檻 | 現狀（v0.43.0）| CI job |
|------|------|--------------|--------|
| 單元測試通過率 | 100% | ✅ 1016/1016 | `unit` |
| E2E tests 通過率 | 100%（含 skip）| ✅ 13/13 + 1 skip | `unit` |
| Benchmark 基準回歸 | 4/4 passed | ✅ | `benchmark` |
| Coverage（unit + e2e）| ≥ 45% | ✅ ~47% | `coverage` |
| FTS5 recall@3（50 nodes）| ≥ 60% | ✅ 取決於 embedder | `benchmark` |
| FTS5 p99 延遲（5K nodes）| ≤ 300ms | ✅ | - |
| 寫入吞吐量（5K nodes）| ≥ 200 nodes/s | ✅ | - |
| Health JSON valid | ok / warn | ✅ | `health` |
| Validate CI passed | True | ✅ | `validate` |

---

## 9. 執行指令速查

```bash
# 一般開發（快速，排除 benchmark / chaos）
pytest tests/unit/ tests/e2e/ -q -m "not benchmark and not chaos"

# CI unit job
pytest tests/unit/ tests/test_web_ui.py -q --tb=short -m "not benchmark and not chaos"

# Benchmark 回歸（CI benchmark job）
pytest tests/ -m benchmark -q --tb=short

# Coverage 量測（CI coverage job）
pytest tests/unit/ tests/test_web_ui.py tests/benchmarks/ -q -m "not chaos" \
  --cov=project_brain --cov-report=term-missing --cov-fail-under=45

# E2E pipeline（無 Ollama）
pytest tests/e2e/ -v

# E2E pipeline（真實 Ollama）
BRAIN_TEST_OLLAMA=1 pytest tests/e2e/ -m e2e_ollama -v

# Chaos 負載測試（本地，耗時）
pytest tests/ -m chaos -v

# 文件準確性驗證
pytest tests/unit/test_docs_accuracy.py -v

# 全量測試（含 chaos — 需 15+ 分鐘）
pytest tests/ -q
```
