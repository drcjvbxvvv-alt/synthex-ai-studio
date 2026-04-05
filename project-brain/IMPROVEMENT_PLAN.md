# Project Brain — 改善規劃書

> **當前版本**：v0.16.0（2026-04-05）
> **文件用途**：待辦改善項目。已完成項目見 `CHANGELOG.md`。
> **分析基準**：873 tests collected；v0.13.0 所有 P1+P2 已完成，867 passed / 5 skipped / 1 intermittent。

---

## 優先等級

| 等級 | 說明 | 目標版本 |
|------|------|---------|
| **P1** | 明確影響正確性或安全性，應優先處理 | v0.12.0 |
| **P2** | 影響核心功能品質，計劃排入 | v0.13.0 |
| **P3** | 長期願景、低頻路徑、實驗性 | 評估中 |

---

## 矩陣優先總覽

| 優先 | ID | 影響 | 解決方案 | 阻塞依賴 | 象限 | 狀態 |
|------|----|------|---------|---------|------|------|
| **P1** | SEC-03 | API key 字串比對有 timing attack 漏洞 | `hmac.compare_digest()` 取代 `!=` | 無 | ⚡ 快速獲益 | ✅ v0.12.0 |
| **P1** | BUG-D01 | 29 處 `except Exception: pass` 靜默吞錯 | 逐一加 `logger.warning`，critical 路徑改 `logger.error` | 無 | ⚡ 快速獲益 | ✅ v0.12.0 |
| **P1** | BUG-D02 | `embedder.py._embedder_cache` 無鎖，多執行緒競態 | 加 `threading.Lock()` 保護 dict read/write | 無 | ⚡ 快速獲益 | ✅ v0.12.0 |
| **P1** | TEST-01 | 15 個測試失敗（chaos 路徑、web_ui AttributeError、lora、embedding cache） | 修復或標記 skip；確保 CI 全綠 | 無 | 🎯 高價值 | ✅ v0.12.0 |
| **P1** | PERF-05 | Decay `_detect_contradictions()` N+1 查詢：每對矛盾各一次 `SELECT confidence` | 批次預取所有節點信心值至 dict | 無 | ⚡ 快速獲益 | ✅ v0.12.0 |
| **P1** | BUG-E01 | `_search_batch(terms[:8])` 截斷使「版本號」「路徑」等關鍵詞被丟棄，Rule 類 False Negative | ① 改 `terms[:15]`；② 補 API 同義詞；③ Rule 配額 2→3 | 無 | 🎯 高價值 | ✅ v0.12.0 |
| **P2** | FEAT-07 | `archaeologist` 掃描 git 歷史後所有節點 `created_at = today`，舊專案 F1 衰減從零開始等 7 天 | ① `add_node()` 接受 `created_at` 參數；② 改 `INSERT OR REPLACE` → `UPSERT` 保留原始日期；③ 新增 `brain backfill-git` 指令 | 無 | 🎯 高價值 | ✅ v0.13.0 |
| **P2** | PERF-06 | 缺少 `nodes(type, confidence DESC)` 複合索引，type 過濾搜尋全表掃描 | SCHEMA_VERSION=21：`CREATE INDEX idx_nodes_type_conf ON nodes(type, confidence DESC)` | 無 | ⚡ 快速獲益 | ✅ v0.13.0 |
| **P2** | BUG-D03 | KRB `ai_screen_cache.db` 只 lazy 刪除過期項，從不 VACUUM，檔案持續增長 | 每次 `KRBAIAssistant.__init__` 呼叫時條件性執行 `VACUUM`（間隔 7 天） | 無 | 🔵 填空 | ✅ v0.13.0 |
| **P2** | BUG-D04 | `session_store.py` per-thread 連線從未關閉，長執行伺服器 FD 洩漏 | 改用單一共享連線 `check_same_thread=False`（WAL 模式安全） | 無 | 📋 計劃執行 | ✅ v0.13.0 |
| **P2** | ARCH-07 | `cli_utils._infer_scope()` 與 `brain_db.infer_scope()` 邏輯重複（兩套實作）| 保留 `brain_db.infer_scope()` 為單一來源，`cli_utils` 委派呼叫 | 無 | 📋 計劃執行 | ✅ v0.13.0 |
| **P2** | OBS-02 | `decay_engine` 缺乏 F1–F7 各因子的量測輸出（無法調參） | 在 `_apply_decay()` 結束時 `db.emit("decay_factors", {f1, f2, ..., f7, final})`  | OBS-01 ✅ | 📋 計劃執行 | ✅ v0.14.0 |
| **P2** | OBS-03 | `rollback_node()` 無審計記錄（誰在何時還原了什麼）| `node_history` 新增 `changed_by TEXT`；`rollback_node()` 寫入還原事件 | FEAT-01 ✅ | 📋 計劃執行 | ✅ v0.15.0 |
| **P2** | SEC-04 | Federation PII 過濾缺失 IP（`192.168.x.x`）、Slack URL、Cloud service URL | 擴充 `_strip_pii()` regex 模式集 | 無 | 📋 計劃執行 | ✅ v0.15.0 |
| **P2** | REV-02 | 衰減效用幫助還是傷害召回率，目前未知 | 90 天數據後執行對比測試；`analytics_engine` 新增 `decay_impact_score()` | 90天數據 | ⏳ 等待 | → `tests/TEST_PLAN.md §7` |
| **P3** | FEAT-05 | `analytics_engine` 無時序圖表：知識庫成長曲線、信心分布遷移無法可視化 | `generate_timeseries()` 方法；`brain report --format html` 輸出 Chart.js 圖表 | OBS-01 ✅ | 🏗 長期 | ✅ v0.16.0 |
| **P3** | FEAT-06 | `brain doctor` 只做基礎健康檢查，無法偵測矛盾節點比例、deprecated 比例 | 新增矛盾節點數量報告；deprecated 比例警告（> 20% 觸發 ⚠） | ARCH-06 ✅ | 📋 計劃執行 | ✅ v0.16.0 |
| **P3** | ARCH-08 | `conflict_resolver.py` 快取無 TTL 淘汰，長執行記憶體持續增長 | 加入 TTL 驅逐（已有 `CACHE_SECONDS=86400` 常數，但無清理機制） | ARCH-06 ✅ | 🔵 填空 | ✅ v0.16.0 |
| **P3** | TEST-02 | 缺乏針對 Decay Engine 的 100K 節點負載測試 | `tests/chaos/test_decay_load.py`：建立 100K 節點知識庫，量測衰減時間 | 無 | 🏗 長期 | ✅ v0.16.0 |
| **P3** | TEST-03 | Chaos 測試有硬編碼 `/home/claude/synthex_v10/brain.py` 路徑（永遠失敗） | 用 `Path(__file__).parent` 或 fixture 取代硬編碼路徑 | 無 | ⚡ 快速獲益 | ✅ v0.16.0 |

