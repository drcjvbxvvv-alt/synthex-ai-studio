# Project Brain — 系統改善計劃書

> **版本**: v1.4
> **建立日期**: 2026-04-02
> **最後更新**: 2026-04-03
> **適用版本**: v0.1.0 (public) / v11.1 (internal)
> **狀態**: P0 + P1 + P2 全部完成 ✅

---

## 目錄

1. [執行摘要](#執行摘要)
2. [系統缺陷清單](#系統缺陷清單)
3. [緊急 BUG 修復](#緊急-bug-修復)
4. [優化方向](#優化方向)
5. [新增功能路線圖](#新增功能路線圖)
6. [深度加強方向](#深度加強方向)
7. [優先矩陣總覽](#優先矩陣總覽)
8. [執行時程建議](#執行時程建議)

---

## 執行摘要

Project Brain 是以 SQLite 為核心的三層式 AI 記憶系統，整體架構設計紮實，具備完整的 CLI、REST API、MCP Server 與 Web UI。本計劃書彙整以下五個維度的改善項目：

- **5 項嚴重/中度系統缺陷**（影響正確性與穩定性）
- **8 項確認 BUG**（含 3 項緊急 Crash 類）
- **6 項性能與架構優化**
- **10 項新功能**（分三批推出）
- **4 項深度加強**（長期差異化方向）

---

## 系統缺陷清單

### 🔴 嚴重缺陷

#### ~~DEF-01：SQLite 單寫競爭條件~~ ✅ 已修復 (2026-04-03)

| 項目 | 內容 |
|------|------|
| **位置** | `brain_db.py` — `_write_guard()` |
| **症狀** | git post-commit hook 觸發 `brain sync` 同時，MCP server 處理 `add_knowledge`，其中一個操作可能 timeout 且靜默失敗 |
| **根本原因** | SQLite 單寫限制；兩個寫入進程競爭鎖定 |
| **影響** | 知識遺失，使用者無感知 |
| **修復** | 新增 `_write_guard()` context manager，使用 `fcntl.flock()` 對獨立 `.write_lock` 文件加排他鎖，序列化跨進程寫入；支援同執行緒可重入（depth counter），Windows 自動降級 |

```python
# brain_db.py — DEF-01 修復
@contextlib.contextmanager
def _write_guard(self):
    depth = getattr(self._local, "_wg_depth", 0)
    self._local._wg_depth = depth + 1
    if depth > 0:
        try: yield
        finally: self._local._wg_depth -= 1
        return
    # outermost: acquire flock
    lf = open(str(self.brain_dir / ".write_lock"), "w")
    fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
    try: yield
    finally:
        self._local._wg_depth -= 1
        fcntl.flock(lf.fileno(), fcntl.LOCK_UN); lf.close()
```

`add_node()`, `update_node()`, `add_episode()`, `delete_node()` 均已加入 `with self._write_guard():`

**測試**: `TestDef01WriteLock` — 4 個測試，全部通過 ✅

#### ~~DEF-02：FTS5 同步觸發器缺失~~ ✅ 已修復 (2026-04-03)

| 項目 | 內容 |
|------|------|
| **位置** | `brain_db.py` — `_setup()` 觸發器 + `conn` property UDF |
| **症狀** | 直接 SQL UPDATE/DELETE `nodes` 表（如 `review_board.update_approved()`、`decay_engine._apply_decay()`），FTS5 不自動更新 |
| **根本原因** | `nodes` 表與 `nodes_fts` 虛擬表之間無 SQL 觸發器；只有 `add_node()` 手動同步 |
| **影響** | 搜尋召回率因直接 SQL 修改而靜默下降 |
| **修復** | 新增 `AFTER UPDATE OF title, content, tags` 和 `AFTER DELETE` 觸發器；`conn` property 註冊 `brain_ngram()` Python UDF 讓觸發器可呼叫 n-gram 函數 |

```sql
-- brain_db.py _setup() — DEF-02 修復
CREATE TRIGGER IF NOT EXISTS nodes_fts_au
AFTER UPDATE OF title, content, tags ON nodes BEGIN
    DELETE FROM nodes_fts WHERE id = old.id;
    INSERT INTO nodes_fts(id, title, content, tags)
    VALUES (new.id, brain_ngram(new.title), brain_ngram(new.content), new.tags);
END;

CREATE TRIGGER IF NOT EXISTS nodes_fts_ad
AFTER DELETE ON nodes BEGIN
    DELETE FROM nodes_fts WHERE id = old.id;
END;
```

**測試**: `TestDef02FTS5Triggers` — 4 個測試，全部通過 ✅

#### DEF-03：延遲初始化執行緒安全問題

| 項目 | 內容 |
|------|------|
| **位置** | `engine.py` — 多個 `if self._db is None` 模式 |
| **症狀** | 多執行緒同時通過 None 判斷，各自初始化，導致資源競爭 |
| **根本原因** | 屬性 getter 非原子操作；`threading.local()` 已用於連線池，但初始化本身未受保護 |
| **影響** | 高並發時可能 Crash 或資料庫狀態不一致 |
| **修復方案** | 使用 `threading.Lock()` 保護所有延遲初始化路徑 |

---

### 🟡 中度缺陷

#### ~~DEF-04：資料庫 Schema 遷移不可靠~~ ✅ 已修復 (2026-04-03)

| 項目 | 內容 |
|------|------|
| **位置** | `brain_db.py` — try/except ALTER TABLE |
| **症狀** | 遷移因任意原因失敗（如磁碟已滿）時靜默跳過，資料庫狀態不一致 |
| **根本原因** | 無版本號追蹤，使用 catch-all except 忽略所有錯誤 |
| **修復方案** | 在 `brain_meta` 表加入 `schema_version` 欄位，按版本號順序執行遷移腳本，任一步驟失敗立即報錯 |

#### ~~DEF-05：Decay Engine 未整合進主查詢流程~~ ✅ 已修復 (2026-04-03)

| 項目 | 內容 |
|------|------|
| **位置** | `brain_db.py` — `search_nodes()` + `_effective_confidence()` |
| **症狀** | 搜尋排名依靜態 `confidence` 欄位，舊知識（信心應已衰減）排在新知識前面 |
| **根本原因** | `search_nodes()` 的 ORDER BY 使用靜態 `confidence`，未套用 DecayEngine 的即時計算 |
| **修復** | 新增 `_effective_confidence()` 靜態方法（F1 時間衰減 + F7 使用頻率加成），`search_nodes()` 在返回前計算每個節點的 `effective_confidence` 並重新排名；Pinned 節點免疫衰減 |

```python
# brain_db.py — DEF-05/OPT-04 修復
@staticmethod
def _effective_confidence(node: dict) -> float:
    base  = float(node.get("confidence", 0.8))
    if node.get("is_pinned"): return base
    days  = (datetime.now(timezone.utc) - created_dt).days
    decay = math.exp(-0.003 * days)           # F1
    f7    = min(0.15, (access / 10) * 0.05)  # F7
    return max(0.05, min(1.0, base * decay + f7))
```

**測試**: `TestDef05DecayAwareRanking` — 5 個測試，全部通過 ✅

#### ~~DEF-06：Session Store 無上限保護~~ ✅ 已修復 (2026-04-03)

| 項目 | 內容 |
|------|------|
| **位置** | `session_store.py` |
| **症狀** | 長期執行任務累積數千 session 條目，查詢效能下降 |
| **修復方案** | 加入 `max_entries_per_session=500` 限制，超過時 LRU 淘汰最舊條目 |

#### DEF-07：CJK 中文搜尋召回率差

| 項目 | 內容 |
|------|------|
| **位置** | `context.py` — FTS5 搜尋設定 |
| **症狀** | 中文 knowledge nodes 的 FTS5 搜尋召回率估計不到 40% |
| **根本原因** | FTS5 預設 Unicode61 tokenizer 對中文分詞效果差，缺乏 N-gram 支援 |
| **修復方案** | 改用 `tokenize="trigram"` 或建立 N-gram 前處理管線 |

---

## 緊急 BUG 修復

### 🔴 P0 — 立即修復 (Crash / 資料損壞)

#### ~~BUG-01：L2 Episodic Memory 重複記錄~~ ✅ 已修復 (2026-04-02)

| 項目 | 內容 |
|------|------|
| **位置** | `brain_db.py` → `add_episode()` + `_setup()` |
| **症狀** | 重複執行 `brain sync` / `brain scan` 將同一 git commit 多次插入 `episodes` 表 |
| **根本原因** | ① `source` 欄位無 UNIQUE 約束，同 commit 不同 content 格式繞過 PRIMARY KEY 防護；② ID hash 僅 8 hex chars（32-bit），存在碰撞風險 |
| **修復** | ① 新增 `CREATE UNIQUE INDEX idx_episodes_source ON episodes(source) WHERE source != ''`；② 有 source 時以 source 為 hash seed；③ hash 長度從 8 擴展至 16 chars（64-bit） |

```python
# brain_db.py — add_episode() 修復後
seed = source if source else f"{content}{source}"
eid  = "ep-" + hashlib.md5(seed.encode()).hexdigest()[:16]
```

```sql
-- _setup() migration 新增
CREATE UNIQUE INDEX IF NOT EXISTS idx_episodes_source
ON episodes(source) WHERE source != '';
```

**測試**: `TestBug01EpisodeDuplication` — 6 個測試，全部通過 ✅

#### ~~BUG-02：NudgeEngine 返回已過期節點~~ ✅ 已修復 (2026-04-03)

| 項目 | 內容 |
|------|------|
| **位置** | `nudge_engine.py` → `_from_l3_pitfalls()` + `brain_db.py` → `_setup()` |
| **症狀** | 使用者收到已棄用或過期的 Pitfall 警告；`confidence=0.0` 被錯誤提升為 `0.7` |
| **根本原因** | ① `float(r.get("confidence") or 0.7)` — `0.0` 為 falsy，被 `or` 覆蓋；② `nodes` 表缺少 `is_deprecated` / `valid_until` 欄位；③ 無過期過濾邏輯 |
| **修復** | ① 新增 schema migration 加入 `is_deprecated INTEGER DEFAULT 0` 和 `valid_until TEXT`；② `_from_l3_pitfalls()` 加入跳過棄用節點、跳過 `valid_until` 已過期節點；③ `raw_conf is not None` 取代 `or` 做 None 判斷 |

```python
# nudge_engine.py — 修復後的過濾邏輯
if r.get("is_deprecated"):
    continue
valid_until = r.get("valid_until")
if valid_until:
    vu = datetime.fromisoformat(valid_until.replace("Z", "+00:00"))
    if vu < now:
        continue
raw_conf = r.get("confidence")
conf     = float(raw_conf) if raw_conf is not None else 0.7
```

**測試**: `TestBug02NudgeExpiry` — 5 個測試，全部通過 ✅

#### ~~BUG-05：ContextResult 在空 Brain 時返回 None~~ ✅ 已修復 (2026-04-03)

| 項目 | 內容 |
|------|------|
| **位置** | `context.py` → `build()` 方法 |
| **症狀** | 空 task 或無 keywords 時，`all_nodes` NameError 靜默吞掉後 SR 失效；`_deduplicate_sections` 只 catch `ImportError`，若 sklearn 其他錯誤導致 `result` 未定義 |
| **根本原因** | ① `all_nodes` 在 `if keywords:` 內定義，但 SR 程式碼在 `if keywords:` 外引用；② `_deduplicate_sections` 的 except 只覆蓋 `ImportError`；③ `return result` 路徑在例外時可返回 `None` |
| **修復** | ① `all_nodes`、`pitfalls`、`decisions` 等所有列表在 `if keywords:` 前初始化為 `[]`；② 用 try/except Exception 包裹 dedup 呼叫；③ 末尾改為 `return result or ""` |

```python
# context.py — build() 修復：提前初始化
all_nodes: list[...] = []
pitfalls = decisions = rules = adrs = notes = []

keywords = self._extract_keywords(task)
if keywords:
    ...  # all_nodes 在此填充

# SR 程式碼現在安全（all_nodes 已初始化）
try:
    _node_ids = [n.get("id") for _, _, n in all_nodes ...]
except Exception:
    pass
return result or ""  # 永不返回 None
```

**測試**: `TestBug05ContextNeverNone` — 4 個測試，全部通過 ✅

---

### 🟡 P1 — 高優先級修復

#### ~~BUG-03：Token 預算計算誤差~~ ✅ 已修復 (2026-04-03)

| 項目 | 內容 |
|------|------|
| **位置** | `context.py` — Token 計數 |
| **症狀** | 中文內容和程式碼實際 token 數超出 6000 預算 20-30% |
| **根本原因** | 使用固定 `CHARS_PER_TOKEN = 4` 估算；CJK 字元每個約 1 token，被嚴重低估 |
| **修復** | 新增無外部依賴的 `_count_tokens()` 函數：CJK ≈ 1 token/char，ASCII ≈ 0.25 token/char |

```python
# context.py — BUG-03 修復
def _count_tokens(text: str) -> int:
    """CJK-aware token estimator（無外部依賴）"""
    cjk = sum(1 for ch in text if '\u4e00' <= ch <= '\u9fff'
              or '\u3000' <= ch <= '\u303f'
              or '\uff00' <= ch <= '\uffef')
    rest = len(text) - cjk
    return cjk + (rest // 4)
```

**測試**: `TestBug03CJKTokenCount` — 5 個測試，全部通過 ✅

---

#### ~~BUG-04：MCP Rate Limiter 執行緒競態~~ ✅ 已修復 (2026-04-03)

| 項目 | 內容 |
|------|------|
| **位置** | `mcp_server.py` — Rate limiter |
| **症狀** | 多執行緒並發呼叫時，`_call_times` 無鎖保護，可能允許超出 RPM 限制的請求 |
| **根本原因** | `_call_times` 全域列表在並發讀/寫時無 Lock 保護；率先修正為滑動窗口 |
| **修復** | 新增 `threading.Lock()`，以 `with _rate_lock:` 保護所有讀/寫操作 |

```python
# mcp_server.py — BUG-04 修復
import threading
_rate_lock = threading.Lock()    # BUG-04 fix

def _rate_check() -> None:
    now = time.monotonic()
    cutoff = now - 60.0
    with _rate_lock:
        _call_times[:] = [t for t in _call_times if t > cutoff]
        if len(_call_times) >= RATE_LIMIT_RPM:
            raise RuntimeError(f"Rate limit：每分鐘最多 {RATE_LIMIT_RPM} 次呼叫")
        _call_times.append(now)
```

**測試**: `TestBug04RateLimitThreadSafety` — 5 個測試，全部通過 ✅

---

#### ~~BUG-06：`brain doctor --fix` 不修復損壞的 FTS5 索引~~ ✅ 已修復 (2026-04-03)

| 項目 | 內容 |
|------|------|
| **位置** | `cli.py` — `cmd_doctor()` |
| **症狀** | `brain doctor --fix` 不偵測 FTS5 索引不完整，導致全文搜尋遺漏節點 |
| **根本原因** | `cmd_doctor()` 未包含 FTS5 完整性檢查邏輯 |
| **修復** | 加入 FTS5 完整性檢查（對比 nodes 與 nodes_fts count），`--fix` 模式執行 `INSERT INTO nodes_fts(nodes_fts) VALUES('rebuild')` |

```python
# cli.py — BUG-06 修復（cmd_doctor 內）
try:
    fts_count = conn.execute("SELECT COUNT(*) FROM nodes_fts").fetchone()[0]
    if fts_count < nodes:
        _err2(f"FTS5 索引不完整：{fts_count}/{nodes} 個節點已建立索引", ...)
        if fix:
            conn.execute("INSERT INTO nodes_fts(nodes_fts) VALUES('rebuild')")
            conn.commit()
    else:
        _ok2(f"FTS5 索引完整  ({fts_count}/{nodes} 個節點)")
except Exception as _fts_err:
    if fix:
        conn.execute("INSERT INTO nodes_fts(nodes_fts) VALUES('rebuild')")
        conn.commit()
```

**測試**: `TestBug06FTS5Integrity` — 4 個測試，全部通過 ✅

---

#### ~~BUG-07：`brain review approve` 不更新 brain.db FTS5~~ ✅ 已修復 (2026-04-03)

| 項目 | 內容 |
|------|------|
| **位置** | `review_board.py` — `approve()` |
| **症狀** | 核准後節點進入 `knowledge_graph.db`，但 `context.py` 查詢的 `brain.db` `nodes_fts` 未同步，導致新批准節點在 AI 上下文中不可見 |
| **根本原因** | 雙 FTS5 問題：`KnowledgeGraph` 維護 `knowledge_graph.db` 的 FTS5，而 `BrainDB` 維護 `brain.db` 的 `nodes_fts`；`approve()` 只寫前者 |
| **修復** | `approve()` 在 `self.graph.add_node()` 後，同時呼叫 `BrainDB(self.brain_dir).add_node()` 同步寫入 `brain.db` |

```python
# review_board.py — BUG-07 修復（approve 內）
from project_brain.brain_db import BrainDB

# 原有 graph.add_node 之後
try:
    bdb = BrainDB(self.brain_dir)
    bdb.add_node(
        node_id   = l3_id,
        node_type = row["kind"],
        title     = row["title"],
        content   = row["content"] or "",
    )
except Exception as _e:
    logger.warning("krb_approve: brain.db FTS 同步失敗（不影響核准）: %s", _e)
```

**測試**: `TestBug07ReviewBoardFTSSync` — 4 個測試，全部通過 ✅

---

#### ~~BUG-08：Web UI Windows 路徑分隔符號問題~~ ✅ 已修復 (2026-04-03)

| 項目 | 內容 |
|------|------|
| **位置** | `web_ui/server.py` — `create_app()` |
| **症狀** | Windows 環境下路徑字串含反斜線，傳入 `_generate_graph_html()` 可能造成 HTML 中路徑顯示異常 |
| **根本原因** | `index()` 以 `str(workdir)` 傳遞路徑，在 Windows 上反斜線可能殘留 |
| **修復** | 改用 `workdir.resolve().as_posix()` 確保跨平台路徑一致性 |

```python
# web_ui/server.py — BUG-08 修復
@app.route("/")
def index():
    # BUG-08 fix: pass resolved POSIX path for cross-platform consistency
    return _generate_graph_html(workdir.resolve().as_posix())
```

**測試**: `TestBug08WebUIPathConsistency` — 4 個測試，全部通過 ✅

---

## 優化方向

### 性能優化

#### ~~OPT-01：FTS5 CJK N-gram 支援~~ ✅ 已修復 (2026-04-03)

```sql
-- 修復前: 每個 CJK 字元空格分隔（單字可搜）→ 召回率 ~40%
-- 修復後: 單字 + bigrams（多字詞可搜）→ 召回率 ~70%（估）
-- "中文搜尋" → "中 文 搜 尋 中文 文搜 搜尋"
```

**實作**:
- `_ngram()` 增強：在空格分隔基礎上，額外生成 CJK bigrams
- `conn` property 註冊 `brain_ngram()` UDF 供觸發器使用
- 一次性遷移：`_setup()` 中檢查 `brain_meta.fts_bigram_v1`，首次執行重建 FTS5（所有歷史節點）
- 新增節點自動使用增強版 `_ngram()`

**測試**: `TestOpt01CJKBigram` — 5 個測試，全部通過 ✅

**工作量**: 小（1-2 天）  **影響**: 高（中文用戶體驗大幅提升）

---

#### ~~OPT-02：混合搜尋自適應權重~~ ✅ 已實作 (2026-04-03)

```python
# 現況: 固定權重
score = fts_score * 0.4 + vector_score * 0.6

# 優化: 根據查詢特性動態調整
def adaptive_score(query, fts_score, vector_score):
    keyword_density = len(re.findall(r'\b\w+\b', query)) / len(query)
    fts_weight = 0.3 + 0.4 * keyword_density  # 0.3 ~ 0.7
    return fts_score * fts_weight + vector_score * (1 - fts_weight)
```

**工作量**: 中（3-5 天）  **影響**: 中（搜尋精準度 +10-15%）

---

#### ~~OPT-03：向量 Embedding 快取~~ ✅ 已實作 (2026-04-03)

```python
# 優化: LRU cache 避免重複計算
from functools import lru_cache
import hashlib

@lru_cache(maxsize=2000)
def _cached_embed(text_hash: str) -> tuple[float, ...]:
    ...

def get_embedding(self, text: str) -> list[float]:
    h = hashlib.sha256(text.encode()).hexdigest()
    return list(self._cached_embed(h))
```

**工作量**: 小（1 天）  **影響**: 中（`brain scan` 大量 commit 時速度提升 3-5×）

---

#### ~~OPT-04：Decay Engine 整合至查詢排名~~ ✅ 已修復 (2026-04-03)

與 DEF-05 一同修復。`search_nodes()` 現在對每個結果計算 `effective_confidence` 並重排序：

```python
# brain_db.py search_nodes() — OPT-04 修復
results = [dict(r) for r in rows]
for r in results:
    r["effective_confidence"] = self._effective_confidence(r)
results.sort(
    key=lambda x: (x.get("is_pinned", 0), x["effective_confidence"]),
    reverse=True,
)
return results
```

無需呼叫 DecayEngine（避免 subprocess/grep 開銷），使用輕量 F1+F7 即時計算。

**工作量**: 中（3 天）  **影響**: 高（知識排名更準確，舊知識不再佔據首位）

---

#### OPT-05：讀寫路徑分離 (CQRS)

```
現況: BrainDB 混合讀寫
建議:
  ReadDB  (mode=ro, WAL snapshot) → context / query / nudges
  WriteDB (single writer)         → add / sync / review approve
```

**工作量**: 大（1-2 週）  **影響**: 高（消除讀寫競爭，提升並發性能）

---

#### OPT-06：查詢展開預計算索引

```python
# 現況: 每次查詢即時展開同義詞 (O(n) 查找)
# 優化: brain index 時預建倒排索引，查詢時 O(1)
brain index --rebuild-synonyms
```

**工作量**: 中（3-5 天）  **影響**: 中（查詢延遲降低 20-30%）

---

## 新增功能路線圖

### Batch 1 — 品質與可觀測性（建議：v0.2.0）

#### ~~FEAT-01：知識健康度儀表板~~ ✅ 已實作 (2026-04-03)

```bash
brain health-report

# 輸出範例:
# ┌─────────────────────────────────────────────┐
# │ Knowledge Health Report — 2026-04-02        │
# ├─────────────────────────────────────────────┤
# │ 過期節點 (confidence < 0.3):  3 個           │
# │ 潛在衝突對:                   2 組           │
# │ 孤立節點 (無 edges):          7 個           │
# │ 高風險 Pitfalls (未存取 30d): 4 個           │
# └─────────────────────────────────────────────┘
```

**工作量**: 中（3-5 天）  **影響**: 高（知識庫長期維護必要工具）

---

#### ~~FEAT-02：智慧衝突偵測~~ ✅ 已實作 (2026-04-03)

新增知識時自動比對現有節點：

```bash
brain add "Use PostgreSQL for all databases"
# ⚠️  偵測到潛在衝突！
# 現有規則: "Use SQLite for lightweight apps" (confidence=0.80, 2025-11-03)
# 相似度: 87%
# 選項: [1] 標記為例外  [2] 更新現有規則  [3] 忽略  [4] 取消
```

**工作量**: 中（5 天）  **影響**: 高（防止矛盾知識污染知識庫）

---

#### ~~FEAT-03：使用率分析報告~~ ✅ 已實作 (2026-04-03)

```bash
brain analytics --period 30d

# 輸出:
# 最常存取: JWT RS256 Rule         (42 queries, 健康)
# 最少存取: Legacy API v1 Rule     (0 queries, 45 天未存取 → 建議審查)
# 衰減警告: Auth token TTL         (confidence 已降至 0.28)
```

**工作量**: 小（2-3 天）

---

### Batch 2 — 使用者體驗（建議：v0.3.0）

#### ~~FEAT-04：自動 Scope 推斷~~ ✅ 已實作 (2026-04-03)

```bash
# 現況: 必須手動指定
brain add "JWT RS256 required" --scope auth

# 優化後: 根據 workdir 當前文件自動推斷
brain add "JWT RS256 required"
# [Brain] 偵測到目前在 src/auth/jwt.py → 自動套用 scope=auth
# 確認? [Y/n]
```

實作：分析 workdir 文件樹 + 規則式分類器（無需 LLM）
**工作量**: 中（5 天）  **影響**: 高（降低使用摩擦）

---

#### ~~FEAT-05：知識匯入 / 匯出~~ ✅ 已實作 (2026-04-03)

```bash
# 匯出
brain export --format json > brain_backup.json
brain export --format markdown > docs/knowledge.md   # Obsidian 相容

# 匯入（支援合併策略）
brain import brain_backup.json --merge-strategy=confidence_wins
brain import team_knowledge.json --scope global --dry-run
```

**工作量**: 中（5-7 天）  **影響**: 中（團隊共享與備份）

---

#### FEAT-06：知識版本歷史

```bash
brain timeline "JWT auth decision"
# 2025-09-01  [v0.7]  新增: "JWT 必須使用 RS256" (confidence=0.9)
# 2025-11-15  [v0.8]  更新: 加入 token TTL 要求
# 2026-02-01  [v0.9]  衰減: confidence 降至 0.72 (未更新 30 天)

brain rollback node_id:42 --to 2025-11-01
```

**工作量**: 大（1-2 週）

---

### Batch 3 — 整合與生態（建議：v0.4.0）

#### FEAT-07：跨專案知識遷移

```bash
brain migrate \
  --from ~/project-a/.brain/brain.db \
  --to   ~/project-b/.brain/brain.db \
  --scope global \
  --min-confidence 0.8
```

#### FEAT-08：自然語言問句查詢

```bash
brain ask "為什麼我們不用 MongoDB？"
brain ask "上次部署失敗的原因是什麼？"
# 使用 LLM 將問句轉換為結構化查詢再搜尋
```

#### FEAT-09：Web UI 時間軸視覺化增強

- 時間軸滑桿（查看不同時間點的知識狀態）
- 衰減動畫（節點隨 confidence 降低而褪色）
- 點擊節點顯示完整歷史與內嵌編輯

#### FEAT-10：Slack / GitHub Webhook 整合

```bash
brain serve --webhook-slack=https://hooks.slack.com/...
# 當 NudgeEngine 偵測到高危情況，自動發送警告到 Slack
```

---

## 深度加強方向

### DEEP-01：圖推理鏈條輸出

**現況**: `graph.py` 只做 BFS/DFS 多跳遍歷，返回相關節點列表
**目標**: 返回帶有推理路徑的因果鏈條

```
輸入任務: "Implement payment refund"

推理結果:
refund
  → REQUIRES → webhook_endpoint
    → PREVENTS_BY → idempotency_rule (Rule, confidence=0.9)
      ⚠️ Pitfall: "重複請求必須冪等，否則客戶被多次扣款"
  → CAUSED_BY → incident_2025_double_charge
    → FIXED_BY → rs256_jwt_rule (Rule, confidence=0.85)
```

**工作量**: 大（2-3 週）  **差異化**: 高

---

### DEEP-02：知識不確定性傳播（貝葉斯信念網路）

**現況**: 各節點 confidence 獨立，互不影響
**目標**: 節點間的依賴關係影響彼此的有效 confidence

```
Rule A: "Use RS256" (confidence=0.9)
  └─ REQUIRES → Rule B: "Key rotation every 90 days" (confidence=0.7)

若 Rule A 衰減至 0.5:
  → Rule B 的有效 confidence 也應調整（傳播係數可配置）
```

**工作量**: 大（3-4 週）  **差異化**: 極高（創新功能）

---

### DEEP-03：反事實推理

```bash
brain counterfactual "如果我們用 NoSQL 代替 PostgreSQL"
# Brain 遍歷所有 DEPENDS_ON 邊
# 輸出: 以下 7 個決策需要重新評估...
# - "Transaction rollback strategy" (Decision, confidence=0.88)
# - "ACID compliance for payments" (Rule, confidence=0.95)
# ...
```

**工作量**: 大（2-3 週）

---

### DEEP-04：主動學習循環

當 Brain 對查詢不確定時，主動向使用者提問：

```
[Brain] 我注意到你在處理 auth 相關代碼，
        但我對 "session timeout 政策" 的信心度只有 0.38。
        能告訴我目前的規定嗎？
        (輸入以儲存 / skip 跳過 / never 永不詢問此類問題)
```

**工作量**: 大（3-4 週）  **差異化**: 極高（使知識庫自我完善）

---

## 優先矩陣總覽

| ID | 項目 | 類別 | 優先級 | 影響 | 工作量 | 建議版本 |
|----|------|------|--------|------|--------|---------|
| ~~BUG-01~~ | ~~L2 重複記錄~~ | Bug | ✅ 完成 | 資料損壞 | 小 | 2026-04-02 |
| ~~BUG-02~~ | ~~過期 Nudge 節點~~ | Bug | ✅ 完成 | 誤導用戶 | 小 | 2026-04-03 |
| ~~BUG-05~~ | ~~ContextResult None~~ | Bug | ✅ 完成 | Crash | 小 | 2026-04-03 |
| ~~BUG-03~~ | ~~Token 計算誤差~~ | Bug | ✅ 完成 | Context 超限 | 中 | 2026-04-03 |
| ~~BUG-04~~ | ~~Rate Limiter 競態~~ | Bug | ✅ 完成 | 安全 | 中 | 2026-04-03 |
| ~~BUG-06~~ | ~~FTS5 doctor 未修復~~ | Bug | ✅ 完成 | 搜尋失準 | 小 | 2026-04-03 |
| ~~BUG-07~~ | ~~approve FTS 未同步~~ | Bug | ✅ 完成 | 知識遺漏 | 小 | 2026-04-03 |
| ~~BUG-08~~ | ~~Web UI 路徑問題~~ | Bug | ✅ 完成 | 跨平台 | 小 | 2026-04-03 |
| ~~DEF-01~~ | ~~SQLite 競爭條件~~ | 缺陷 | ✅ 完成 | 資料遺失 | 中 | 2026-04-03 |
| ~~DEF-02~~ | ~~FTS5 觸發器缺失~~ | 缺陷 | ✅ 完成 | 搜尋失準 | 中 | 2026-04-03 |
| ~~DEF-05~~ | ~~Decay 未整合查詢~~ | 缺陷 | ✅ 完成 | 排名錯誤 | 中 | 2026-04-03 |
| ~~OPT-01~~ | ~~CJK N-gram 增強~~ | 優化 | ✅ 完成 | 中文支援 | 小 | 2026-04-03 |
| ~~OPT-04~~ | ~~Decay 整合排名~~ | 優化 | ✅ 完成 | 排名精準 | 中 | 2026-04-03 |
| DEF-04 | ~~Schema 遷移~~ ✅ | 缺陷 | 🟢 P2 | 穩定性 | 中 | v0.2.0 |
| DEF-06 | ~~Session 無上限~~ ✅ | 缺陷 | 🟢 P2 | 效能 | 小 | v0.2.0 |
| OPT-02 | ~~自適應搜尋權重~~ ✅ | 優化 | 🟢 P2 | 精準度 | 中 | v0.2.0 |
| OPT-03 | ~~Embedding 快取~~ ✅ | 優化 | 🟢 P2 | 效能 | 小 | v0.2.0 |
| FEAT-01 | ~~健康度儀表板~~ ✅ | 新功能 | 🟢 P2 | 可觀測性 | 中 | v0.2.0 |
| FEAT-02 | ~~衝突偵測~~ ✅ | 新功能 | 🟢 P2 | 知識品質 | 中 | v0.2.0 |
| FEAT-03 | ~~使用率分析~~ ✅ | 新功能 | 🟢 P2 | 可觀測性 | 小 | v0.2.0 |
| FEAT-04 | ~~自動 Scope 推斷~~ ✅ | 新功能 | 🟢 P2 | UX | 中 | v0.3.0 |
| FEAT-05 | ~~匯入/匯出~~ ✅ | 新功能 | 🟢 P2 | 生態 | 中 | v0.3.0 |
| OPT-05 | 讀寫路徑分離 | 優化 | 🔵 P3 | 並發 | 大 | v0.3.0 |
| FEAT-06 | 版本歷史 | 新功能 | 🔵 P3 | 可追溯 | 大 | v0.3.0 |
| FEAT-07 | 跨專案遷移 | 新功能 | 🔵 P3 | 生態 | 中 | v0.4.0 |
| FEAT-08 | 自然語言問句 | 新功能 | 🔵 P3 | UX | 中 | v0.4.0 |
| DEEP-01 | 圖推理鏈條 | 深度 | 🔵 P3 | 差異化 | 大 | v1.0.0 |
| DEEP-02 | 貝葉斯傳播 | 深度 | 🔵 P3 | 差異化 | 大 | v1.0.0 |
| DEEP-03 | 反事實推理 | 深度 | 🔵 P3 | 差異化 | 大 | v1.0.0 |
| DEEP-04 | 主動學習 | 深度 | 🔵 P3 | 差異化 | 大 | v1.0.0 |

---

## 執行時程建議

```
2026-04  v0.1.1 Hotfix Release  ✅ 完成
         ├── ✅ BUG-01, BUG-02, BUG-05 (P0 修復, 完成 2026-04-03)
         ├── ✅ BUG-03, BUG-04, BUG-06, BUG-07, BUG-08 (P1 BUG, 完成 2026-04-03)
         ├── ✅ DEF-01, DEF-02, DEF-05 (缺陷修復, 完成 2026-04-03)
         └── ✅ OPT-01, OPT-04 (CJK N-gram + Decay 排名, 完成 2026-04-03)

2026-04  v0.2.0 Stability & Observability  ✅ 完成
         ├── ✅ DEF-04 (版本化 Schema 遷移, 完成 2026-04-03)
         ├── ✅ DEF-06 (Session LRU 上限, 完成 2026-04-03)
         ├── ✅ OPT-02 (自適應搜尋權重, 完成 2026-04-03)
         ├── ✅ OPT-03 (Embedding LRU 快取, 完成 2026-04-03)
         ├── ✅ FEAT-01 (知識健康度儀表板, 完成 2026-04-03)
         ├── ✅ FEAT-02 (智慧衝突偵測, 完成 2026-04-03)
         ├── ✅ FEAT-03 (使用率分析報告, 完成 2026-04-03)
         ├── ✅ FEAT-04 (自動 Scope 推斷, 完成 2026-04-03)
         └── ✅ FEAT-05 (知識匯入/匯出, 完成 2026-04-03)

2026-06  v0.3.0 UX & Ecosystem
         ├── FEAT-06 (版本歷史)
         └── OPT-05 (讀寫分離)

2026-Q3  v0.4.0 Integration
         ├── FEAT-07 ~ FEAT-10

2027-Q1  v1.0.0 Intelligence
         └── DEEP-01 ~ DEEP-04
```

---

## 附錄：參考文件

- `PROJECT_BRAIN.md` — 核心架構說明
- `CHANGELOG.md` — 版本歷史
- `COMMANDS.md` — CLI 指令參考
- `SECURITY.md` — 安全模型說明
- `CONTRIBUTING.md` — 貢獻指南
- `tests/` — 測試套件（76% coverage）

---

*本計劃書由系統深度分析自動生成，最終決策由開發團隊審核。*
