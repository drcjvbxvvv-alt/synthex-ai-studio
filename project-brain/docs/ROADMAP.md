# Project Brain — 總體開發路線圖

> **主要規劃文件**。設計、開發、實作、測試的完整依賴鏈。
>
> **版本**：v1.0
> **建立日期**：2026-04-26
> **基準版本**：v0.34.0（684 passed，0 regression）
> **維護原則**：每個 Phase 完成後在對應區塊標記 `[DONE vX.Y.Z]`，不刪除內容。

---

## 目錄

1. [文件導覽](#1-文件導覽)
2. [系統現況快照](#2-系統現況快照)
3. [Phase A — 基礎鞏固](#3-phase-a--基礎鞏固-done-v0340)
4. [Phase B — 可觀測性與維護性](#4-phase-b--可觀測性與維護性-v035)
5. [Phase C — 架構演進](#5-phase-c--架構演進-v040)
6. [Phase D — 生產就緒](#6-phase-d--生產就緒-v10)
7. [依賴關係圖](#7-依賴關係圖)
8. [模型選擇速查表](#8-模型選擇速查表)
9. [品質門檻](#9-品質門檻)
10. [歸檔文件索引](#10-歸檔文件索引)

---

## 1. 文件導覽

| 文件 | 用途 | 狀態 |
|------|------|------|
| `docs/ROADMAP.md` | **本文件**：規劃、設計、實作、測試全覽 | 主動維護 |
| `docs/ARCHITECTURE_REVIEW.md` | 系統缺陷審計報告（v1.2）；各項缺陷的根因、驗證方法、修法細節 | 審計存檔（規劃已遷移至本文件） |
| `docs/AUTO_KNOWLEDGE_PIPELINE.md` | Pipeline Layer 1-5 設計文件（v0.3.4）；Prompt 設計、資料模型、可靠性策略 | 技術參考（Layer 1-4 已實作） |
| `docs/EXPERIMENT_REPORT.md` | REV-01/02、KRB 效果的數據記錄範本 | 待填寫 |
| `CHANGELOG.md` | 各版本變更歷史 | 主動維護 |
| `tests/TEST_PLAN.md` | 測試套件全覽與真實數據量測計劃 | 需更新至 v0.34 |
| `COMMANDS.md` | CLI 命令使用者參考 | 主動維護 |
| `docs/archive/` | 過時文件歸檔 | 唯讀 |

---

## 2. 系統現況快照

### 2.1 版本與測試狀態

| 指標 | 數值 |
|------|------|
| 版本 | v0.34.0 |
| Unit tests | 684 passed（含 chaos/benchmark marker 測試） |
| 測試覆蓋率 | ≥ 50%（`fail_under = 50` in pyproject.toml） |
| 基準 recall@3 | ≥ 60%（baseline.json） |
| 基準 avg 查詢延遲 | ≤ 500ms |

### 2.2 模組完成度

```
project_brain/
├── core/
│   ├── brain_db.py          [STABLE] _execute_write 統一入口，WAL+lock
│   ├── session_store.py     [STABLE] TTL + cleanup daemon
│   └── constants.py         [STABLE] sys.modules 別名，monkey-patch 安全
│
├── pipeline/
│   ├── signal.py            [STABLE] Layer 1+2：Signal/SignalKind/SignalQueue
│   ├── executor.py          [STABLE] Layer 4：KnowledgeExecutor（確定性寫入）
│   ├── llm_judgment.py      [STABLE] Layer 3：LLMJudgmentEngine（Ollama+fallback）
│   └── worker.py            [STABLE] Layer 3.5：PipelineWorker daemon
│
├── engines/
│   ├── context.py           [STABLE] ContextEngineer，向量搜尋 + synonym 展開
│   ├── nudge_engine.py      [STABLE] effective_confidence 排序，零 LLM 費用
│   ├── decay_engine.py      [STABLE] F1-F7 多因子衰減，BUG-B02 已修
│   ├── review_board.py      [STABLE] KRB staging + cleanup_expired_staging
│   ├── memory_synthesizer.py [STABLE] L2 合成
│   ├── conflict_resolver.py  [STABLE]
│   └── knowledge_validator.py [STABLE]
│
├── interfaces/
│   ├── mcp_server.py        [STABLE] 22 MCP tools，_validate_workdir 全覆蓋
│   ├── api_server.py        [STABLE]
│   ├── cli*.py              [STABLE]
│   └── web_ui/              [PARTIAL] 零測試覆蓋（ARCH-05）
│
└── integrations/
    ├── federation.py        [TESTED] 75 tests（PII/dedup/subscription）
    └── graphiti_adapter.py  [STABLE]
```

### 2.3 已知未完成項目（各 Phase 詳述）

| Phase | 版本目標 | 未完成項目數 | 核心目標 |
|-------|----------|-------------|---------|
| Phase A | v0.31~v0.34 | 0 | 止血 + 架構深化 ✅ 完成 |
| Phase B | v0.35 | 0 | 可觀測性、資料同步、維護性 ✅ 完成 |
| Phase C | v0.40 | 0 | 架構統一、LLM 介面、Pipeline 擴展 ✅ 完成 |
| Phase D | v1.0 | 5 | 生產就緒、LoRA 蒸餾、CI 全覆蓋 |

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
> **總估計工作量**：~20h（Haiku 4h / Sonnet 12h / Opus 0h）

### B-01 KRB Cleanup Daemon 整合 [DONE v0.35.0]

**ID**：來自 MEDIUM-04「待做」項目
**優先**：P2 — 搭配既有 decay daemon，低成本完成 MEDIUM-04 後半

#### 設計

`cleanup_expired_staging()` 已實作（A-10），只需要在 decay daemon 啟動流程中呼叫一次。

目標：每次 decay daemon 觸發（預設每 24h）順帶清理 KRB staging。

#### 實作步驟

1. **讀取** `project_brain/engines/decay_engine.py`，找到 daemon loop 位置
2. **確認** `KnowledgeReviewBoard` import 方式（避免循環依賴）
3. **在 decay daemon loop 末尾** 呼叫 `krb.cleanup_expired_staging()`，結果記入 structured log
4. **若 decay daemon 不存在統一入口**：在 `mcp_server.py` 啟動流程加入定時任務（仿 `_start_cleanup_daemon`）

#### 測試計劃

```python
# tests/unit/test_krb_daemon_integration.py
class TestCleanupDaemonIntegration:
    def test_cleanup_called_during_decay_cycle(self, monkeypatch):
        """decay daemon 執行一輪後，cleanup_expired_staging 被呼叫"""
    def test_cleanup_error_does_not_stop_decay(self):
        """cleanup 拋出例外時，decay daemon 繼續運作（容錯）"""
    def test_cleanup_log_entry_on_success(self, caplog):
        """成功清理後有 structured log（含 pending_skipped, rejected_archived 計數）"""
```

#### 驗收條件

- [x] decay daemon 每輪執行後，過期 staging 被自動清理
- [x] cleanup 失敗不中斷 decay（有 try/except + log）
- [x] `pytest tests/unit/test_krb_daemon_integration.py` 全通過（16/16）

**推薦模型**：Haiku 4.5（單檔小改 + 3 個測試）
**估計工作量**：1h

---

### B-02 MEDIUM-02：KG/BrainDB 事件驅動同步 [DONE v0.35.0]

**ID**：MEDIUM-02
**優先**：P1（Phase B 最重要項目）— 解決雙 DB 不一致根因

#### 設計

選擇**方案 C：事件驅動同步**（最小侵入，4h）。

```
graph.add_node()  ──emit NodeAdded──▶  BrainDB.on_node_added()
graph.update_node() ─emit NodeUpdated─▶ BrainDB.on_node_updated()
```

架構決策：
- `graph.py` 維持不依賴 `BrainDB`（避免循環依賴）
- 改用 Observer pattern：`KnowledgeGraph._listeners: list[Callable]`
- `ProjectBrain.__init__` 負責連線：`graph.add_listener(brain_db.sync_node)`
- **同步語意**：listener 在同一 call stack 內執行（非異步），保持 ACID 屬性
- **失敗策略**：listener 拋出例外時，graph 寫入仍成功，但記 `WARNING` 讓 `brain health` 偵測

#### 實作步驟

1. **`project_brain/graph.py`**：
   - 新增 `_listeners: list[Callable[[str, dict], None]] = []`（事件 payload 為 node dict）
   - 新增 `add_listener(fn)` / `remove_listener(fn)` 方法
   - 在 `add_node()` 和 `update_node()` 成功寫入後呼叫 `self._emit("node_upserted", node_data)`
   - `_emit()` 迭代 listeners，每個 try/except，失敗 `logger.warning`

2. **`project_brain/core/brain_db.py`**：
   - 新增 `sync_from_graph_node(event: str, data: dict)` 方法
   - event = `"node_upserted"` → 呼叫既有 `add_node()`（upsert 語意）

3. **`project_brain/engine.py`**（ProjectBrain 主入口）：
   - `__init__` 中：`self.graph.add_listener(self._db.sync_from_graph_node)`

4. **`review_board.py`**：
   - 確認 `approve()` 中的 KG 寫入會觸發 listener → BrainDB 同步自動發生
   - 移除原有的手動 `bdb.add_node()` 呼叫（改由事件觸發）

#### 測試計劃

```python
# tests/unit/test_kg_braindb_sync.py
class TestEventSync:
    def test_add_node_syncs_to_braindb(self):
        """graph.add_node() 後，brain_db.search_nodes(title) 能找到"""
    def test_update_node_syncs_to_braindb(self):
        """graph.update_node() 後，brain_db 中的內容同步更新"""
    def test_listener_failure_does_not_rollback_graph(self):
        """listener 拋出例外時，graph 寫入成功，有 WARNING log"""
    def test_add_remove_listener(self):
        """add_listener / remove_listener 正確管理 listener list"""
    def test_multiple_listeners(self):
        """多個 listener 都被呼叫，其中一個失敗不影響其他"""
    def test_approve_triggers_sync(self, tmp_path):
        """review_board.approve() 後，search_nodes 能找到該節點"""
    def test_no_duplicate_sync_on_double_approve(self, tmp_path):
        """同一節點 approve 兩次，brain_db 中只有一份（upsert 冪等）"""

class TestSyncConsistency:
    def test_50_concurrent_adds_all_synced(self):
        """50 threads 並發 add_node，brain_db 最終節點數一致"""
```

#### 驗收條件

- [ ] `graph.add_node()` 後 `brain_db.search_nodes()` 能找到節點（不需手動同步）
- [ ] `review_board.approve()` 移除手動 BrainDB 寫入，改由事件觸發
- [ ] listener 失敗不中斷 graph 寫入
- [ ] 50 threads 並發測試通過

**推薦模型**：Sonnet 4.6（事務邊界 + Observer 設計，需確認循環依賴）
**估計工作量**：4h

---

### B-03 `brain health` 診斷命令 [DONE v0.35.0]

**ID**：新功能（§8.4 列出）
**優先**：P2（依賴 B-02 讓 health check 有意義）
**依賴**：B-02 完成後 KG/BrainDB 差異可被可靠偵測

#### 設計

```bash
$ brain health
Project Brain Health Check — v0.35.0
======================================
[OK]  brain.db          accessible (684 nodes, 231 edges)
[OK]  knowledge_graph.db accessible (231 nodes)
[WARN] KG/BrainDB sync   12 nodes in KG not found in brain.db FTS5
[OK]  KRB staging        3 pending, 0 stale (oldest: 2d)
[OK]  Pipeline worker    running (last processed: 4m ago)
[OK]  Decay daemon       running (last run: 6h ago)
[OK]  Signal queue       12 pending signals
[WARN] Benchmark         last run: 14d ago (recommend: re-run update_baseline.py)
======================================
Overall: WARN (1 warning, 0 errors)
```

#### 實作步驟

1. **`project_brain/interfaces/cli_admin.py`**（或新的 `cli_health.py`）：
   - 新增 `health` subcommand
   - 實作各項檢查函式（每個 try/except，失敗顯示 ERROR）

2. **檢查項目清單**：
   - DB 連線與基本節點數（BrainDB + KnowledgeGraph）
   - KG/BrainDB 節點數差異（B-02 完成後準確）
   - KRB staging 狀態（pending 數、最舊 pending 日期）
   - Pipeline worker 存活（讀 `pipeline_metrics` 最後一筆記錄）
   - Decay daemon 最後執行時間
   - Signal queue pending 數
   - baseline.json 最後更新距今天數

3. **輸出格式**：
   - 結構化（支援 `--json` flag 輸出 JSON）
   - 顏色（OK=green、WARN=yellow、ERROR=red，支援 `--no-color`）

4. **MCP tool**（選擇性）：新增 `brain_status` 增強版，回傳 health JSON

#### 測試計劃

```python
# tests/unit/test_cli_health.py
class TestHealthCommand:
    def test_all_ok_fresh_db(self, tmp_path):
        """新初始化的 DB，health 全綠"""
    def test_warn_kg_braindb_mismatch(self, tmp_path):
        """手動在 KG 加入節點但不同步 BrainDB，health 顯示 WARN"""
    def test_warn_stale_staging(self, tmp_path):
        """插入 35 天前的 pending staging，health 顯示 WARN"""
    def test_json_output_schema(self, tmp_path):
        """--json 輸出可被 json.loads 解析，包含必要欄位"""
    def test_db_not_found_shows_error(self, tmp_path):
        """brain.db 不存在時顯示 ERROR，不 crash"""
```

#### 驗收條件

- [x] `brain health` 命令可執行，輸出各項狀態
- [x] KG/BrainDB 不一致時顯示 WARN（依賴 B-02）
- [x] `--json` 輸出格式穩定（供 CI 解析）
- [x] DB 不存在時優雅降級（不 crash）
- [x] `pytest tests/unit/test_health.py` 全通過（21/21）

**推薦模型**：Sonnet 4.6（跨多模組資訊收集 + CLI 設計）
**估計工作量**：3h

---

### B-04 Pipeline Metrics Dashboard [DONE v0.35.0]

**ID**：新功能（§8.4 列出）
**優先**：P2
**依賴**：`pipeline_metrics` 表已存在（brain.db 中）

#### 設計

目標：讓 `brain stats` 或新的 `brain pipeline-stats` 輸出 pipeline 運行統計，同時支援 Grafana 可讀的 Prometheus text format。

```bash
$ brain pipeline-stats
Pipeline Statistics (last 7 days)
==================================
Signals received:    142
Signals processed:    98 (69%)
  - Added to L3:      31 (32%)
  - Skipped:          67 (68%)
  - Failed:            0
Avg processing time: 2.3s
Worker uptime:       99.2%
Queue depth (now):   12

$ brain pipeline-stats --prometheus
# HELP brain_signals_total Total signals received
# TYPE brain_signals_total counter
brain_signals_total{status="received"} 142
brain_signals_total{status="processed"} 98
...
```

#### 實作步驟

1. **確認** `pipeline_metrics` 表 schema（讀 brain_db.py）
2. **新增** `BrainDB.get_pipeline_stats(days=7) → dict` 聚合查詢
3. **新增** `brain pipeline-stats [--prometheus] [--days N]` CLI subcommand
4. **Prometheus exporter**：`brain serve --metrics` 在 `/metrics` 端點輸出 text format（可選，僅在 `gunicorn` extra 安裝時啟用）

#### 測試計劃

```python
# tests/unit/test_pipeline_stats.py
class TestPipelineStats:
    def test_empty_db_returns_zero_stats(self, tmp_path): ...
    def test_stats_aggregate_by_status(self, tmp_path): ...
    def test_days_filter_works(self, tmp_path): ...
    def test_prometheus_format_parseable(self, tmp_path): ...
```

#### 驗收條件

- [x] `brain pipeline-stats` 輸出人可讀統計
- [x] `--prometheus` 輸出可被 Prometheus text format 解析器讀取
- [x] `--json` 輸出 JSON 格式
- [x] 空 DB 不 crash（回傳全 0）
- [x] `pytest tests/unit/test_pipeline_stats.py` 全通過（19/19）

**推薦模型**：Sonnet 4.6（跨 CLI + DB 聚合查詢）
**估計工作量**：3h

---

### B-05 MEDIUM-03：MCP Server Singleton 重構 [DONE v0.35.0]

**ID**：MEDIUM-03
**優先**：P2（測試穩定性，pytest-xdist 並行時狀態污染風險）
**依賴**：無（獨立重構）

#### 設計

**問題根源**：`mcp_server.py` 頂層有 7 個 module-level 可變狀態變數：

```python
_call_times: list[float] = []
_rate_lock = threading.Lock()
_session_nodes: dict[str, list[str]] = {}
_snodes_lock = threading.Lock()
_session_served: dict[str, set[str]] = {}
_cleanup_daemon_started = False
_decay_daemon_started = False
```

同程序多個 Brain 實例（或 pytest 並行）共享這些狀態。

**修法**：封裝進 `class BrainServer`，`create_server()` 工廠回傳實例。

```python
class BrainServer:
    def __init__(self, brain_dir: Path, config: BrainConfig):
        self._call_times: list[float] = []
        self._rate_lock = threading.Lock()
        self._session_nodes: dict[str, list[str]] = {}
        # ...
        self._cleanup_started = False
        self._decay_started = False

    def create_mcp_server(self) -> Server:
        """原 create_server() 的邏輯移入此方法"""
        ...
```

#### 實作步驟

1. **讀取** `project_brain/interfaces/mcp_server.py` 全文
2. **建立** `class BrainServer` 包含所有 module-level state
3. **將所有 helper 函式**（`_rate_check`, `_track_session_node` 等）改為 `BrainServer` 的方法（或 closure）
4. **保留** `create_server(brain_dir, config) → Server` 為公開工廠函式（現有呼叫方不需改動）：
   ```python
   def create_server(brain_dir, config=None):
       srv = BrainServer(brain_dir, config)
       return srv.create_mcp_server()
   ```
5. **確認** `mcp_server.create_server()` 的呼叫方（`engine.py`、CLI）無需修改

#### 測試計劃

```python
# tests/unit/test_mcp_server_isolation.py
class TestServerIsolation:
    def test_two_servers_have_independent_rate_state(self, tmp_path):
        """兩個 create_server() 實例的 rate limit 互不干擾"""
    def test_two_servers_have_independent_session_state(self, tmp_path):
        """兩個實例的 session_nodes 不共享"""
    def test_daemon_flags_per_instance(self, tmp_path):
        """每個實例有獨立的 daemon started flag"""

# tests/unit/test_mcp_server_regression.py — 確保既有行為不退化
class TestExistingBehaviorUnchanged:
    def test_rate_limit_still_enforced(self, tmp_path): ...
    def test_session_tracking_still_works(self, tmp_path): ...
```

#### 驗收條件

- [x] `create_server()` 公開 API 不變（無 breaking change）
- [x] 兩個 `create_server()` 實例的狀態互相隔離
- [x] 現有所有 MCP server 測試通過（零 regression）

**推薦模型**：Sonnet 4.6（跨檔重構，需確保所有呼叫方正確）
**估計工作量**：6h

---

### B-06 MEDIUM-06：`_count_tokens` 停用 LRU cache [DONE v0.35.0]

**ID**：MEDIUM-06
**優先**：P3（性能優化）
**依賴**：無

#### 設計

**問題**：`@functools.lru_cache(maxsize=1024)` 對 5000+ 節點的知識庫命中率 < 20%，持續驅逐 + 重算浪費 CPU。

**修法（方案 B）**：移除 cache decorator，改為確定性 O(n) 估算：

```python
def _count_tokens(text: str) -> int:
    """確定性 token 估算，無 cache 管理成本。

    中文字元：約 1 token / char
    ASCII 字元：約 1 token / 4 chars
    混合文字：分段計算
    """
    if not text:
        return 0
    cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff'
              or '\u3400' <= c <= '\u4dbf'
              or '\uf900' <= c <= '\ufaff')
    ascii_like = len(text) - cjk
    return cjk + max(1, ascii_like // 4)
```

#### 測試計劃

```python
# tests/unit/test_token_count.py（更新既有測試）
class TestCountTokens:
    def test_empty_string(self): assert _count_tokens("") == 0
    def test_pure_cjk(self): assert _count_tokens("你好世界") == 4
    def test_pure_ascii(self): assert _count_tokens("hello world") == 3  # 11/4 ≈ 3
    def test_mixed(self): ...
    def test_deterministic(self):
        """相同輸入永遠相同輸出（不依賴快取狀態）"""
        assert _count_tokens("abc") == _count_tokens("abc")
    def test_no_lru_cache_attribute(self):
        """確認 cache_info() 不存在（已移除 decorator）"""
        assert not hasattr(_count_tokens, 'cache_info')
```

#### 驗收條件

- [x] `_count_tokens` 無 `@lru_cache` decorator
- [x] 結果與舊實作誤差 < 20%（token 估算允許誤差）
- [x] `context.py` 相關測試全通過

**推薦模型**：Haiku 4.5（單函式改寫，< 20 行）
**估計工作量**：1h

---

### B-07 LOW-01~04：錯誤處理批次修復 [DONE v0.35.0]

**ID**：LOW-01, LOW-02, LOW-03, LOW-04
**優先**：P3（可維護性）
**依賴**：無（可一次批次完成）

#### 各項說明

**LOW-01**：`context.py:92` — `except Exception: pass` 吞掉 config.json 讀取失敗，無任何日誌
```python
# 修法：改為 logger.warning("failed to load config: %s", e)
```

**LOW-02**：`brain_db.py:68` — `except OSError: pass`（備份清理靜默）
```python
# 修法：改為 logger.debug("backup cleanup failed (non-critical): %s", e)
```

**LOW-03**：`brain_db.py:93` — `close()` 無 idempotent 保護，重複呼叫可能出錯
```python
# 修法：
def close(self):
    if self._conn is None:
        return
    self._conn.close()
    self._conn = None
```

**LOW-04**：`federation.py:63-71` — `_strip_pii` 未處理 UUID、序列號、token 格式
```python
# 修法：新增 UUID pattern (8-4-4-4-12) + 常見 token 格式 regex
_PII_UUID = re.compile(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', re.I)
_PII_TOKEN = re.compile(r'\b(sk-|ghp_|xoxb-)[A-Za-z0-9_-]{16,}\b')
```

#### 測試計劃

```python
# tests/unit/test_low_fixes.py
class TestLow01ContextConfigLog:
    def test_invalid_config_logs_warning(self, caplog, tmp_path): ...

class TestLow02BackupCleanupLog:
    def test_cleanup_oserror_logs_debug(self, caplog, tmp_path): ...

class TestLow03CloseIdempotent:
    def test_double_close_no_exception(self, tmp_path): ...
    def test_close_sets_conn_none(self, tmp_path): ...

class TestLow04PiiUUID:
    def test_uuid_stripped(self): ...
    def test_github_token_stripped(self): ...
    def test_slack_token_stripped(self): ...
    def test_normal_hyphenated_word_not_stripped(self): ...
```

#### 驗收條件

- [x] LOW-01~03：相關位置無靜默 `pass`
- [x] LOW-04：UUID 和常見 token 格式被 `_strip_pii` 清理
- [x] 所有現有 federation 測試通過（75 tests 不退化）

**推薦模型**：Haiku 4.5（LOW-01~03）；Sonnet 4.6（LOW-04，PII 邊界需思考）
**估計工作量**：3h

---

### Phase B 完成驗收

```bash
# Phase B 完成後，全量測試基準
python -m pytest tests/ -q 2>&1 | tail -3
# 目標：≥ 730 passed（現 684 + ~46 新測試），0 regression

python -m pytest tests/ -m benchmark -q
# 目標：4 tests passed（召回率/延遲回歸門檻）

brain health
# 目標：all [OK]（新安裝環境）
```

---

## 5. Phase C — 架構演進 [DONE v0.40.0]

> **前提依賴**：Phase B 全部完成，系統可觀測性建立後再動架構
>
> **核心目標**：統一資料層、統一 LLM 介面、擴展 Pipeline 信號類型
>
> **總估計工作量**：~60h（Haiku 0h / Sonnet 16h / Opus 44h）

### C-01 ARCH-01：統一 DB（knowledge_graph.db 合併進 brain.db）[DONE v0.40.0]

**ID**：ARCH-01
**優先**：P3（架構債，但 B-02 事件同步先緩解症狀）
**依賴**：B-02 完成（事件同步讓遷移更安全）；Schema v27 migration

#### 設計

**目標**：消除雙 DB 架構，讓所有資料在單一 `brain.db` 的單一事務內完成。

```
v0.34 (two DBs)              v0.40 (single DB)
──────────────────           ──────────────────────────
brain.db                     brain.db
  nodes (FTS5 mirror)          nodes (唯一真相源)
  edges                        nodes_fts (FTS5 virtual)
  ...                          edges
knowledge_graph.db             temporal_edges
  nodes (真相源)               episodes
  edges (duplicate)            sessions
  temporal_edges               node_vectors
                               staged_nodes (從 KRB 遷入)
                               signal_queue
                               pipeline_metrics
                               node_history
```

#### Schema v31 遷移策略

```python
def migrate_v30_to_v31(brain_dir: Path) -> MigrationResult:
    """
    遷移步驟（全部在 transaction 內）：
    1. brain.db 建立 temporal_edges 表（從 KG schema）
    2. brain.db 建立 node_history 表（從 KG）
    3. 從 knowledge_graph.db 讀取所有 nodes，upsert 進 brain.db
       （以 brain.db 版本為主，KG 只補 version/created_at）
    4. 從 KG 複製 edges（INSERT OR IGNORE）
    5. 從 KG 複製 temporal_edges
    6. 驗證：brain.db node 數 >= KG node 數
    7. 備份 KG：knowledge_graph.db → knowledge_graph.db.bak.YYYYMMDD
    8. 更新 brain_meta.schema_version = 31
    """
```

#### 實作步驟

1. **設計** `BrainDB` v31 schema（新增 temporal_edges、node_history 表）
2. **實作** `migrate_v30_to_v31()` 遷移腳本（含乾跑模式 `--dry-run`）
3. **重構** `KnowledgeGraph`：改為使用 `brain.db` 而非獨立檔案（接受 `BrainDB` 實例）
4. **更新** `ProjectBrain.__init__`：移除 KG DB 初始化，改從 `BrainDB` 建立 KG view
5. **更新** `review_board.approve()`：移除 BrainDB 手動同步（B-02 的事件機制 + 統一 DB 讓這不再需要）
6. **`brain init`** 自動觸發遷移（偵測到 `knowledge_graph.db` 存在時）

#### 測試計劃

```python
# tests/unit/test_db_migration_v31.py
class TestMigrationV31:
    def test_dry_run_reports_counts(self, tmp_path): ...
    def test_migration_preserves_all_nodes(self, tmp_path): ...
    def test_migration_preserves_edges(self, tmp_path): ...
    def test_migration_idempotent(self, tmp_path):
        """二次遷移不重複資料，無錯誤"""
    def test_migration_creates_backup(self, tmp_path): ...
    def test_rollback_on_failure(self, tmp_path):
        """遷移中途失敗，brain.db 回到原狀態"""

# tests/unit/test_kg_on_unified_db.py — 確認 KG 功能在 brain.db 上正常
class TestKGOnUnifiedDB:
    def test_add_node_searchable_via_fts5(self, tmp_path): ...
    def test_cas_still_works(self, tmp_path): ...
    def test_temporal_edges_queryable(self, tmp_path): ...
```

#### 驗收條件

- [x] 遷移後 `knowledge_graph.db` 不再被建立
- [x] 所有既有 KG 測試通過（無 regression）
- [x] `brain health` 顯示單 DB 模式
- [x] 50 threads 並發測試在統一 DB 上通過

**推薦模型**：Opus 4.6 (1M)（Schema 遷移 + 全檔掃描，架構級設計）
**估計工作量**：24h

---

### C-02 integrations/llm_client.py — 統一 LLM 介面 [DONE v0.40.0]

**ID**：新功能（§6.2 延後項目）
**優先**：P3（為 C-03、C-04 提供乾淨基礎）
**依賴**：無（新建）

#### 設計

目前 LLM 呼叫散落在多個模組，各自實作重試、fallback、timeout：

| 模組 | LLM 呼叫方式 |
|------|-------------|
| `pipeline/llm_judgment.py` | `OllamaClient` + Anthropic fallback |
| `engines/memory_synthesizer.py` | 獨立呼叫 |
| `engines/conflict_resolver.py` | 獨立呼叫 |
| `engines/knowledge_validator.py` | 獨立呼叫 |
| `engines/review_board.py` (KRBAIAssistant) | `OllamaClient` |

**目標**：建立 `integrations/llm_client.py` 統一介面：

```python
class LLMClient(Protocol):
    """統一 LLM 呼叫介面（Protocol，不強制繼承）"""
    def complete(self, prompt: str, *, timeout: int = 30,
                 max_retries: int = 2, temperature: float = 0.1) -> str: ...

class OllamaLLMClient:
    """本地 Ollama 實作"""
    ...

class AnthropicLLMClient:
    """Anthropic API 實作"""
    ...

class FallbackLLMClient:
    """優先使用 primary，失敗時 fallback"""
    def __init__(self, primary: LLMClient, fallback: LLMClient): ...

def from_brain_config(section: str, brain_dir: Path) -> LLMClient:
    """從 brain.toml 建立對應實作（工廠函式）"""
    ...
```

#### 實作步驟

1. **讀取** 現有 OllamaClient 實作（`llm_judgment.py` 中）
2. **建立** `integrations/llm_client.py`，提取共用邏輯
3. **漸進遷移**：先讓 `llm_judgment.py` 使用新介面，其他模組後續遷移
4. **compat shim**：原 `OllamaClient` 保留為 `LLMClient` 的別名

#### 測試計劃

```python
# tests/unit/test_llm_client.py
class TestFallbackClient:
    def test_uses_primary_when_available(self): ...
    def test_falls_back_on_primary_failure(self): ...
    def test_raises_when_both_fail(self): ...

class TestFromBrainConfig:
    def test_ollama_section_creates_ollama_client(self, tmp_path): ...
    def test_missing_section_returns_noop_client(self, tmp_path): ...
```

#### 驗收條件

- [x] `from_brain_config` 工廠可替換現有各模組的 OllamaClient 建構方式
- [x] 現有 LLM judgment 測試通過（零 regression）

**推薦模型**：Opus 4.6 (1M)（跨多模組重構，需理解所有呼叫方）
**估計工作量**：8h

---

### C-03 ARCH-02：KnowledgeValidator CI 集成 [DONE v0.40.0]

**ID**：ARCH-02
**優先**：P3
**依賴**：C-02（使用統一 LLM 介面）

#### 設計

`KnowledgeValidator` 三階段（Rule 驗證 → 統計分析 → LLM 抽樣）已實作，但：
1. 沒有 CI 觸發機制（只能手動呼叫）
2. LLM 抽樣階段在 CI 環境中 Ollama 不可用時會 skip，無 fallback 報告

**目標**：
- `brain validate [--ci]` 命令，可在 CI pipeline 呼叫
- `--ci` 模式：LLM 不可用時，只跑 Rule + 統計兩階段，輸出 JSON report
- 新增 `tests/integration/test_knowledge_validator_ci.py`（不需 LLM）

#### 實作步驟

1. 新增 `brain validate --ci --output report.json` CLI flag
2. CI-safe 模式跳過 LLM 抽樣，輸出 `{"passed": bool, "rule_violations": [...], "stats": {...}}`
3. 整合測試：模擬 200 個節點，驗證三階段各自可獨立跑

#### 驗收條件

- [x] `brain validate --ci` 在無 Ollama 環境執行不 crash
- [x] JSON report 可被 CI 解析（exit code 1 if `passed: false`）

**推薦模型**：Sonnet 4.6
**估計工作量**：6h

---

### C-04 ARCH-04：Pipeline Phase 2 — 新增 MCP_TOOL_CALL / TEST_FAILURE 信號 [DONE v0.40.0]

**ID**：ARCH-04
**優先**：P3
**依賴**：C-02（統一 LLM 介面），Layer 1-4 穩定（Phase A）

#### 設計

目前 Pipeline 只捕捉 `GIT_COMMIT`、`KNOWLEDGE_GAP` 信號。Phase 2 新增：

| 信號類型 | 觸發時機 | 知識提取目標 |
|---------|---------|------------|
| `MCP_TOOL_CALL` | 每次 MCP tool 被呼叫（add_knowledge / answer_question / get_context） | 學習使用模式 |
| `TEST_FAILURE` | `complete_task` 中的 lessons 含 "test failed" / "error" | 記錄測試失敗模式 |
| `KNOWLEDGE_CONFLICT` | `find_conflicts()` 發現新衝突 | 主動偵測矛盾 |

#### Prompt 設計（LLM 判斷引擎）

```python
# MCP_TOOL_CALL 信號的 prompt template
MCP_TOOL_CALL_PROMPT = """
你是知識提取助手。以下是一個 MCP tool 呼叫記錄。

工具：{tool_name}
參數摘要：{params_summary}
結果摘要：{result_summary}

請判斷：這個呼叫是否暗示了一個可記錄的知識？
- 若是 add_knowledge 且 kind=Pitfall → 高價值，action=add, confidence=0.8
- 若是重複的 get_context → action=skip
- 其他 → 根據內容判斷

輸出格式（JSON）：
{"action": "add|skip", "reason": "...", "title": "...", "content": "...", "kind": "Pitfall|Rule|Decision|Note", "confidence": 0.0-1.0}
"""
```

#### 實作步驟

1. **`pipeline/signal.py`**：新增 `SignalKind.MCP_TOOL_CALL`、`TEST_FAILURE`、`KNOWLEDGE_CONFLICT`
2. **`interfaces/mcp_server.py`**：在各 tool handler 末尾 emit MCP_TOOL_CALL 信號（非同步，不影響 tool 回應）
3. **`pipeline/llm_judgment.py`**：新增各信號類型的 prompt template + `analyze()` dispatch
4. **`pipeline/worker.py`**：新增信號類型的批次優先度（TEST_FAILURE > MCP_TOOL_CALL）

#### 測試計劃

```python
# tests/unit/test_pipeline_phase2_signals.py
class TestMCPToolCallSignal:
    def test_add_knowledge_emits_signal(self, ...): ...
    def test_get_context_signal_analyzed_as_skip(self, ...): ...

class TestTestFailureSignal:
    def test_complete_task_with_error_lesson_emits_signal(self, ...): ...
    def test_signal_extracted_as_pitfall(self, ...): ...

class TestKnowledgeConflictSignal:
    def test_find_conflicts_result_emits_signal(self, ...): ...
```

#### 驗收條件

- [x] 3 個新 SignalKind 定義完整，向後相容
- [x] `add_knowledge` MCP tool 呼叫後 signal_queue 有對應記錄
- [x] LLM 不可用時信號進 queue 但不 crash（非同步）

**推薦模型**：Opus 4.6 (1M)（Signal schema + prompt 設計，需長 context 理解 pipeline 全貌）
**估計工作量**：16h

---

### C-05 Pipeline Layer 5 — Feedback Loop [DONE v0.40.0]

**ID**：§7.1 功能強化
**優先**：P3
**依賴**：C-04（需要足夠的信號數據）

#### 設計

每次 `report_knowledge_outcome(node_id, was_useful)` 後，統計特定信號類型的有用率：

```python
# 週期性計算（可在 decay daemon 中觸發）
def _adjust_signal_confidence(signal_kind: str) -> None:
    """若某信號類型 30 天內負面回饋 > 30%，降低 auto_confidence"""
    negative_rate = feedback_tracker.get_negative_rate(signal_kind, days=30)
    if negative_rate > 0.30:
        # 降低此類型信號的預設 confidence（寫入 brain.toml 或 brain_meta）
        new_confidence = max(0.3, current - 0.1)
        brain_config.set_signal_confidence(signal_kind, new_confidence)
```

#### 驗收條件

- [x] `report_knowledge_outcome` 記錄寫入 `feedback_log` 表（含信號類型）
- [x] 週期統計在 decay daemon 中觸發
- [x] 30% 負面回饋觸發 auto_confidence 下調（有測試覆蓋）

**推薦模型**：Opus 4.6 (1M)（跨層設計，需理解 feedback_tracker + pipeline + config 三塊）
**估計工作量**：12h

---

### Phase C 完成驗收

```bash
# 單一 DB 驗證
ls .brain/*.db
# 預期只有：brain.db（knowledge_graph.db 已合併或備份）

brain health
# 預期：[OK] Database: single DB mode (brain.db)

python -m pytest tests/ -q | tail -3
# 目標：≥ 800 passed，0 regression
```

---

## 6. Phase D — 生產就緒 [目標 v1.0]

> **前提依賴**：Phase C 全部完成
>
> **核心目標**：研究級功能（LoRA 蒸餾）、WebUI 完整化、CI 全覆蓋、生產驗證
>
> **總估計工作量**：~90h（主要為研究 + 測試工作）

### D-01 ARCH-03：KnowledgeDistiller Layer 3 LoRA

**ID**：ARCH-03
**優先**：P4（需要 GPU 環境）
**依賴**：C-02（統一 LLM 介面），需本地 GPU（≥ 16GB VRAM）

#### 設計

**目標**：將 Brain 知識庫蒸餾成 LoRA adapter，使小型模型（7B）能直接回答專案問題，無需每次做 RAG。

```
知識庫 ──[KnowledgeDistiller]──▶ 訓練資料集（Q&A pairs）
                                     │
                                     ▼
                               [LoRA 訓練]（本地 GPU）
                                     │
                                     ▼
                               brain.lora.adapter
                                     │
                        ┌────────────┘
                        ▼
                  Ollama 載入 adapter → 回答專案問題
```

#### 實作步驟（高層次）

1. **資料集生成**：`KnowledgeDistiller.generate_dataset()` — 從 L3 節點生成 Q&A pairs
2. **訓練腳本**：`scripts/train_lora.py`（使用 unsloth / axolotl）
3. **評估**：與 RAG 基線對比（recall@3 / answer accuracy）
4. **推論整合**：`brain.toml [distiller.adapter_path]` 指定 adapter，優先於 RAG

**注意**：此項目研究性強，工期難以精確估算，建議先完成 Phase A~C 積累足夠數據後再啟動。

**推薦模型**：Opus 4.6 (1M)（ML 研究級設計）
**估計工作量**：40h+（含 GPU 訓練時間）

---

### D-02 ARCH-05：WebUI 行內編輯

**ID**：ARCH-05
**優先**：P4
**依賴**：C-01（統一 DB 讓前端 API 更穩定）

#### 設計

目前 WebUI 只有讀取功能（`web_ui/`，零測試）。目標新增：
- 節點行內編輯（title / content / confidence）
- KRB staging 管理界面（approve / reject / needs_changes）
- 搜尋 + 過濾

**推薦模型**：Sonnet 4.6（前端 + API 整合）
**估計工作量**：16h

---

### D-03 完整 CI 集成

**優先**：P4
**依賴**：Phase B 完成（有 `brain health --json` 和 prometheus metrics）

#### CI Pipeline 設計

```yaml
# .github/workflows/ci.yml（目標）
jobs:
  unit:
    - pytest tests/unit/ -q
    - pytest tests/unit/ -m benchmark -q  # baseline regression

  integration:
    - pytest tests/integration/ -q

  health:
    - brain health --json | jq '.overall == "OK"'

  coverage:
    - pytest --cov=project_brain --cov-fail-under=60
```

#### 驗收條件

- [ ] 所有 CI 步驟在 GitHub Actions 上通過
- [ ] `pytest -m benchmark` 在 CI 環境以 `skip`（無 embedder）優雅處理
- [ ] 覆蓋率達 60%（從現有 50% 提升）

---

### D-04 生產驗證

**優先**：P4
**包含**：

1. **Federation 生產驗證**：在至少 2 個真實專案之間做跨知識庫同步，驗證 PII 清理完整性
2. **E2E 整合測試**：git commit → signal → LLM 判斷 → L3 寫入（需真實 Ollama 環境）
3. **效能基準更新**：5000 節點知識庫下的 recall@3 / avg latency 驗證

---

### D-05 文件完整化

**優先**：P4

| 文件 | 目標狀態 |
|------|---------|
| `COMMANDS.md` | 更新至 v1.0 所有命令（含 `brain health`、`brain pipeline-stats`） |
| `INSTALL.md` | 加入 GPU 環境（LoRA 蒸餾）安裝指引 |
| `tests/TEST_PLAN.md` | 更新至 v1.0 測試套件全覽 |
| `docs/EXPERIMENT_REPORT.md` | 填入 REV-01/02 真實實驗數據 |
| `README.md` | 加入架構圖、核心功能 GIF |

---

## 7. 依賴關係圖

```
Phase A (v0.31~v0.34) — 全部完成
├── A-01 BLOCKER-02 雙 DB 原子化 ─────────────────────────────┐
├── A-02 HIGH-02 假 ERROR log                                  │
├── A-03 HIGH-04 workdir 驗證                                  │
├── A-04 MEDIUM-05 同義詞展開上界                              │
├── A-05 BLOCKER-01 LLMJudgmentEngine                          │
├── A-06 BLOCKER-03 Federation 測試                            │
├── A-07 HIGH-01 CAS 樂觀鎖                                    │
├── A-08 HIGH-03 find_conflicts 優化                           │
├── A-09 MEDIUM-01 _execute_write 統一入口                     │
├── A-10 MEDIUM-04 KRB staging 清理                            │
└── A-11 MEDIUM-07 CI Benchmark Baseline                       │
                                                               │
Phase B (v0.35) — 前提：Phase A 完成                           │
├── B-01 KRB Daemon 整合（依賴 A-10）                          │
├── B-02 KG/BrainDB 事件同步（依賴 A-01 修復原子化）◄─────────┘
│    └──▶ B-03 brain health 命令（依賴 B-02 才有意義）
├── B-04 Pipeline metrics dashboard（依賴 A-05 Worker 運行）
├── B-05 MCP Server singleton（獨立）
├── B-06 _count_tokens 無 cache（獨立）
└── B-07 LOW-01~04 錯誤處理（獨立，可與其他並行）

Phase C (v0.40) — 前提：Phase B 完成（系統可觀測後再動架構）
├── C-01 ARCH-01 統一 DB（依賴 B-02 事件同步為基礎）
├── C-02 LLM Client 統一介面（獨立，但為 C-03/C-04 前置）
│    ├──▶ C-03 ARCH-02 KnowledgeValidator CI（依賴 C-02）
│    └──▶ C-04 ARCH-04 Pipeline Phase 2 信號（依賴 C-02）
│              └──▶ C-05 Layer 5 Feedback Loop（依賴 C-04）

Phase D (v1.0) — 前提：Phase C 完成
├── D-01 ARCH-03 LoRA 蒸餾（依賴 C-02，需 GPU）
├── D-02 ARCH-05 WebUI 行內編輯（依賴 C-01 統一 DB）
├── D-03 CI 全覆蓋（依賴 B-03 health + B-04 metrics）
├── D-04 生產驗證（依賴所有 Phase C）
└── D-05 文件完整化（依賴所有功能完成）
```

---

## 8. 模型選擇速查表

> 開發時用此表快速選擇 Claude 開發模型。詳細判準見 `ARCHITECTURE_REVIEW.md §1.4.1`。

| 任務類型 | 推薦模型 | 理由 |
|---------|---------|------|
| 單行/單函式修補（< 20 行，< 1h） | **Haiku 4.5** | 成本最低，無需長 context |
| 測試編寫、標準功能實作（1-12h，2-4 個檔案） | **Sonnet 4.6** | 品質與成本平衡 |
| 事務/並發/安全邊界修改 | **Sonnet 4.6 最少** | 需要審慎推理 |
| 架構設計、新模組、Schema 遷移、跨 5+ 檔案 | **Opus 4.6 (1M)** | 需長 context + 一次吞下全貌 |
| LLM 研究（LoRA、Prompt 設計） | **Opus 4.6 (1M)** | 研究級複雜度 |

| Phase | 主要模型分佈 |
|-------|------------|
| A（已完成） | Haiku 4h / Sonnet 23h / Opus 12h |
| B | Haiku 4h / Sonnet 12h / Opus 0h |
| C | Haiku 0h / Sonnet 16h / Opus 44h |
| D | 混合（主要 Opus + Sonnet） |

---

## 9. 品質門檻

每個 Phase 完成後必須滿足：

| 指標 | Phase B 目標 | Phase C 目標 | Phase D 目標 |
|------|------------|------------|------------|
| Unit tests passed | ≥ 730 | ≥ 800 | ≥ 900 |
| 覆蓋率 | ≥ 50% | ≥ 55% | ≥ 60% |
| recall@3 | ≥ 60% | ≥ 65% | ≥ 70% |
| avg 查詢延遲 | ≤ 500ms | ≤ 400ms | ≤ 300ms |
| `brain health` 輸出 | 有此命令 | all [OK] | all [OK] |
| Regression | 0 | 0 | 0 |

### 每項任務完成前的標準 checklist

```
[ ] 先讀相關程式碼，理解現有行為
[ ] 寫測試（先 fail）
[ ] 最小改動實作
[ ] pytest tests/ -q — 全量通過，零 regression
[ ] 更新 CHANGELOG.md（版本 + 變更摘要）
[ ] 更新本文件（標記任務為 [DONE vX.Y.Z]）
[ ] brain complete_task（記錄 decisions/lessons/pitfalls）
[ ] 必要時 brain add_knowledge（Pitfall/Decision/Rule）
```

---

## 10. 歸檔文件索引

以下文件已移至 `docs/archive/`，僅供歷史參考：

| 文件 | 歸檔原因 | 替代文件 |
|------|---------|---------|
| `docs/archive/BRAIN_MASTER_v0.2.md` | v0.2.0（2026-04-03），架構已大幅演進 | 本文件 §2 系統現況快照 |
| `docs/archive/COMPLETED_HISTORY_pre_v0.30.md` | 記錄 v0.1.1~v1.0.0（舊版號）的 76 個已完成項目 | `CHANGELOG.md` |
| `docs/archive/IMPROVEMENT_PLAN_v0.30.md` | v0.30.0 改善規劃（2026-04-06），大部分已完成或整合進本文件 | 本文件 Phase B+ |

> **注意**：`docs/AUTO_KNOWLEDGE_PIPELINE.md` 保留為 Pipeline Layer 1-5 的**技術設計參考**（Prompt 設計、資料模型、可靠性策略），不歸檔。Layer 3-4 的實作細節仍有參考價值。