---

## 依賴鏈

```
SEC-03 ──┐
BUG-D01 ─┤ 無依賴，v0.12.0 可立即執行
BUG-D02 ─┤
PERF-05 ─┘

PERF-06 ──→ 無依賴（schema migration）
BUG-D03 ──→ 無依賴
TEST-01 ──→ 無依賴（修復現有測試）
TEST-03 ──→ 無依賴

OBS-02 ──→ OBS-01 ✅（structlog 基礎設施已就位）
OBS-03 ──→ FEAT-01 ✅（node_history 表已存在）

FEAT-06 ──→ ARCH-06 ✅（ConflictResolver 已有矛盾偵測）
ARCH-08 ──→ ARCH-06 ✅（conflict_resolver.py 已存在）

REV-02 ──→ 90 天真實數據（不可提前執行）
FEAT-05 ──→ OBS-01 ✅ + 充分的 events 數據
```

---

## P1 — 正確性 / 安全性缺陷

### SEC-03 — API Key Timing Attack

**問題**：`api_server.py:154`：
```python
if auth[7:].strip() != key:   # 字串比對非恆定時間
```
透過計時差異可推算 key 長度與前綴，在本地網路環境下可量測。

**修復**：
```python
import hmac
if not hmac.compare_digest(auth[7:].strip(), key):
```

