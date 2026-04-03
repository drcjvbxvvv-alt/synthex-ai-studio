# Project Brain — 已完成改善歷史

> **文件版本**: v1.0
> **建立日期**: 2026-04-03
> **說明**: 本文件歸檔所有已完成的改善項目，供未來參考。
>          現行待辦事項請見 `IMPROVEMENT_PLAN.md`。

---

## 目錄

1. [v0.1.1 Hotfix Release — 2026-04-03](#v011-hotfix-release)
2. [v0.2.0 Stability & Observability — 2026-04-03](#v020-stability--observability)
3. [v0.3.0 UX & Ecosystem — 2026-04-03](#v030-ux--ecosystem)
4. [v1.0.0 Intelligence — 2026-04-03](#v100-intelligence)

---

## v0.1.1 Hotfix Release

> **完成日期**: 2026-04-03 | **包含**: P0 Crash 修復、P1 BUG 修復、關鍵缺陷修復

---

### 系統缺陷修復

#### DEF-01：SQLite 單寫競爭條件 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `brain_db.py` — `_write_guard()` |
| **症狀** | git post-commit hook 與 MCP server 並發寫入，競爭 SQLite 鎖，靜默失敗 |
| **根本原因** | SQLite 單寫限制；兩個進程競爭鎖定 |
| **影響** | 知識遺失，使用者無感知 |
| **修復** | 新增 `_write_guard()` context manager，使用 `fcntl.flock()` 排他鎖序列化跨進程寫入；同執行緒可重入（depth counter），Windows 自動降級 |

```python
@contextlib.contextmanager
def _write_guard(self):
    depth = getattr(self._local, "_wg_depth", 0)
    self._local._wg_depth = depth + 1
    if depth > 0:
        try: yield
        finally: self._local._wg_depth -= 1
        return
    lf = open(str(self.brain_dir / ".write_lock"), "w")
    fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
    try: yield
    finally:
        self._local._wg_depth -= 1
        fcntl.flock(lf.fileno(), fcntl.LOCK_UN); lf.close()
```

**測試**: `TestDef01WriteLock` — 4 個測試 ✅

---

#### DEF-02：FTS5 同步觸發器缺失 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `brain_db.py` — `_setup()` 觸發器 + `conn` property UDF |
| **症狀** | 直接 SQL UPDATE/DELETE `nodes` 表時，FTS5 不自動更新 |
| **根本原因** | `nodes` 表與 `nodes_fts` 虛擬表之間無 SQL 觸發器 |
| **修復** | 新增 `AFTER UPDATE OF title, content, tags` 和 `AFTER DELETE` 觸發器；`conn` property 註冊 `brain_ngram()` Python UDF |

```sql
CREATE TRIGGER IF NOT EXISTS nodes_fts_au
AFTER UPDATE OF title, content, tags ON nodes BEGIN
    DELETE FROM nodes_fts WHERE id = old.id;
    INSERT INTO nodes_fts(id, title, content, tags)
    VALUES (new.id, brain_ngram(new.title), brain_ngram(new.content), new.tags);
END;
```

**測試**: `TestDef02FTS5Triggers` — 4 個測試 ✅

---

#### DEF-04：資料庫 Schema 遷移不可靠 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `brain_db.py` — `_run_migrations()` |
| **修復** | `brain_meta` 表加入 `schema_version` 欄位，按版本號順序執行遷移腳本，失敗立即報錯 |

---

#### DEF-05：Decay Engine 未整合進主查詢流程 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `brain_db.py` — `search_nodes()` + `_effective_confidence()` |
| **修復** | 新增 `_effective_confidence()` 靜態方法（F1 時間衰減 + F7 使用頻率加成），`search_nodes()` 重新排名 |

```python
@staticmethod
def _effective_confidence(node: dict) -> float:
    base  = float(node.get("confidence", 0.8))
    if node.get("is_pinned"): return base
    days  = (datetime.now(timezone.utc) - created_dt).days
    decay = math.exp(-0.003 * days)
    f7    = min(0.15, (access / 10) * 0.05)
    return max(0.05, min(1.0, base * decay + f7))
```

**測試**: `TestDef05DecayAwareRanking` — 5 個測試 ✅

---

#### DEF-06：Session Store 無上限保護 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `session_store.py` |
| **修復** | 加入 `max_entries_per_session=500` 限制，超過時 LRU 淘汰最舊條目 |

---

### BUG 修復

#### BUG-01：L2 Episodic Memory 重複記錄 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `brain_db.py` → `add_episode()` + `_setup()` |
| **修復** | 新增 `UNIQUE INDEX` on episodes.source；hash 從 8 → 16 chars |

**測試**: `TestBug01EpisodeDuplication` — 6 個測試 ✅

---

#### BUG-02：NudgeEngine 返回已過期節點 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `nudge_engine.py` → `_from_l3_pitfalls()` |
| **修復** | 加入 `is_deprecated` / `valid_until` 欄位；過期/棄用節點過濾邏輯；`raw_conf is not None` 替換 falsy `or` |

**測試**: `TestBug02NudgeExpiry` — 5 個測試 ✅

---

#### BUG-03：Token 預算計算誤差 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `context.py` — Token 計數 |
| **修復** | 新增 `_count_tokens()`：CJK ≈ 1 token/char，ASCII ≈ 0.25 token/char |

**測試**: `TestBug03CJKTokenCount` — 5 個測試 ✅

---

#### BUG-04：MCP Rate Limiter 執行緒競態 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `mcp_server.py` — Rate limiter |
| **修復** | 新增 `threading.Lock()`，以 `with _rate_lock:` 保護所有讀/寫 |

**測試**: `TestBug04RateLimitThreadSafety` — 5 個測試 ✅

---

#### BUG-05：ContextResult 在空 Brain 時返回 None ✅

| 項目 | 內容 |
|------|------|
| **位置** | `context.py` → `build()` |
| **修復** | 所有列表在 `if keywords:` 前初始化為 `[]`；末尾改為 `return result or ""` |

**測試**: `TestBug05ContextNeverNone` — 4 個測試 ✅

---

#### BUG-06：`brain doctor --fix` 不修復損壞的 FTS5 索引 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `cli.py` — `cmd_doctor()` |
| **修復** | 加入 FTS5 完整性檢查；`--fix` 模式執行 `INSERT INTO nodes_fts(nodes_fts) VALUES('rebuild')` |

**測試**: `TestBug06FTS5Integrity` — 4 個測試 ✅

---

#### BUG-07：`brain review approve` 不更新 brain.db FTS5 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `review_board.py` — `approve()` |
| **修復** | 核准後同時呼叫 `BrainDB(self.brain_dir).add_node()` 同步 brain.db |

**測試**: `TestBug07ReviewBoardFTSSync` — 4 個測試 ✅

---

#### BUG-08：Web UI Windows 路徑分隔符號問題 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `web_ui/server.py` — `create_app()` |
| **修復** | 改用 `workdir.resolve().as_posix()` 確保跨平台路徑一致性 |

**測試**: `TestBug08WebUIPathConsistency` — 4 個測試 ✅

---

### 優化項目

#### OPT-01：FTS5 CJK N-gram 支援 ✅

- `_ngram()` 增強：空格分隔基礎上額外生成 CJK bigrams
- 一次性遷移：`_setup()` 中檢查 `brain_meta.fts_bigram_v1` 後重建 FTS5

**測試**: `TestOpt01CJKBigram` — 5 個測試 ✅

---

#### OPT-04：Decay Engine 整合至查詢排名 ✅

與 DEF-05 一同修復。`search_nodes()` 對每個結果計算 `effective_confidence` 並重排序，pinned 節點免疫。

---

## v0.2.0 Stability & Observability

> **完成日期**: 2026-04-03 | **包含**: P2 穩定性、可觀測性功能

---

#### OPT-02：混合搜尋自適應權重 ✅

```python
def adaptive_score(query, fts_score, vector_score):
    keyword_density = len(re.findall(r'\b\w+\b', query)) / len(query)
    fts_weight = 0.3 + 0.4 * keyword_density  # 0.3 ~ 0.7
    return fts_score * fts_weight + vector_score * (1 - fts_weight)
```

---

#### OPT-03：向量 Embedding LRU 快取 ✅

```python
@lru_cache(maxsize=2000)
def _cached_embed(text_hash: str) -> tuple[float, ...]: ...
```

---

#### FEAT-01：知識健康度儀表板 ✅

```bash
brain health-report
# ┌─────────────────────────────────────────────┐
# │ Knowledge Health Report — 2026-04-03        │
# ├─────────────────────────────────────────────┤
# │ 過期節點 (confidence < 0.3):  N 個           │
# │ 潛在衝突對:                   N 組           │
# │ 孤立節點 (無 edges):          N 個           │
# │ 高風險 Pitfalls (未存取 30d): N 個           │
# └─────────────────────────────────────────────┘
```

---

#### FEAT-02：智慧衝突偵測 ✅

```bash
brain add "Use PostgreSQL for all databases"
# ⚠️  偵測到潛在衝突！
# 現有規則: "Use SQLite for lightweight apps" (confidence=0.80)
```

---

#### FEAT-03：使用率分析報告 ✅

```bash
brain analytics --period 30d
```

---

#### FEAT-04：自動 Scope 推斷 ✅

```bash
brain add "JWT RS256 required"
# [Brain] 偵測到目前在 src/auth/jwt.py → 自動套用 scope=auth
```

---

#### FEAT-05：知識匯入 / 匯出 ✅

```bash
brain export --format json > brain_backup.json
brain export --format markdown > docs/knowledge.md
brain import brain_backup.json --merge-strategy=confidence_wins
```

---

## v0.3.0 UX & Ecosystem

> **完成日期**: 2026-04-03 | **包含**: P3 UX 功能、生態整合

---

#### OPT-05：讀寫路徑分離 (CQRS) ✅

- `ReadBrainDB`：唯讀 WAL snapshot（`mode=ro`），阻擋所有寫入方法
- `WriteBrainDB`：繼承完整 `_write_guard` 寫入保護

---

#### OPT-06：查詢展開預計算索引 ✅

- Migration v7：建立 `synonym_index` 表
- `build_synonym_index()`：從 `_SYNONYM_MAP` 批次 INSERT
- `expand_query()`：O(1) DB 查找取代原本的 O(n) 字典遍歷

---

#### FEAT-06：知識版本歷史 ✅

```bash
brain timeline "JWT auth decision"
brain rollback <node_id> --to <version>
```

- Migration v8/v9：建立 `node_history` 表 + 索引
- `update_node()` 自動快照 BEFORE 狀態
- `get_node_history()` / `rollback_node()`

---

#### FEAT-07：跨專案知識遷移 ✅

```bash
brain migrate --from ~/project-a/.brain/brain.db \
              --scope global --min-confidence 0.8 --dry-run
```

---

#### FEAT-08：自然語言問句查詢 ✅

```bash
brain ask "為什麼我們不用 MongoDB？"
```

CJK 關鍵字萃取 + 同義詞展開 + 推理鏈輸出，無需 LLM。

---

#### FEAT-09：Web UI 時間軸視覺化 ✅

`/api/timeline` 端點：返回按 `created_at` 排序的節點（含 confidence、type、color）。

---

#### FEAT-10：Slack / GitHub Webhook 整合 ✅

```bash
brain serve --slack-webhook=https://hooks.slack.com/...
```

- `POST /webhook/slack`：透過 `BRAIN_SLACK_WEBHOOK_URL` 發送 Nudge
- `POST /webhook/github`：處理 push event，觸發 `brain sync`

---

## v1.0.0 Intelligence

> **完成日期**: 2026-04-03 | **包含**: DEEP 深度 AI 功能

---

#### DEEP-01：圖推理鏈條輸出 ✅

`ContextEngineer.build_reasoning_chain()`：遍歷 REQUIRES/PREVENTS/CAUSED_BY/SOLVED_BY/DEPENDS_ON 邊：

```
task_keyword
  → REQUIRES → node_A (Rule, conf=0.9)
    ⚠️ Pitfall: "重複請求必須冪等"
  → CAUSED_BY → incident_B
```

`get_context` MCP 回應新增 `reasoning_chain` 欄位。

---

#### DEEP-02：貝葉斯信念傳播 ✅（基礎版）

`BrainDB.propagate_confidence(node_id, dampening=0.5)`：
透過 REQUIRES 邊傳播信心度下降：
`conf_B_effective = conf_B * (1 - dampening * (1 - conf_A))`

---

#### DEEP-03：反事實推理 ✅

```bash
brain counterfactual "如果我們用 NoSQL 代替 PostgreSQL"
# 以下 N 個決策需要重新評估...
```

`KnowledgeGraph.counterfactual_impact(hypothesis)` + CLI 指令。

---

#### DEEP-04：主動學習循環 ✅（基礎版）

`NudgeEngine.generate_questions(task, threshold=0.5)`：
對低信心度節點生成型別適合的提問。

`generate_questions` MCP 工具 + `brain context --interactive` 互動提問。

---

## v1.0.1 Critical Fixes (P0)

> **完成日期**: 2026-04-03 | **包含**: DEF-03、BUG-09、BUG-12

---

#### DEF-03：延遲初始化執行緒安全問題 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `engine.py` — 所有 `@property` 延遲初始化 |
| **症狀** | 多執行緒同時通過 `if self._db is None` 判斷，各自初始化，多個 BrainDB 實例競爭同一資料庫鎖 |
| **修復** | 加入 `self._init_lock = threading.Lock()`；所有 8 個延遲初始化屬性（`db`, `graph`, `extractor`, `context_engineer`, `review_board`, `krb`, `router`, `validator`, `distiller`）改用 double-checked locking 模式 |

```python
@property
def db(self) -> 'BrainDB':
    if self._db is None:
        with self._init_lock:
            if self._db is None:
                self.brain_dir.mkdir(parents=True, exist_ok=True)
                self._db = BrainDB(self.brain_dir)
    return self._db
```

---

#### BUG-09：雙 FTS5 索引不同步 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `context.py` — `_search_batch()` |
| **症狀** | BrainDB 有結果時 early-return，KnowledgeGraph 獨有節點永遠被跳過 |
| **修復** | 移除 early return；同時查詢 BrainDB 和 KnowledgeGraph，以 node id 去重合併結果（BrainDB 優先），回傳 `merged[:limit]` |

---

#### BUG-12：Scope 過濾從未傳遞至 search_nodes() ✅

| 項目 | 內容 |
|------|------|
| **位置** | `context.py` — `_search_batch()` |
| **症狀** | `hybrid_search` 呼叫有傳 scope，但 `search_nodes()` fallback 路徑未傳，多專案共用 `.brain/` 時查詢結果跨污染 |
| **修復** | `_scope = getattr(self, "_scope", None)` 提取一次，`search_nodes()` 和 `hybrid_search()` 統一傳入 `scope=_scope` |

---

## 統計摘要

| 類別 | 數量 | 說明 |
|------|------|------|
| 系統缺陷修復 | 7 | DEF-01~06, DEF-03 |
| BUG 修復 | 10 | BUG-01~08, BUG-09, BUG-12 |
| 性能優化 | 6 | OPT-01~06 |
| 新增功能 | 10 | FEAT-01~10 |
| 深度 AI 功能 | 4 | DEEP-01~04 |
| **合計** | **37** | |

---

*本文件由 `IMPROVEMENT_PLAN.md` 分拆，完成時間 2026-04-03。*
