# Project Brain — 完整測試計劃文件

> **版本**：v0.6.0（2026-04-04）
> **用途**：記錄所有測試項目的計劃、狀態、覆蓋範圍與待執行的真實數據量測需求。

---

## 目錄

1. [測試套件全覽](#1-測試套件全覽)
2. [單元測試（Unit）](#2-單元測試-unit)
3. [整合測試（Integration）](#3-整合測試-integration)
4. [Chaos & 負載測試](#4-chaos--負載測試)
5. [基準測試（Benchmark）](#5-基準測試-benchmark)
6. [待實作項目測試計劃](#6-待實作項目測試計劃)
   - [REF-04 — 魔法數字提取](#ref-04--魔法數字提取-constants)
   - [PERF-03 — Token 計數快取](#perf-03--token-計數快取)
   - [BUG-A03 — 雙重加鎖修復](#bug-a03--雙重加鎖修復)
7. [真實數據量測計劃](#7-真實數據量測計劃)
   - [REV-01 — 量化對照實驗（商業指標）](#rev-01--量化對照實驗商業指標)
   - [FLY-04 — NudgeEngine 命中率](#fly-04--nudgeengine-命中率)
   - [FLY-05 — 知識庫自然成長率](#fly-05--知識庫自然成長率)
   - [REV-02 — 衰減效用量測](#rev-02--衰減效用量測)
   - [四維指標版本週期一致性](#四維指標-版本週期一致性)
8. [品質門檻總表](#8-品質門檻總表)
9. [執行指令速查](#9-執行指令速查)

---

## 1. 測試套件全覽

```
tests/
├── TEST_PLAN.md                     ← 本文件
├── unit/
│   ├── test_core.py                 ← 核心功能（BrainDB、Graph、Router 等）
│   ├── test_session_store.py        ← L1a SessionStore
│   ├── test_arch_decisions_v01.py   ← 架構決策 v0.1.0（WAL、衰減不刪節點）
│   ├── test_arch_decisions_v02.py   ← 架構決策 v0.2.0（BRAIN_WORKDIR 自動偵測、查詢展開）
│   ├── test_arch_decisions_v03.py   ← 架構決策 v0.3.0（OllamaClient、MultilingualEmbedder）
│   ├── test_arch_decisions_v04.py   ← 架構決策 v0.4.0（長期願景 VISION-01~05）
│   ├── test_arch_decisions_v05.py   ← 架構決策 v0.5.0（靜默失效、FLY-01/02）
│   ├── test_arch_decisions_v06.py   ← 架構決策 v0.6.0（NudgeEngine、Synonym Map 等）
│   ├── test_ref04_constants.py      ← 📋 REF-04 魔法數字提取（待實作）
│   ├── test_perf03_token_cache.py   ← 📋 PERF-03 Token 計數快取（待實作）
│   └── test_bug_a03_locking.py     ← 📋 BUG-A03 雙重加鎖修復（待實作）
├── integration/
│   ├── test_cli.py                  ← CLI 命令端對端測試
│   ├── test_phase2.py               ← Phase 2 功能整合測試
│   ├── test_q2.py                   ← Q2 查詢流程測試
│   └── test_web_ui.py               ← Web UI 端點測試
├── chaos/
│   └── test_chaos_and_load.py       ← Chaos & 負載測試（6 個類，@pytest.mark.chaos）
└── benchmarks/
    ├── benchmark_recall.py          ← 召回率基準測試（目標 ≥ 60%，實測 95%）
    └── benchmark_rev01.py           ← REV-01 量化對照實驗（13 個測試案例）
```

**圖例**：
- ✅ 已通過 — 程式碼已實作，測試在 CI 中穩定通過
- 📋 測試計劃已寫 — 測試文件存在，等待程式碼實作
- △ 需真實數據 — 邏輯已實作，需累積線上數據後量測
- ⏳ 待規劃 — 尚未有測試文件或量測計劃

---

## 2. 單元測試（Unit）

### 2.1 核心功能 — `test_core.py` ✅

| 測試類別 | 覆蓋功能 | 狀態 |
|---------|---------|------|
| `TestGraphitiAdapter` | L2 降級邏輯（無 FalkorDB 時回傳空列表） | ✅ |
| `TestBrainDB` | add/get/update/delete/search_nodes CRUD | ✅ |
| `TestKnowledgeGraph` | L3 圖節點 + FTS5 搜尋 | ✅ |
| `TestContextEngineer` | context.build() token 預算 + SR 排序 | ✅ |
| `TestRouter` | 三層路由（L1a / L2 / L3 並行） | ✅ |
| `TestDecayEngine` | 信心衰減計算、pinning 保護 | ✅ |
| `TestNudgeEngine` | check() 返回相關 nudge | ✅ |
| `TestDef02FTS5Triggers` | 觸發器已移除；update/delete API 維護 FTS5 同步 | ✅ |

### 2.2 架構決策測試 — `test_arch_decisions_v01~v06.py` ✅

這些測試是「活的架構文件」— 每個決策都有對應的自動化驗收測試，確保未來修改不違反已確立的架構約定。

| 檔案 | 版本 | 決策 |
|------|------|------|
| `v01` | 0.1.0 | A：SQLite WAL 模式；B：衰減不刪節點（只降 confidence） |
| `v02` | 0.2.0 | C：BRAIN_WORKDIR 自動偵測；D：查詢展開上限 15 詞 |
| `v03` | 0.3.0 | E：OllamaClient duck-typed；F：MultilingualEmbedder 優先；G：export 時清除 PII；I：ANN fallback LinearScan |
| `v04` | 0.4.0 | VISION-01~05：動態信心、衝突仲裁、跨專案遷移、唯讀模式、多庫合併查詢 |
| `v05` | 0.5.0 | J：無裸 `except: pass`；FLY-01 冷啟動引導；FLY-02 scope 推斷優先順序 |
| `v06` | 0.6.0 | K-1~K-5：NudgeEngine bridge；Synonym Map 46 條；ReviewBoard schema；SR access_count 時序 |

### 2.3 SessionStore — `test_session_store.py` ✅

| 測試類別 | 覆蓋功能 | 狀態 |
|---------|---------|------|
| `TestSessionStoreCRUD` | set/get/delete/list | ✅ |
| `TestSessionStoreTTL` | 過期條目自動清除 | ✅ |
| `TestSessionStoreCategories` | pitfalls/decisions/context 分類 | ✅ |
| `TestSessionStoreConcurrency` | 多執行緒並行寫入 | ✅ |

### 2.4 待實作項目 — 詳見第 6 節

| 檔案 | 對應項目 | 狀態 |
|------|---------|------|
| `test_ref04_constants.py` | REF-04 魔法數字提取 | 📋 |
| `test_perf03_token_cache.py` | PERF-03 Token 快取 | 📋 |
| `test_bug_a03_locking.py` | BUG-A03 雙重加鎖 | 📋 |

---

## 3. 整合測試（Integration）

| 檔案 | 覆蓋功能 | 狀態 |
|------|---------|------|
| `integration/test_cli.py` | brain add / ask / review / scan CLI 命令 | ✅ |
| `integration/test_phase2.py` | Phase 2 功能組（NudgeEngine、FederationSync、ConflictResolver） | ✅ |
| `integration/test_q2.py` | Q2 查詢流程（expand → route → build context） | ✅ |
| `integration/test_web_ui.py` | Web UI REST 端點（/v1/context、/v1/nodes 等） | ✅ |

### Legacy 根目錄測試（已遷移但保留）

| 檔案 | 說明 |
|------|------|
| `tests/test_core.py` | 遺留版本，部分與 unit/test_core.py 重疊 |
| `tests/test_cli.py` | 遺留 CLI 測試 |
| `tests/test_api.py` | REST API 端點測試 |
| `tests/test_mcp.py` | MCP Server 工具測試 |
| `tests/test_session_store.py` | 遺留 SessionStore 測試 |
| `tests/test_web_ui.py` | 遺留 Web UI 測試 |

---

## 4. Chaos & 負載測試

**執行指令**：`python -m pytest tests/chaos/test_chaos_and_load.py -m chaos -v`

| 測試類別 | 場景 | 執行模式 | 狀態 |
|---------|------|---------|------|
| `TestChaosL3GraphFailure` | SQLite 鎖競爭、連線中斷恢復 | `@pytest.mark.chaos` | ✅ 通過 |
| `TestChaosL1SessionStore` | SessionStore 並行寫入衝突 | `@pytest.mark.chaos` | ✅ 通過 |
| `TestChaosSemanticDedup` | 去重邏輯邊界：極高相似度節點 | `@pytest.mark.chaos` | ✅ 通過 |
| `TestChaosKRB` | ReviewBoard DB 損壞恢復 | `@pytest.mark.chaos` | ✅ 通過 |
| `TestLoadL3Graph` | 1000 節點批次寫入性能 | `@pytest.mark.chaos` | ✅ 通過 |
| `TestLoadConcurrent` | 20 執行緒並行讀寫 | `@pytest.mark.chaos` | ✅ 通過 |

**通過率**：17/17（STAB-08，2026-04-04）

**CI Gate 條件**：v0.7.0 發布前，`pytest -m chaos` 必須 100% 通過。

---

## 5. 基準測試（Benchmark）

### 5.1 召回率基準 — `benchmarks/benchmark_recall.py` ✅

**執行指令**：`python -m pytest tests/benchmarks/benchmark_recall.py -v`

| 指標 | 門檻 | 實測結果（v0.6.0）|
|------|------|-----------------|
| `get_context` 召回率 | ≥ 60% | **95%**（MultilingualEmbedder + hybrid FTS5+vector）|

**測試集**：50 個知識節點 + 20 個查詢 + 已知正確答案集

---

## 6. 待實作項目測試計劃

以下三個項目的測試文件**已寫完**，等待通知後執行程式碼實作。

---

### REF-04 — 魔法數字提取（constants）

**測試文件**：`tests/unit/test_ref04_constants.py`
**預估工時**：半天
**優先級**：P3

#### 問題描述

魔法數字散落於多個模組，修改時需同步多處：

| 數值 | 位置 | 意圖 |
|------|------|------|
| `0.003` | `brain_db.py:~300` | 每日衰減率（Ebbinghaus 曲線）|
| `800` | `context.py:~288` | ADR 節點的 content token 上限 |
| `400` | `context.py:~288` | 一般節點的 content token 上限 |
| `8` | `engine.py`、`cli.py`、`graph.py` | 搜尋預設回傳數量 |

注意：`decay_engine.py` 已有 `BASE_DECAY_RATE = 0.003`，但 `brain_db.py` 的相同數值是孤立字面量，未引用。

#### 實作計劃

1. 建立 `project_brain/constants.py`：
   ```python
   BASE_DECAY_RATE  = 0.003   # 日衰減率
   ADR_CONTENT_CAP  = 800     # ADR 節點最大 content 字元數
   NODE_CONTENT_CAP = 400     # 一般節點最大 content 字元數
   DEFAULT_SEARCH_LIMIT = 8   # search_nodes 預設 limit
   ```

2. `brain_db.py` 替換 `0.003` → `from .constants import BASE_DECAY_RATE`

3. `context.py` 替換 `800` / `400` → `ADR_CONTENT_CAP` / `NODE_CONTENT_CAP`

4. `engine.py`、`cli.py`、`graph.py` 替換 `limit=8` → `DEFAULT_SEARCH_LIMIT`

#### 測試群組

| 群組 | 類別 | 測試項目 | 驗證方式 |
|------|------|---------|---------|
| 1 | `TestRef04ConstantsModuleExists` | `project_brain.constants` 可匯入 | `import` 不拋錯 |
| 1 | | `BASE_DECAY_RATE == 0.003` | 值斷言 |
| 1 | | `ADR_CONTENT_CAP == 800` | 值斷言 |
| 1 | | `NODE_CONTENT_CAP == 400` | 值斷言 |
| 1 | | `DEFAULT_SEARCH_LIMIT == 8` | 值斷言 |
| 1 | | `ADR_CONTENT_CAP > NODE_CONTENT_CAP` | 邏輯斷言 |
| 2 | `TestRef04BrainDbUsesConstant` | `_effective_confidence` 與 `BASE_DECAY_RATE` 計算一致 | 數值比對（誤差 < 1e-9）|
| 2 | | `monkeypatch BASE_DECAY_RATE=0.010` 後行為改變 | monkeypatch 驗證 |
| 3 | `TestRef04ContextUsesContentCaps` | ADR 節點 content 被截斷在 800 字元內 | `len(result)` 斷言 |
| 3 | | `context.py` 原始碼無孤立字面量 800/400 | AST 掃描 |
| 4 | `TestRef04SearchLimitUsesConstant` | `search_nodes()` 預設回傳 ≤ 8 筆 | 結果數量斷言 |
| 4 | | `engine.py` 原始碼無 `limit=8` 字面量 | 字串搜尋 |

#### 執行方式

```bash
# 未實作（應失敗）
python -m pytest tests/unit/test_ref04_constants.py -v

# 實作後（應全部通過）
python -m pytest tests/unit/test_ref04_constants.py -v
```

---

### PERF-03 — Token 計數快取

**測試文件**：`tests/unit/test_perf03_token_cache.py`
**預估工時**：30 分鐘
**優先級**：P3

#### 問題描述

`context.py` 的 `_count_tokens(text)` 在每次組裝 context 時對同一段文字重複計算，沒有任何快取。CJK 邏輯逐字元判斷，在大量節點時累積成可觀的 CPU 開銷：

```
profile 範例（100 節點，每節點平均 300 字元）：
  _count_tokens  called 800+ times/request
  total chars processed: 240,000+
  wall time: ~15ms（可降至 < 1ms with cache）
```

#### 實作計劃

```python
# context.py 頂部加入
from functools import lru_cache

# 在函數定義上加
@lru_cache(maxsize=1024)
def _count_tokens(text: str) -> int:
    ...
```

若 `_count_tokens` 是 instance method，需改為 `@staticmethod` 或 module-level function，再加 `@lru_cache`。

#### 測試群組

| 群組 | 類別 | 測試項目 | 驗證方式 |
|------|------|---------|---------|
| 1 | `TestPerf03CacheApplied` | `cache_info()` 方法存在 | `hasattr` 檢查 |
| 1 | | `cache_clear()` 方法存在 | `hasattr` 檢查 |
| 1 | | 相同輸入第二次呼叫為 cache hit | `cache_info().hits >= 1` |
| 1 | | 第一次呼叫為 cache miss | `cache_info().misses >= 1` |
| 1 | | `maxsize >= 1024` | `cache_info().maxsize` 斷言 |
| 2 | `TestPerf03Correctness` | 8 個邊界值（空字串、純 CJK、純 ASCII 等）結果穩定 | 參數化測試，5 次呼叫結果一致 |
| 2 | | 空字串回傳 0 | 值斷言 |
| 2 | | CJK token 數 ≥ 同長 ASCII | 大小關係斷言 |
| 2 | | 快取命中不污染結果 | 3 次呼叫結果相同 |
| 3 | `TestPerf03Benchmark` | 1000 次快取 vs 1000 次 `__wrapped__`，加速比 ≥ 10x | `time.perf_counter()` 計時 |
| 3 | | 20 種文字各 50 次，命中率 ≥ 90% | `cache_info().hits / total` |
| 3 | | `context.build()` cold → warm，warm ≤ cold × 0.8 | 端對端計時 |
| 4 | `TestPerf03EdgeCases` | emoji、全形、零寬空格不污染快取 | 相同輸入結果一致 |
| 4 | | 10000 字元長文字快取正確 | 結果穩定 |
| 4 | | 不同輸入不互相污染 | 5 種文字各自結果不混淆 |

#### 執行方式

```bash
python -m pytest tests/unit/test_perf03_token_cache.py -v
python -m pytest tests/unit/test_perf03_token_cache.py -v -k "Benchmark"  # 只跑效能測試
```

---

### BUG-A03 — 雙重加鎖修復

**測試文件**：`tests/unit/test_bug_a03_locking.py`
**預估工時**：1 小時
**優先級**：P3

#### 問題描述

`engine.py` 的 `ProjectBrain` 類別有 6 個懶加載屬性共用同一個 `_init_lock = threading.Lock()`（非可重入鎖）：

```
屬性：db / graph / context_engineer / decay_engine / nudge_engine / router
```

**雙重加鎖競態（double-checked locking without volatile）**：

```python
# 現有（有問題的）實作
@property
def db(self):
    if self._db is None:          # ← 無鎖保護的外部檢查
        with self._init_lock:     # ← 共用鎖
            if self._db is None:
                self._db = BrainDB(...)
    return self._db
```

問題：
1. 兩個執行緒同時通過外部 `if self._db is None` 檢查
2. Thread A 初始化後釋放鎖
3. Thread B 仍進入鎖內，**二次初始化**，產生兩個不同的 `sqlite3.Connection`

**死鎖風險**：若屬性 A 的初始化觸發屬性 B（例如 `context_engineer` 需要 `db`），而 `_init_lock` 是非可重入鎖，持鎖中再 acquire 同一鎖 → 死鎖。

#### 實作計劃

為每個屬性建立獨立鎖：

```python
# ProjectBrain.__init__
self._db_lock            = threading.Lock()
self._graph_lock         = threading.Lock()
self._context_lock       = threading.Lock()
self._decay_lock         = threading.Lock()
self._nudge_lock         = threading.Lock()
self._router_lock        = threading.Lock()

# 移除 _init_lock = threading.Lock()

# 每個 @property 改用自己的鎖
@property
def db(self) -> BrainDB:
    if self._db is None:
        with self._db_lock:
            if self._db is None:
                self._db = BrainDB(self.brain_dir)
    return self._db
```

#### 測試群組

| 群組 | 類別 | 測試項目 | 驗證方式 |
|------|------|---------|---------|
| 1 | `TestBugA03LockStructure` | 無 `_init_lock` 屬性 | `hasattr` 否定檢查 |
| 1 | | 6 個專用鎖存在（`_db_lock` 等）| `hasattr` 正向檢查 |
| 1 | | 每個鎖有 `acquire/release` 介面 | 介面斷言 |
| 1 | | 所有鎖 `id()` 互不相同 | `id` 唯一性 |
| 2 | `TestBugA03SingleInit` | 20 執行緒並行 `engine.db`，只有 1 個實例 | `id()` 集合大小 == 1 |
| 2 | | 20 執行緒並行 `engine.graph`，只有 1 個實例 | `id()` 集合大小 == 1 |
| 2 | | 任何執行緒拿到的 `engine.db` 不為 None | None 計數 == 0 |
| 3 | `TestBugA03NoDeadlock` | `engine.db` + `engine.graph` 各 10 執行緒，10 秒內完成 | `t.is_alive()` == False |
| 3 | | 6 個屬性各 5 執行緒（共 30），10 秒內完成 | `t.is_alive()` == False |
| 3 | | 鏈式存取（`context_engineer` → `db` → `graph`）不死鎖 | 10 秒超時 |
| 4 | `TestBugA03StressTest` | 50 執行緒隨機存取 3 個屬性，每屬性只有 1 個實例 | `id()` 集合大小 == 1 |
| 4 | | 同一執行緒 100 次存取 `engine.db`，每次 `id` 相同 | 穩定性斷言 |
| 4 | | 50 執行緒後所有 `engine.db` 的 `id` 與預期一致 | 跨執行緒一致性 |
| 5 | `TestBugA03Regression` | `engine.db` 可執行 CRUD 操作 | add/get 成功 |
| 5 | | `engine.graph` 可搜尋節點 | search 有結果 |
| 5 | | 兩個不同 `ProjectBrain` 實例的 `db` 互相獨立 | `id()` 不相等 |

#### 執行方式

```bash
python -m pytest tests/unit/test_bug_a03_locking.py -v
python -m pytest tests/unit/test_bug_a03_locking.py -v -k "NoDeadlock"  # 只跑死鎖測試
python -m pytest tests/unit/test_bug_a03_locking.py -v -k "StressTest"  # 只跑壓力測試
```

---

## 7. 真實數據量測計劃

以下項目的**程式碼實作已完成**，但需累積真實使用數據才能驗收。這些無法用 pytest 單元測試代替，需定期執行 SQL 查詢並核對門檻。

---

### REV-01 — 量化對照實驗（商業指標）

**狀態**：✅ Layer 1 自動化測試通過（13/13）；Layer 2/3 需累積線上數據
**核心假設**：Project Brain 能讓 Agent 在執行任務時召回已知 Pitfall，且知識品質透過反饋迴圈自我強化，最終減少重複踩坑。

#### 三層實驗架構

```
Layer 1  合成受控實驗（Synthetic Controlled Experiment）   ← 自動化，現在就可跑
Layer 2  生產反饋率量測（Production Utility Rate）          ← 需 30 天線上數據
Layer 3  Pitfall 非重現率量測（Pitfall Non-Recurrence）     ← 需 90 天線上數據
```

---

#### Layer 1 — 合成受控實驗（Automated，pytest）

**執行指令**：
```bash
python -m pytest tests/benchmarks/benchmark_rev01.py -v
```

**測試案例總覽**：

| 類別 | 測試案例 | 商業假設 | 門檻 | 狀態 |
|------|---------|---------|------|------|
| `TestREV01PitfallRecall` | `test_pitfall_recall_rate_meets_threshold` | A. 5 個 Pitfall 中 ≥ 4 個能被相關查詢召回 | 召回率 ≥ 70% | ✅ |
| `TestREV01PitfallRecall` | `test_each_pitfall_individually_retrievable` | A. 每個 Pitfall 單獨也能被召回 | 0 缺漏 | ✅ |
| `TestREV01ControlVsTreatment` | `test_treatment_vs_control_pitfall_avoidance` | B. 有 Brain vs 無 Brain 的 Pitfall 出現率差距 | ≥ 50pp | ✅ |
| `TestREV01ControlVsTreatment` | `test_rule_also_retrieved_in_treatment` | B. Rule 類型知識同樣可被召回 | context 非空 | ✅ |
| `TestREV01FeedbackLoop` | `test_positive_feedback_increases_confidence` | C. 正向反饋使 confidence +3% | 精確 +0.03 | ✅ |
| `TestREV01FeedbackLoop` | `test_negative_feedback_decreases_confidence` | D. 負向反饋使 confidence -5% | 精確 -0.05 | ✅ |
| `TestREV01FeedbackLoop` | `test_confidence_floor_enforced` | D. confidence 下限 0.05（DECAY_FLOOR） | ≥ 0.05 | ✅ |
| `TestREV01FeedbackLoop` | `test_confidence_ceiling_enforced` | C. confidence 上限 1.0（DECAY_CEIL） | ≤ 1.0 | ✅ |
| `TestREV01KnowledgePromotion` | `test_repeatedly_useful_node_reaches_high_confidence` | E. 15 次正向反饋後晉升為核心知識 | ≥ 0.90 | ✅ |
| `TestREV01KnowledgePromotion` | `test_alternating_feedback_stabilizes_confidence` | E. 正負交替不會讓 confidence 失控漂移 | ±0.15 內 | ✅ |
| `TestREV01AdoptionCount` | `test_adoption_count_increments_on_positive_feedback` | F. adoption_count 正確累加（F6 因子） | ≥ 3 | ✅ |
| `TestREV01AdoptionCount` | `test_negative_feedback_does_not_increment_adoption_count` | F. 負向反饋不影響 adoption_count | == 0 | ✅ |
| `TestREV01AdoptionCount` | `test_mixed_feedback_adoption_count_only_counts_positive` | F. 混合反饋只計正向次數 | == 3 | ✅ |

**合成資料集**：5 個真實場景 Pitfall（JWT / SQLite WAL / API Key / DB 遷移 / FTS5 一致性），每個搭配語意相關但用語不同的查詢，測試 FTS + 向量召回的真實能力。

---

#### Layer 2 — 生產反饋率量測（Real Data，30 天）

**商業意義**：Agent 確認有用的知識比例，代表 Brain 提供的 context 是否真的幫助了決策。

**量測方式**：
```sql
-- 執行位置：.brain/brain.db
-- 知識有用率（30 天內 report_knowledge_outcome 反饋統計）
SELECT
  ROUND(100.0 * SUM(CASE WHEN helpful = 1 THEN 1 ELSE 0 END)
        / NULLIF(COUNT(*), 0), 1)                            AS useful_rate_pct,
  SUM(CASE WHEN helpful = 1 THEN 1 ELSE 0 END)              AS useful_count,
  SUM(CASE WHEN helpful = 0 THEN 1 ELSE 0 END)              AS not_useful_count,
  COUNT(*)                                                   AS total_feedback
FROM (
  -- helpful 欄位記錄在 adoption_count 增加前後的節點變化
  SELECT n.id,
    CASE WHEN n.adoption_count > 0 THEN 1 ELSE 0 END AS helpful
  FROM nodes n
  WHERE n.updated_at >= datetime('now', '-30 days')
    AND n.access_count > 0
);

-- 前 10 最常被確認有用的知識（高 adoption_count 節點）
SELECT
  id, title, type,
  adoption_count,
  ROUND(confidence, 2) AS confidence,
  access_count
FROM nodes
WHERE adoption_count > 0
ORDER BY adoption_count DESC
LIMIT 10;

-- 信心分布：反饋對 confidence 的實際影響
SELECT
  CASE
    WHEN confidence >= 0.90 THEN '核心知識（≥ 0.90）'
    WHEN confidence >= 0.70 THEN '穩定知識（0.70–0.89）'
    WHEN confidence >= 0.50 THEN '一般知識（0.50–0.69）'
    ELSE                         '低信心（< 0.50）'
  END AS tier,
  COUNT(*) AS node_count,
  ROUND(AVG(adoption_count), 1) AS avg_adoption
FROM nodes
WHERE is_deprecated = 0
GROUP BY tier
ORDER BY MIN(confidence) DESC;
```

**量測前提條件**：
- [ ] `report_knowledge_outcome` 已被 Agent 呼叫至少 20 次
- [ ] 知識庫節點數 > 30
- [ ] 已使用 Brain 完成至少 10 個非瑣碎任務

**驗收門檻（30 天）**：

| 指標 | 目標 | 未達標時的行動 |
|------|------|--------------|
| 知識有用率（useful_rate_pct）| ≥ 60% | 審查低信心節點，清除過時知識 |
| 有 adoption_count > 0 的節點比例 | ≥ 30% | 確認 Agent 是否實際呼叫 `report_knowledge_outcome` |
| 核心知識層（confidence ≥ 0.90）節點數 | ≥ 5 | 增加正向反饋呼叫頻率 |

---

#### Layer 3 — Pitfall 非重現率量測（Real Data，90 天）

**商業意義**：如果 Brain 中已有的 Pitfall 在之後的任務中被重新「發現」並以近似方式加入，代表 Agent 沒有在任務開始時成功召回該 Pitfall，Brain 對踩坑預防的效果失效。

**量測方式**：
```sql
-- 偵測「重複 Pitfall」：新加入的 Pitfall 與現有 Pitfall 高度相似
-- （near_duplicate 事件由 SemanticDedup 在 add_knowledge 時觸發）
SELECT
  json_extract(payload, '$.existing_id') AS existing_id,
  json_extract(payload, '$.new_id')      AS new_id,
  ROUND(json_extract(payload, '$.similarity'), 3) AS similarity,
  created_at
FROM events
WHERE event_type = 'near_duplicate'
  AND created_at >= datetime('now', '-90 days')
ORDER BY similarity DESC;

-- 計算 Pitfall 重現率
SELECT
  ROUND(100.0 * COUNT(DISTINCT json_extract(payload, '$.existing_id'))
        / NULLIF((SELECT COUNT(*) FROM nodes WHERE type='Pitfall'), 0), 1)
  AS pitfall_recurrence_rate_pct
FROM events
WHERE event_type = 'near_duplicate'
  AND created_at >= datetime('now', '-90 days');
```

**量測前提條件**：
- [ ] 知識庫 Pitfall 節點 ≥ 10
- [ ] 已運行 ≥ 90 天，完成 ≥ 30 個任務
- [ ] SemanticDedup 已啟用（`near_duplicate` 事件存在）

**驗收門檻（90 天）**：

| 指標 | 目標 | 說明 |
|------|------|------|
| Pitfall 重現率（pitfall_recurrence_rate_pct）| < 20% | > 20% 代表 Pitfall 召回失效，需調整 context token budget 或查詢策略 |
| near_duplicate similarity ≥ 0.90 的事件數 | < 5 | 高相似度重複代表嚴重召回失敗（同一個坑踩兩次） |

---

#### 驗收里程碑

| 時間點 | 里程碑 | 動作 |
|--------|--------|------|
| 現在 | Layer 1 全通過（13/13 ✅）| `pytest tests/benchmarks/benchmark_rev01.py` |
| +30 天 | Layer 2 知識有用率 ≥ 60% | 執行 Layer 2 SQL，記錄結果至 CHANGELOG |
| +90 天 | Layer 3 Pitfall 重現率 < 20% | 執行 Layer 3 SQL，評估是否需要調整召回策略 |
| +90 天 | 三層全通過 → REV-01 ✅ 完整驗收 | 更新 IMPROVEMENT_PLAN.md 狀態 |

---

### FLY-04 — NudgeEngine 命中率

**狀態**：△ emit 邏輯已實作，需累積事件數據
**門檻**：≥ 30%（在知識庫 > 20 節點後開始量測）
**實作位置**：`project_brain/nudge_engine.py` → `check()` emit `nudge_triggered` 事件

#### 量測方式

```sql
-- 執行位置：.brain/brain.db
-- 計算 NudgeEngine 命中率
SELECT
  CAST(SUM(CASE WHEN event_type='nudge_triggered' THEN 1 ELSE 0 END) AS REAL)
  / NULLIF(SUM(CASE WHEN event_type='get_context' THEN 1 ELSE 0 END), 0) AS hit_rate,
  SUM(CASE WHEN event_type='nudge_triggered' THEN 1 ELSE 0 END) AS nudge_count,
  SUM(CASE WHEN event_type='get_context' THEN 1 ELSE 0 END) AS context_count
FROM events
WHERE created_at >= datetime('now', '-30 days');
```

#### 量測前提條件

- [ ] 知識庫節點數 > 20（節點太少 nudge 幾乎不會觸發）
- [ ] 已使用 `brain ask` / `get_context` MCP 工具至少 30 次
- [ ] `events` 表有 `nudge_triggered` 和 `get_context` 記錄

#### 解讀標準

| 命中率 | 判斷 |
|--------|------|
| ≥ 30% | ✅ 飛輪健康 |
| 15% ~ 30% | ⚠️ 知識庫節點數可能不足，或 nudge 主題與查詢不符 |
| < 15% | ❌ 需檢查 NudgeEngine 相關性邏輯 |

#### 提升命中率的方向

1. 增加知識庫節點數（尤其是 Pitfall 類型）
2. 確認 `nudge_engine.check()` 相關性分數計算正確
3. 確認 `get_context` 呼叫有傳入有意義的 `task` 描述

---

### FLY-05 — 知識庫自然成長率

**狀態**：△ SQL 就緒，需累積真實使用數據
**門檻**：7 天內 ≥ 5 個節點自動寫入（auto:complete_task tag）
**實作位置**：`complete_task` MCP 工具 → 自動寫入 `add_knowledge`

#### 量測方式

```sql
-- 執行位置：.brain/brain.db
-- 統計近 7 天自動新增節點數
SELECT
  COUNT(*) AS auto_nodes_7d,
  MAX(created_at) AS latest_added
FROM nodes
WHERE tags LIKE '%auto:complete_task%'
  AND created_at >= datetime('now', '-7 days');

-- 分類統計
SELECT
  type,
  COUNT(*) AS count
FROM nodes
WHERE tags LIKE '%auto:complete_task%'
  AND created_at >= datetime('now', '-7 days')
GROUP BY type
ORDER BY count DESC;
```

#### 量測前提條件

- [ ] 已在 7 天內完成至少 5 個非瑣碎任務（呼叫 `complete_task`）
- [ ] `complete_task` 的 `lessons` 或 `decisions` 不為空（空的不會新增節點）
- [ ] `ANTHROPIC_API_KEY` 已設置（AI 提取知識需要 LLM）

#### 解讀標準

| 7 天新增數 | 判斷 |
|-----------|------|
| ≥ 5 | ✅ 飛輪正在轉 |
| 1 ~ 4 | ⚠️ 使用頻率低，或 complete_task 未帶有效 lessons/decisions |
| 0 | ❌ 需檢查 complete_task 是否正確觸發 |

#### 搭配 brain status 查看

```bash
brain status
# 輸出中「🌀 飛輪健康度」區塊會顯示：
#   近 7 天新增 N 節點（目標 ≥ 5，當前總計 M）
```

---

### REV-02 — 衰減效用量測

**狀態**：⏳ 等待數據（從 `IMPROVEMENT_PLAN.md` 移入；需知識庫運行 > 90 天）
**問題**：無法確認 Ebbinghaus 衰減是幫助 Agent 避免使用過時知識，還是反而降低了有效知識的可見度

#### 量測設計

**方法 A：對比實驗（需要兩個知識庫）**

```bash
# 建立兩個知識庫
brain init --workdir /tmp/brain_with_decay     # 啟用衰減（預設）
brain init --workdir /tmp/brain_without_decay  # 停用衰減

# 使用相同的知識集，分別在兩個庫中查詢 20 個問題
# 統計哪個庫的召回率更高
python -m pytest tests/benchmarks/benchmark_recall.py \
  --brain-dir /tmp/brain_with_decay
python -m pytest tests/benchmarks/benchmark_recall.py \
  --brain-dir /tmp/brain_without_decay
```

**方法 B：過時知識偵測率**

在知識庫中故意放入「過時」知識（created_at 設為 1 年前），查詢相關問題，觀察：
1. 有衰減時，過時知識的 confidence 降至何值
2. 過時知識是否仍排在搜尋結果前列

```sql
-- 量測：90 天前的節點，衰減後的平均 confidence
SELECT
  AVG(confidence) AS avg_current_confidence,
  COUNT(*) AS node_count,
  julianday('now') - julianday(created_at) AS age_days
FROM nodes
WHERE created_at <= datetime('now', '-90 days')
  AND is_pinned = 0
GROUP BY CAST(age_days / 30 AS INT)  -- 按月份分組
ORDER BY age_days;
```

#### 量測前提條件

- [ ] 知識庫已運行 > 90 天，有足夠的時序數據
- [ ] 有已知「應過時」的節點可供對照
- [ ] `decay_engine.run()` 已定期執行（可透過 cron 或 `brain sync` 觸發）

#### 驗收門檻（建議）

| 指標 | 目標 |
|------|------|
| 90 天前節點的平均 confidence | < 0.5（明顯衰減）|
| 過時節點排在搜尋前 3 的比例 | < 20%（不妨礙主要召回）|
| 有衰減 vs 無衰減的召回率差距 | < 5%（衰減不傷害整體召回）|

---

### 四維指標 — 版本週期一致性

**狀態**：△ 需 CHANGELOG 歷史資料
**門檻**：相鄰版本完成數差距 ≤ 30%
**問題**：目前 CHANGELOG 各版本完成條目數未統計

#### 量測方式

```bash
# 計算各版本的 CHANGELOG 完成條目數
grep -c "✅" CHANGELOG.md  # 總數

# 或按版本分段統計
awk '/^## v/{ver=$2} /✅/{count[ver]++} END{for(v in count) print v, count[v]}' CHANGELOG.md | sort
```

#### 量測前提條件

- [ ] CHANGELOG.md 各版本條目使用 ✅ 標記完成項目
- [ ] 至少有 3 個版本的完成記錄可供比較

---

## 8. 品質門檻總表

| 指標 | 門檻 | 量測方法 | v0.6.0 現況 |
|------|------|---------|------------|
| Chaos test 通過率 | **100%（Gate）** | `pytest -m chaos` | ✅ 17/17 |
| `get_context` 召回率 | **≥ 60%（Gate）** | `benchmark_recall.py` | ✅ **95%** |
| 靜默失效路徑 | **0（Gate）** | `grep 'except.*pass'` | ✅ 0 |
| Migration 失敗可觀察率 | **100%** | 故意破壞 schema 後確認 warning | ✅ |
| REV-01 Layer 1 Pitfall 召回率 | ≥ 70% | `benchmark_rev01.py` | ✅ 100% |
| REV-01 Layer 1 對照實驗差距 | ≥ 50pp | `benchmark_rev01.py` | ✅ 100% |
| REV-01 Layer 2 知識有用率 | ≥ 60%（30 天）| SQL 查詢 nodes 表 | △ 需累積 |
| REV-01 Layer 3 Pitfall 重現率 | < 20%（90 天）| SQL 查詢 events 表 | △ 需累積 |
| NudgeEngine 命中率 | ≥ 30%（> 20 節點後）| SQL 查詢 events 表 | △ 需累積 |
| 知識庫自然成長率 | ≥ 5 節點/7 天 | SQL 查詢 nodes 表 | △ 需累積 |
| 功能狀態標記覆蓋率 | 100% | COMMANDS.md 命令表 | ✅ 22/22 |
| Synonym Map 一致性 | 差距 ≤ 2 條 | `len()` 比較 | ✅ 46 = 46 |
| ANN 觸發條件文件化 | 已標注 | COMMANDS.md 向量索引說明 | ✅ |
| 版本週期完成數差距 | ≤ 30% | CHANGELOG 統計 | △ 未量測 |
| REF-04 魔法數字 | 無孤立字面量 | AST 掃描 + pytest | 📋 待實作 |
| PERF-03 token 快取 | cache hit 率 ≥ 90% | pytest benchmark | 📋 待實作 |
| BUG-A03 競態修復 | 單一初始化實例 | pytest concurrency | 📋 待實作 |

---

## 9. 執行指令速查

```bash
# ── 全部單元測試 ──────────────────────────────────────────
python -m pytest tests/unit/ -v

# ── 全部整合測試 ──────────────────────────────────────────
python -m pytest tests/integration/ -v

# ── Chaos & 負載測試（需明確標記）────────────────────────
python -m pytest tests/chaos/ -m chaos -v

# ── 召回率基準測試 ─────────────────────────────────────────
python -m pytest tests/benchmarks/benchmark_recall.py -v

# ── REV-01 量化對照實驗（13 個測試案例）────────────────────
python -m pytest tests/benchmarks/benchmark_rev01.py -v
python -m pytest tests/benchmarks/benchmark_rev01.py -v -k "ControlVsTreatment"  # 只跑對照實驗
python -m pytest tests/benchmarks/benchmark_rev01.py -v -k "FeedbackLoop"         # 只跑反饋迴圈

# ── 待實作項目（目前應失敗）──────────────────────────────
python -m pytest tests/unit/test_ref04_constants.py -v
python -m pytest tests/unit/test_perf03_token_cache.py -v
python -m pytest tests/unit/test_bug_a03_locking.py -v

# ── 覆蓋率報告 ────────────────────────────────────────────
python -m pytest tests/unit/ tests/integration/ \
  --cov=project_brain --cov-report=term-missing

# ── 真實數據量測（在有 .brain/ 的目錄下執行）────────────
sqlite3 .brain/brain.db \
  "SELECT event_type, COUNT(*) FROM events GROUP BY event_type"

sqlite3 .brain/brain.db \
  "SELECT COUNT(*) FROM nodes WHERE tags LIKE '%auto:complete_task%'
   AND created_at >= datetime('now','-7 days')"

# ── 發布前完整檢查（Gate）─────────────────────────────────
python -m pytest tests/unit/ tests/integration/ tests/chaos/ -m "not slow" -v
python -m pytest tests/benchmarks/benchmark_recall.py -v
```

---

## 附錄：快速索引

| 想測試什麼 | 執行指令 |
|-----------|---------|
| REF-04 常數提取 | `pytest tests/unit/test_ref04_constants.py -v` |
| PERF-03 token 快取 | `pytest tests/unit/test_perf03_token_cache.py -v` |
| BUG-A03 鎖修復 | `pytest tests/unit/test_bug_a03_locking.py -v` |
| 架構決策 v0.1~0.6 | `pytest tests/unit/test_arch_decisions_v0*.py -v` |
| SQLite WAL 模式 | `pytest tests/unit/test_arch_decisions_v01.py -v -k WAL` |
| 衰減不刪節點 | `pytest tests/unit/test_arch_decisions_v01.py -v -k Decay` |
| 靜默失效檢查 | `pytest tests/unit/test_arch_decisions_v05.py -v -k Silent` |
| FTS5 觸發器移除 | `pytest tests/unit/test_core.py -v -k Def02` |
| Chaos 全部 | `pytest tests/chaos/ -m chaos -v` |
| 召回率 | `pytest tests/benchmarks/benchmark_recall.py -v` |
| 並行死鎖 | `pytest tests/unit/test_bug_a03_locking.py -v -k NoDeadlock` |
| 快取效能 | `pytest tests/unit/test_perf03_token_cache.py -v -k Benchmark` |