**工時**：1 行，< 15 分鐘。

---

### BUG-D01 — 靜默例外吞錯（29 處）

**問題**：18 個檔案共 29 處 `except Exception: pass`，bug 和資料損毀完全不可見。

高危路徑（依嚴重程度）：

| 檔案 | 嚴重程度 | 危險原因 |
|------|---------|---------|
| `brain_db.py`（6 處） | 🔴 高 | migration 失敗、edge 寫入失敗靜默 |
| `cli_knowledge.py`（7 處） | 🟡 中 | 使用者操作失敗無反饋 |
| `graph.py`（5 處） | 🔴 高 | graph 操作失敗無記錄 |
| `federation.py`（4 處） | 🟡 中 | 匯入失敗靜默 |
| `engine.py`（3 處） | 🟡 中 | sync 失敗靜默 |

**修復方針**：
- 核心儲存路徑（`brain_db.py`、`graph.py`）：`except Exception as e: logger.error("...", e)`
- CLI 路徑：`except Exception as e: logger.warning("...", e)`
- 非關鍵輔助路徑（rich render、emoji）：`except Exception: logger.debug("...", exc_info=True)`

**工時**：2 天（逐一審查每個路徑）。

---

### BUG-D02 — Embedder Cache 競態（多執行緒）

**問題**：`embedder.py:305`：
```python
_embedder_cache: dict = {}   # 無 threading.Lock
```
FastMCP 在多執行緒環境下並發呼叫 `get_embedder()` 可能造成：
1. 重複建立 embedder（浪費 300ms+）
2. dict 寫入競態（CPython GIL 通常保護，但 Jython/PyPy 不保護）

**修復**：
```python
_embedder_lock = threading.Lock()

def get_embedder(provider: str = "") -> ...:
    with _embedder_lock:
        if provider in _embedder_cache:
            return _embedder_cache[provider]
        ...
```

**工時**：30 分鐘。

---

### TEST-01 — 修復 15 個失敗測試

**分類**：

| 類別 | 測試數 | 原因 | 修復方向 |
|------|--------|------|---------|
| `TestBug08WebUIPathConsistency`（4） | 4 | `generate_graph_html()` 函數已移除或簽名改變 | 更新測試以匹配現有 web_ui API |
| `TestB24RealUserPath`（4） | 4 | setup wizard 產生的 CLAUDE.md 格式變動 | 更新 expected 字串 |
| `TestEngineWithMockedLLM::test_add_knowledge_positional_cli`（2） | 2 | positional arg 順序改變 | 修正測試呼叫簽名 |
| `TestKnowledgeDistiller::test_lora_dataset_creates_jsonl`（2） | 2 | LoRA dataset 功能狀態不確定 | 確認功能存在或 `@pytest.mark.skip` |
| `TestOpt03EmbeddingCache::test_cache_hit_is_same_object`（1） | 1 | BUG-D02 競態造成每次回傳新實例 | 修復 BUG-D02 即可解決 |
| Chaos `test_l2_health_check_function_exists`（1） | 1 | 硬編碼 `/home/claude/synthex_v10/brain.py` | 見 TEST-03 |

**目標**：測試套件從 742/873 提升至 873/873（≥99% 通過率）。

**工時**：1.5 天。

---

### PERF-05 — Decay N+1 矛盾信心查詢

**問題**：`decay_engine.py` `_detect_contradictions()`：
```python
for node_a, node_b in contradiction_pairs:
    conf_a = db.conn.execute("SELECT confidence FROM nodes WHERE id=?", (node_a,)).fetchone()
    conf_b = db.conn.execute("SELECT confidence FROM nodes WHERE id=?", (node_b,)).fetchone()
```
100 對矛盾 = 200 次獨立 SELECT。

**修復**：預取所有節點信心值：
```python
all_ids = {n for pair in contradiction_pairs for n in pair}
conf_map = {r["id"]: r["confidence"] for r in db.conn.execute(
    f"SELECT id, confidence FROM nodes WHERE id IN ({','.join('?'*len(all_ids))})",
    list(all_ids)).fetchall()}
```

**工時**：1 小時。

---

### BUG-E01 — `_search_batch` 截斷導致 Rule 召回 False Negative

**觀察現象**：`benchmark_recall.py` 第 5 筆查詢 ❌：

```
query    : "如何設計 API 版本號，放路徑還是 Header"
expected : api-01  "API 版本號在路徑中，非 Header"
result   : 未出現在 get_context 回傳中
```

#### 根因分析（三層）

**根因 A（主要）：`_search_batch` 只用 `terms[:8]`，關鍵詞被截斷**

`_expand_query` 產生的 `expanded_terms`（15 個）按字面順序排列：

| 位置 | 詞 | 說明 |
|------|----|------|
| 1 | `api` | 英文詞 |
| 2 | `header` | 英文詞 |
| 3–8 | `如何` `何設` `設計` `如何設` `何設計` `如何設計` | "如何設計" 的所有 n-gram |
| **9–11** | **`版本` `本號` `版本號`** | **api-01 的核心辨別詞** |
| **12–13** | **`放路` `路徑`** | **api-01 的另一辨別詞** |
| 14–15 | `徑還` `還是` | 低信號詞 |

`_search_batch` 呼叫時：`" ".join(terms[:8])` → 只送入前 8 個詞，**位置 9–13 的 `版本`、`版本號`、`路徑` 全部被丟棄**。

FTS5 搜尋字串實際為：
```
"api header 如何 何設 設計 如何設 何設計 如何設計"
```

`api-01` 雖有 "api" 匹配，但其他 Rule 節點（如 `db-04`：「HTTP 呼叫或外部 API 不可放在資料庫 transaction 內部」）也有 "api" 且 BM25 不低，在 `limit=2` 下可能把 `api-01` 擠出。

**根因 B（次要）：Rule 類型配額過低（`limit=2`）**

`context.py:227`：
```python
rules = _search_batch(expanded_terms, node_type="Rule", limit=2)
```
50 個測試節點中 Rule 型節點共 12+ 個。只取前 2，任何 BM25 排名失準都會造成 False Negative。

**根因 C（加劇）：查詢前綴 n-gram 佔用擴展配額**

"如何設計" 產生 6 個 n-gram（如何, 何設, 設計, 如何設, 何設計, 如何設計），本質上都是「如何設計＝how to design」的噪音詞，消耗了 6 個名額，把有語義的「版本號」擠出 `[:8]` 視窗。

同時 `synonyms.py` 完全缺少 API 版本化領域的同義詞：

| 缺失詞 | 應擴展至 |
|--------|---------|
| `版本` | `versioning`, `v1`, `url`, `path`, `routing` |
| `版本號` | `versioning`, `api version`, `url`, `v1` |
| `路徑` (URL 語境) | `url`, `path`, `endpoint`, `route` |
| `header` (HTTP 語境) | `accept`, `content-type`, `api versioning` |

---

#### 修復方案

**Fix-1：`context.py` — 改 `terms[:8]` → `terms[:15]`**（15 分鐘）

`context.py:199` 的 `_search_batch` 內部：
```python
# 現行
_q_vec = _emb.embed(" ".join(terms[:8]))
...
db_results = self._brain_db.hybrid_search(
    " ".join(terms[:8]), ...
)
...
db_results = self._brain_db.search_nodes(
    " ".join(terms[:8]), ...
)
```

改為：
```python
_SEARCH_TERMS_CAP = 15          # 與 EXPAND_LIMIT 對齊，不再早截斷
_q_vec = _emb.embed(" ".join(terms[:_SEARCH_TERMS_CAP]))
...
db_results = self._brain_db.hybrid_search(
    " ".join(terms[:_SEARCH_TERMS_CAP]), ...
)
...
db_results = self._brain_db.search_nodes(
    " ".join(terms[:_SEARCH_TERMS_CAP]), ...
)
```

**Fix-2：`synonyms.py` — 補充 API 版本化領域同義詞**（30 分鐘）

```python
# API 版本化
"版本":    ["versioning", "v1", "url", "path", "routing", "api version"],
"版本號":  ["versioning", "api version", "url", "path", "v1"],
"路徑":    ["url", "path", "endpoint", "route", "routing"],
"header":  ["http header", "accept", "content-type", "versioning"],
"versioning": ["版本", "版本號", "url", "path", "v1"],
```

**Fix-3：`context.py` — Rule 配額 2 → 3**（5 分鐘）

```python
# context.py:227
rules = _search_batch(expanded_terms, node_type="Rule", limit=3)   # 2 → 3
```

---

#### 驗收標準

修復後執行：
```bash
python tests/benchmarks/benchmark_recall.py
```

- 第 5 筆查詢：`api-01` ✅（由 ❌ 變 ✅）
- 整體召回率不下降（Fix 可能順帶修復其他 False Negative）
- `benchmark_recall.py` 每個 FTS5 模式下召回率 ≥ 50%（無 sentence-transformers）

**工時**：Fix-1 + Fix-2 + Fix-3 合計 < 1 小時；加測試驗收共 2 小時。

---

## P2 — 核心功能品質

### FEAT-07 — Git 歷史時間回填：舊專案衰減從零開始問題

**問題**：`brain archaeologist`（或 `brain init`）掃描舊專案的 git 歷史後，知識節點的 `created_at` 全部等於今天。原因有兩層：

#### 根因 A：`add_node()` 不接受 `created_at` 參數

`archaeologist._scan_git_history()`（`archaeologist.py:159–181`）正確地從 git log 中取得 `commit_date`：

```python
commit_date = meta.get("date", "")   # e.g. "2023-08-14 10:22:31 +0800"
```

但呼叫 `graph.add_node()` 時完全不傳這個日期：

```python
self.graph.add_node(
    node_id   = node_id,
    node_type = chunk["type"],
    title     = chunk["title"],
    content   = chunk["content"],
    source_url= commit_hash,
    # ← commit_date 完全被丟棄
)
```

`graph.add_node()` 和 `brain_db.add_node()` 的 INSERT 語句都不包含 `created_at`，全靠 SQLite `DEFAULT (datetime('now'))` 填入。

#### 根因 B：`INSERT OR REPLACE` 每次都重置 `created_at`

`brain_db.add_node()` 使用 `INSERT OR REPLACE`，這在 SQLite 中等於先 DELETE 再 INSERT。`DEFAULT` 重新觸發，即使是「更新」既有節點，`created_at` 也會被重置為現在。

**影響**：

- 掃描一個有 3 年 git 歷史的專案後，所有節點 `created_at = today`
- 衰減引擎 F1 factor = `e^(-λ × 0 days)` = **1.0** — 完全無衰減
- 7 天後才開始衰減，但 3 年前的 commit 理論上應該已衰減至 0.3–0.5
- `_effective_confidence` 不反映實際知識時效性，知識庫信心分布失真

---

#### 修復方案

**Fix-1：`graph.add_node()` 新增 `created_at` 參數**（`graph.py:232`）

```python
def add_node(self, node_id, node_type, title,
             content="", tags=None, source_url="", author="",
             meta=None, created_at: str = "") -> str:
    ...
    # INSERT 時：若未提供 created_at，用 DEFAULT；若提供，優先用提供值
    if created_at:
        self._conn.execute("""
            INSERT OR IGNORE INTO nodes (id, type, ..., created_at) VALUES (...)
        """, (..., created_at))
        self._conn.execute("UPDATE nodes SET type=?, title=?, ... WHERE id=?", (...))
    else:
        # 原有邏輯
```

更好的寫法：改用 SQLite UPSERT（`INSERT ... ON CONFLICT DO UPDATE`），保留 `created_at` 不覆蓋：

```python
self._conn.execute("""
    INSERT INTO nodes (id, type, title, content, tags,
                       source_url, author, meta, confidence, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now')))
    ON CONFLICT(id) DO UPDATE SET
        type=excluded.type,
        title=excluded.title,
        content=excluded.content,
        updated_at=datetime('now')
        -- created_at 不更新，永遠保留初始值
""", (..., created_at or None))
```

同樣修改 `brain_db.add_node()`（`brain_db.py:442`）。

**Fix-2：`archaeologist._scan_git_history()` 傳入 `commit_date`**（`archaeologist.py:170`）

```python
self.graph.add_node(
    node_id    = node_id,
    node_type  = chunk["type"],
    title      = chunk["title"],
    content    = chunk["content"],
    source_url = commit_hash,
    author     = meta.get("author", ""),
    meta       = {"confidence": chunk.get("confidence", 0.8)},
    created_at = commit_date,   # ← 新增這一行
)
```

**Fix-3：新增 `brain backfill-git` CLI 指令**

針對已建立的 DB（舊節點 `created_at` 已錯誤設為 today），提供修正指令：

```bash
brain backfill-git [--workdir DIR] [--dry-run]
```

邏輯：
1. 讀取所有 `source_url` 為 commit hash 格式（40 hex chars）的節點
2. 執行 `git show --format="%ai" <hash>` 取得該 commit 的 author date
3. `UPDATE nodes SET created_at=<commit_date>, updated_at=<commit_date> WHERE id=?`
4. 若 `source_url` 是檔案路徑，執行 `git log --follow --format="%ai" -- <file> | tail -1` 取得檔案最早 commit 日期

```python
# cli_admin.py 新增
def _cmd_backfill_git(args):
    db = BrainDB(brain_dir)
    nodes = db.conn.execute(
        "SELECT id, source_url FROM nodes WHERE created_at > date('now', '-1 day')"
    ).fetchall()
    updated = 0
    for node in nodes:
        src = node["source_url"]
        git_date = _resolve_git_date(src, workdir)
        if git_date:
            db.conn.execute(
                "UPDATE nodes SET created_at=?, updated_at=? WHERE id=?",
                (git_date, git_date, node["id"])
            )
            updated += 1
    db.conn.commit()
    print(f"回填完成：{updated}/{len(nodes)} 個節點時間戳已更新")
```

---

#### 驗收標準

```bash
brain archaeologist --workdir /my-old-project
brain backfill-git  --workdir /my-old-project --dry-run  # 預覽
brain backfill-git  --workdir /my-old-project            # 執行
brain report                                              # 衰減報告應出現非 1.0 的 F1 值
```

3 年前的 commit 的節點應顯示 `confidence ≈ 0.3–0.5`（依 `base_decay_rate` 而定），而非 0.87。

**工時**：Fix-1+2 共 2 小時；Fix-3（`brain backfill-git`）4 小時，含測試共 1 天。

---

### PERF-06 — 缺少 type+confidence 複合索引

**問題**：`search_nodes(node_type=...)` 呼叫產生：
```sql
SELECT n.* FROM nodes_fts f JOIN nodes n ON f.id=n.id WHERE n.type=? ORDER BY confidence DESC
```
目前索引：`idx_nodes_scope_conf(scope, confidence)`、`idx_nodes_pinned_conf(is_pinned, confidence)`。
**缺少**：`idx_nodes_type_conf(type, confidence DESC)`。10k 節點下 type 過濾全表掃描。

**修復**：SCHEMA_VERSION=21 migration：
```sql
ALTER TABLE nodes ... -- no new column needed
CREATE INDEX IF NOT EXISTS idx_nodes_type_conf ON nodes(type, confidence DESC)
```

**工時**：30 分鐘（純 migration）。

---

### BUG-D03 — KRB AI Assist Cache 永不 VACUUM

**問題**：`krb_ai_assist.py` 的 `ai_screen_cache.db` lazy 刪除過期行但從不執行 `VACUUM`，SQLite 檔案只增不減。

**修復**：在 `_init_db()` 末尾加條件性 VACUUM：
```python
last_vacuum = self._conn.execute(
    "SELECT value FROM meta WHERE key='last_vacuum'").fetchone()
if not last_vacuum or (datetime.now() - datetime.fromisoformat(last_vacuum[0])).days > 7:
    self._conn.execute("VACUUM")
    self._conn.execute("INSERT OR REPLACE INTO meta VALUES('last_vacuum', ?)",
                       (datetime.now().isoformat(),))
```

**工時**：2 小時。

---

### BUG-D04 — SessionStore Per-Thread 連線洩漏

**問題**：`session_store.py` 使用 `threading.local()` 儲存 SQLite 連線，執行緒結束時連線不關閉，長執行伺服器（`brain serve`）可能耗盡 FD。

**修復方案 A（最小改動）**：改用單一共享連線 + `check_same_thread=False`（WAL 模式下安全）。
**修復方案 B**：改用 `weakref.finalize()` 在執行緒 GC 時自動關閉。

**建議**：採用方案 A，與 `brain_db.py` 的模式一致。

**工時**：3 小時。

---

### ARCH-07 — 雙重 scope 推斷實作

**問題**：`cli_utils._infer_scope()` 與 `brain_db.infer_scope()` 各自維護相同的推斷邏輯（git remote → 子目錄 → workdir → global）。兩者同步修改容易遺漏。

**修復**：`cli_utils._infer_scope()` 改為：
```python
def _infer_scope(workdir: str, current_file: str = "") -> str:
    from project_brain.brain_db import BrainDB
    return BrainDB.infer_scope(workdir, current_file)
```

**工時**：1 小時 + 測試驗證。

---

### OBS-02 — Decay F1–F7 因子量測缺失

**問題**：`decay_engine._apply_decay()` 計算 7 個因子的乘積但從不記錄各因子貢獻，無法診斷「為何這個節點信心從 0.85 降到 0.21」。

**修復**：`_apply_decay()` 結尾加：
```python
db.emit("decay_run", {
    "node_id": node_id,
    "factors": {"f1_time": f1, "f2_access": f2, "f3_contra": f3,
                "f4_cross": f4, "f5_version": f5, "f6_adoption": f6, "f7_freq": f7},
    "old_conf": old_conf, "new_conf": new_conf,
})
```
`analytics_engine` 新增 `decay_factor_breakdown(node_id)` 讀取 events 表。

**工時**：1 天。

---

### OBS-03 — rollback_node() 無審計記錄

**問題**：`brain restore <node_id> --version <N>` 執行後，`node_history` 中無法知道是誰在何時還原了什麼版本，違反知識演變可追溯性（FEAT-01 目標）。

**修復**：
1. `node_history` 加 `changed_by TEXT DEFAULT 'system'`（v22 migration，可為 null）
2. `rollback_node()` 參數加 `changed_by: str = ""`，寫入 `node_history` 帶 `change_type='rollback'`

**工時**：半天。

---

### SEC-04 — Federation PII 過濾不完整

**問題**：`federation.py` `_strip_pii()` 目前過濾：email、`*.internal`、`.local` 域名。
缺失：
- IP 位址：`192.168.x.x`、`10.x.x.x`、`172.16-31.x.x`
- Slack workspace URL：`*.slack.com`
- 內部 Cloud 路徑：`s3.*/internal-bucket`
- 內部 git URL：`github.corp.com/...`

**修復**：擴充 regex 模式集（4 條新 pattern）。

**工時**：2 小時 + 測試。

---

### REV-02 — Decay 實際效用未量測

**問題**：無法驗證衰減是幫助還是傷害召回率。

**量測方案**：
1. 對比有/無衰減兩組知識庫的召回率（`tests/benchmarks/benchmark_recall.py` 已有基礎）
2. 統計 deprecated 節點在清除前的 `access_count`（零 access = 衰減正確）
3. `analytics_engine` 新增 `decay_impact_score()`

**執行條件**：需 90 天真實使用數據。目標：`brain report` 中顯示衰減效用指標。

---

## P3 — 長期 / 低頻 / 實驗性

### FEAT-05 — analytics 時序報告 / HTML 儀表板

`analytics_engine.generate_timeseries()` 方法 + `brain report --format html` 輸出 Chart.js 圖表（知識庫成長曲線、信心分布、decay 趨勢）。工時：3 天。

---

### FEAT-06 — brain doctor 矛盾 / deprecated 指標

`brain doctor` 新增：
- 矛盾節點比例（`CONFLICTS_WITH` edges 數量 / 總節點數）
- Deprecated 比例（若 > 20% 觸發 ⚠ 警告）
- Decay 未執行天數警告

工時：1 天。

---

### ARCH-08 — ConflictResolver 快取 TTL 淘汰

`conflict_resolver.py` 已有 `CACHE_SECONDS=86400` 常數，但快取永不清空（dict 只增不減）。加入 TTL 淘汰：在 `resolve()` 呼叫時清除超過 `CACHE_SECONDS` 的項目。工時：2 小時。

---

### TEST-02 — Decay Engine 100K 節點負載測試

`tests/chaos/test_decay_load.py`：建立 100K 節點，執行完整 decay 週期，量測：時間 < 60s、記憶體 < 500MB、無 SQLite lock 錯誤。工時：1 天。

---

### TEST-03 — 修復 Chaos 測試硬編碼路徑

`tests/chaos/test_chaos_and_load.py:380` 硬編碼 `/home/claude/synthex_v10/brain.py`，在任何其他環境永遠失敗。改用 `Path(__file__).parents[2] / "project_brain"` 或直接 import。工時：1 小時。

---

## 版本路線圖

| 版本 | 主題 | 主要工作 | Gate |
|------|------|---------|------|
| **v0.12.0** | 正確性修復 | SEC-03, BUG-D01, BUG-D02, BUG-E01, TEST-01, PERF-05, TEST-03 | 0 failing tests；所有 P1 修復通過；benchmark 召回率 ≥ 50%（FTS5 only） |
| **v0.13.0** | 品質強化 | FEAT-07, PERF-06, BUG-D03, BUG-D04, ARCH-07, OBS-02, OBS-03, SEC-04 | 舊專案回填後 F1 衰減正確反映 commit 時間；無 bare except/pass（高危路徑） |
| **v0.14.0** | 長期改善 | FEAT-06, ARCH-08, TEST-02, FEAT-05（視餘力） | REV-02 90天數據就位後 |
| **v0.15.0** | 量測驗收 | REV-02 decay 效用量測與報告 | `brain report` 顯示衰減效用指標 |

---

## 架構完整度（v0.11.0）

| 層 / 模組 | 完整度 | 已知缺口 |
|----------|--------|---------|
| L1a SessionStore | ✅ | BUG-D04 FD 洩漏 |
| L2 Episodes / Temporal | ✅ | — |
| L3 KnowledgeGraph | ✅ | — |
| BrainDB | ✅ SCHEMA v20 | PERF-06 缺 type+conf 索引（v21）|
| DecayEngine | ⚠️ 7/7 因子 | PERF-05 N+1；OBS-02 因子量測缺失；FEAT-07 舊專案 created_at 全為 today |
| ContextEngineer | ⚠️ | BUG-E01 `_search_batch[:8]` 截斷；BUG-D01 部分 except/pass |
| NudgeEngine | ✅ | — |
| ConflictResolver | ✅ | ARCH-08 快取無 TTL 淘汰 |
| Federation | ✅ | SEC-04 PII 過濾不完整 |
| KRB | ✅ | BUG-D03 cache.db 永不 VACUUM |
| MCP Server | ✅ | — |
| API Server | ✅ | SEC-03 timing attack |
| Embedder | ⚠️ | BUG-D02 cache 無鎖 |
| Analytics | ✅ | OBS-02 decay 因子缺失；REV-02 待量測 |
| Tests | ⚠️ | 15 failing；chaos 硬編碼路徑 |
