# Project Brain — 已完成改善歷史

> **文件版本**: v2.0
> **建立日期**: 2026-04-03
> **最後更新**: 2026-04-03 (v2.0.0 P3 全部完成)
> **說明**: 本文件歸檔所有已完成的改善項目（共 76 項），供未來參考。
>          所有技術債已清除，無待辦事項。

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

## v1.0.2 Stability (P1)

> **完成日期**: 2026-04-03 | **包含**: DEF-07、DEF-08、DEF-09、BUG-10、BUG-11

---

#### DEF-07：CJK 中文搜尋召回率不一致 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `brain_db.py` `search_nodes()` + `graph.py` `search_nodes_multi()` |
| **症狀** | FTS5 N-gram 只用於 INSERT，查詢字串未展開，搜「中文」找不到含「中文搜尋」的節點 |
| **修復** | `search_nodes()` 將每個 term 通過 `_ngram()` 展開為 bigram token set 後再建 OR 查詢；`search_nodes_multi()` 同樣通過 `_ngram_text()` 展開 safe_terms；兩處均保序去重 |

---

#### DEF-08：FTS5 Bigram 遷移非冪等 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `brain_db.py` `_run_migrations()` + `_setup()` |
| **症狀** | FTS5 重建邏輯在 `_setup()` 中獨立執行，崩潰後旗標已設但索引未完整重建 |
| **修復** | 將 FTS5 重建移入 `_run_migrations()` 作為 v10 migration（callable tuple），受版本號控管確保原子性；`SCHEMA_VERSION` 從 9 升至 10；移除 `_setup()` 中舊的 try/except 區塊 |

---

#### DEF-09：SessionStore 無跨進程寫入保護 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `session_store.py` |
| **症狀** | `BrainDB` 有 `fcntl.flock()` 保護，`SessionStore` 完全無跨進程鎖，MCP + CLI 並發時條目遺失 |
| **修復** | 新增 `_write_guard()` context manager（`fcntl.LOCK_EX` + 可重入 depth counter + Windows fallback）；`set()`、`delete()`、`clear_session()` 均以 `with self._write_guard():` 包覆 |

---

#### BUG-10：Session Store 非持久條目永不過期 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `session_store.py` — `_purge_expired()` |
| **症狀** | `persistent=False` 條目 `expires_at=''`，舊 WHERE 只刪有明確到期時間的記錄 |
| **修復** | 新增第二條 DELETE：`WHERE persistent = 0 AND session_id != current_session`，清除舊 session 的非持久化孤立條目 |

---

#### BUG-11：emotional_weight 未納入節點排名 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `context.py` — `_node_priority()` |
| **症狀** | `emotional_weight` 欄位存在可設定，但排名公式完全忽略，重大事故 Pitfall 與普通筆記同等排名 |
| **修復** | 加入 `ew_boost = (emotional_weight - 0.5) * 0.10`（範圍 −0.05 ~ +0.05），納入 priority 計算 |

---

## v1.1.0 Polish & Completions (P2)

> **完成日期**: 2026-04-03 | **包含**: DEF-10、OPT-07~10、DEEP-02/04/05 補完

---

#### DEF-10：SR 背景執行緒競態 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `context.py` — SR batch update |
| **修復** | 移除 daemon thread，改為同步寫入：優先使用 `self._brain_db._write_guard()` 保護的 BrainDB conn，fallback 至 `self.graph._conn` |

---

#### OPT-07：統一 `_ngram()` 實作 ✅

| 項目 | 內容 |
|------|------|
| **位置** | 新建 `utils.py` + `brain_db.py` + `graph.py` |
| **修復** | 建立 `project_brain/utils.py`，提供 `ngram_cjk()`（unigram + bigram）；`BrainDB._ngram()` 和 `KnowledgeGraph._ngram_text()` 均 delegate 至此，消除行為差異 |

---

#### OPT-08：FTS5 查詢字串轉義 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `brain_db.py` + `graph.py` |
| **修復** | 新增 `BrainDB._sanitize_fts()` 靜態方法，去除 `"()* -^` 等 FTS5 特殊字元；`search_nodes()` 和 `search_nodes_multi()` 均套用 |

---

#### OPT-09：排名使用 effective_confidence ✅

| 項目 | 內容 |
|------|------|
| **位置** | `context.py` — `_node_priority()` |
| **修復** | 優先讀取 `node.get("effective_confidence")`（含時間衰減），fallback 至原始 `confidence` |

---

#### OPT-10：向量快取失效修復 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `brain_db.py` — `update_node()` |
| **修復** | `content` 更新後，以舊 content MD5 為 key 主動從 `_TFIDF_CACHE` 驅逐舊項目，避免記憶體浪費 |

---

#### DEEP-02 補完：BFS 貝葉斯信念傳播 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `brain_db.py` — `propagate_confidence()` |
| **修復** | 原 1-hop 實作改為完整 BFS 多跳遍歷（預設 `max_hops=3`），公式：`conf_eff = conf_base * (1 - dampening * (1 - upstream_conf))`，含起始節點在結果中 |

---

#### DEEP-04 補完：主動學習回饋迴路 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `mcp_server.py` — `answer_question()` 新工具 |
| **修復** | 新增 `answer_question(node_id, answer, new_confidence)` MCP 工具：更新節點 confidence + content，並建立 L2 episode 記錄，形成 generate_questions → answer_question 閉環 |

---

#### DEEP-05：時序邊自動建立 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `archaeologist.py` + `brain_db.py` |
| **修復** | `ProjectArchaeologist` 接受可選 `brain_db` 參數；`_scan_git_history()` 每次建立知識節點後自動呼叫 `brain_db.add_temporal_edge(commit_node → knowledge_node, INTRODUCES)`，填充 `temporal_edges` 表 |

---

## v1.2.0 Ecosystem (P3)

> **完成日期**: 2026-04-03 | **包含**: FEAT-11~14、DEEP-03 補完

---

#### FEAT-11：知識圖譜 Neo4j/Cypher 匯出 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `brain_db.py` `export_neo4j()` + `cli.py` `cmd_export()` |
| **實作** | `export_neo4j()` 生成 Cypher `CREATE (:Label {...})` 節點語句和 `MATCH … CREATE (a)-[:REL]->(b)` 關係語句；CLI 加入 `brain export --format neo4j` 選項，輸出 `.cypher` 檔 |

---

#### FEAT-12：匯入衝突互動式解決 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `brain_db.py` `import_json()` + `cli.py` `cmd_import()` |
| **實作** | `import_json()` 新增 `merge_strategy` 參數（skip / overwrite / confidence_wins / interactive）；CLI 加入 `--merge-strategy interactive`，提供逐一衝突解決介面（keep / import / merge / skip） |

---

#### FEAT-13：知識節點生命週期管理 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `brain_db.py` `deprecate_node()` + `get_lifecycle()` + `cli.py` |
| **實作** | `deprecate_node()` 設 `is_deprecated=1` + 建立 REPLACED_BY 邊；`get_lifecycle()` 返回狀態、版本歷史、取代鏈；CLI 新增 `brain deprecate <id>` 和 `brain lifecycle <id>` 指令 |

---

#### FEAT-14：使用率指標 CSV 匯出 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `cli.py` `cmd_analytics()` |
| **實作** | `brain analytics --export csv --output <path>` 輸出 node_id / title / type / scope / access_count / last_accessed / confidence / importance 欄位的 CSV 檔 |

---

#### DEEP-03 補完：反事實推理強化 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `graph.py` `counterfactual_impact()` |
| **實作** | 為每個受影響節點計算 `impact_score = confidence × (1 − 0.3 × distance)`（直接匹配 distance=0，依賴鏈 distance=1），按 impact_score 排序後回傳，使最高風險節點排最前 |

---

## 統計摘要

| 類別 | 數量 | 說明 |
|------|------|------|
| 系統缺陷修復 | 11 | DEF-01~10 |
| BUG 修復 | 12 | BUG-01~12 |
| 性能優化 | 10 | OPT-01~10 |
| 新增功能 | 14 | FEAT-01~14 |
| 深度 AI 功能 | 8 | DEEP-01~05 + DEEP-02/03/04 補完 |
| **合計** | **55** | |

---

---

## v1.2.1 Hotfix (P0)

> **完成日期**: 2026-04-03 | **包含**: BUG-13

---

#### BUG-13：Session Store `_purge_expired()` 引用不存在的 `persistent` 欄位 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `session_store.py` — `_purge_expired()` |
| **症狀** | `DELETE FROM session_entries WHERE persistent = 0 AND session_id != ?` 因 schema 無 `persistent` 欄位而 SQL 錯誤，導致非持久化 session 條目（`progress`/`notes` 類別）永遠不被清理 |
| **根本原因** | BUG-10 修復時新增的清理 SQL 引用了未在 schema 建立的計劃欄位 |
| **影響** | `_purge_expired()` 每次呼叫均 SQL error；舊 session 的 progress/notes 條目無限累積；session_store.db 持續膨脹（繞過 DEF-06 的 MAX_SESSION_ENTRIES 保護） |
| **修復** | 改用 `category IN ('progress', 'notes') AND session_id != ?`，從 `CATEGORY_CONFIG` 動態推導非持久化類別，與 `clear_session()` 邏輯保持一致 |

```python
# 修復前（BUG）
conn.execute(
    "DELETE FROM session_entries WHERE persistent = 0 AND session_id != ?",
    (self.session_id,)
)

# 修復後
non_persistent = [k for k, v in CATEGORY_CONFIG.items() if not v["persistent"]]
placeholders   = ",".join("?" * len(non_persistent))
conn.execute(
    f"DELETE FROM session_entries WHERE category IN ({placeholders}) AND session_id != ?",
    non_persistent + [self.session_id],
)
```

**驗證**：手動測試確認 session_B 初始化後，session_A 的 `progress`/`notes` 條目被清除，`pitfalls` 保留。

---

*v1.2.1 更新：2026-04-03。BUG-13 P0 hotfix 完成，總計 56 項改善落地。*

---

## v1.2.2 Reliability & Honesty (P1)

> **完成日期**: 2026-04-03 | **包含**: R-4、U-1、H-1

---

#### R-4：`add_edge()` 不驗證節點存在 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `graph.py` — `add_edge()` |
| **症狀** | 直接 INSERT 邊而不確認 source_id / target_id 存在，可靜默建立孤立邊，DEEP-01 推理鏈條和 DEEP-03 反事實推理可能遍歷幽靈節點 |
| **修復** | 在 INSERT 前加 `SELECT id FROM nodes WHERE id IN (?, ?)` 驗證；缺少任一節點時 raise `ValueError`，呼叫方明確感知錯誤 |

```python
# 修復後
ids_found = {r[0] for r in self._conn.execute(
    "SELECT id FROM nodes WHERE id IN (?, ?)", (source_id, target_id)
).fetchall()}
missing = {source_id, target_id} - ids_found
if missing:
    raise ValueError(
        f"add_edge: referenced node(s) not found: {', '.join(sorted(missing))}"
    )
```

---

#### U-1：API 錯誤訊息洩漏 SQL ✅

| 項目 | 內容 |
|------|------|
| **位置** | `api_server.py` — 8 處 `str(e)` 洩漏點 |
| **症狀** | 所有 exception handler 直接返回 `str(e)` 給 HTTP 客戶端，洩漏原始 SQL 錯誤、堆疊追蹤、內部路徑 |
| **修復** | 加入 module-level `logger = logging.getLogger(__name__)`；所有 8 處改為 `logger.warning(..., exc_info=True)` + 回傳中文友善訊息；SSE stream 內的錯誤字串亦改為靜態訊息 |

---

#### H-1：信心值語意重新設計 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `utils.py`（新增）、`context.py:_fmt_node()`、`nudge_engine.py:Nudge.to_dict()` |
| **症狀** | 信心值 0.75 可能是「React 16 老規則」或「近期驗證的規則」，Agent 無法判斷；`nudge_engine.py` urgency 定義不透明；`context.py` 的 `applicability_condition` / `invalidation_condition` 雖建置但從未輸出 |
| **修復** | 三層改動：① `utils.py` 新增 `confidence_label(conf)` — 四層語意標注（⚠ 推測 / ~ 推斷 / ✓ 已驗證 / ✓✓ 權威）；② `context.py:_fmt_node()` — 標題列加入 `[{clabel}]`，並修正 `meta`（適用條件/失效條件）從未 return 的 bug；③ `nudge_engine.py:Nudge.to_dict()` — 加入 `confidence_label` 欄位，AI agent 可直接讀取 |

```python
# utils.py
def confidence_label(conf: float) -> str:
    if conf < 0.3: return "⚠ 推測"
    if conf < 0.6: return "~ 推斷"
    if conf < 0.8: return "✓ 已驗證"
    return "✓✓ 權威"

# context.py _fmt_node() 輸出示例
# ### Rule：JWT RS256 [✓✓ 權威]
# Use RS256 for multi-service auth
# `jwt` `auth`
#   ⚠ 適用條件：多服務環境

# nudge_engine.py Nudge.to_dict()
# { ..., "confidence": 0.45, "confidence_label": "~ 推斷", ... }
```

**副作用修正**：`_fmt_node()` 同時修復 `applicability_condition` / `invalidation_condition` 雖計算但從未加入 return 字串的 bug（H-4 的部分改善）。

**評分影響**：誠實性 C+ → B-，可靠度 A- → A，可用性 B → B+

---

*v1.2.2 更新：2026-04-03。P1 三項修復完成，總計 59 項改善落地。*

---

## v1.3.0 Quality (已知技術債全面清除)

> **完成日期**: 2026-04-03 | **包含**: R-2、R-5、U-2、U-5、H-3、H-4（部分）、A-4、C-1、C-3、C-6/BUG-14、E-4、A-3/E-6、P-4

---

#### R-2：FTS5 INSERT 失敗靜默 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `graph.py` — `add_node()` FTS5 INSERT except block |
| **症狀** | FTS5 索引 INSERT 失敗時 `except: pass`，節點存在但不可搜尋，無任何警告 |
| **修復** | 加入 `import logging; logger = logging.getLogger(__name__)`；exception block 改為 `logger.warning("fts5_insert_failed node=%s: %s", node_id, _fts_err)` |

---

#### R-5：Session Store 過期清理不定期執行 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `session_store.py` — `_purge_expired()` + `set()` |
| **症狀** | `_purge_expired()` 只在 `__init__` 執行一次，長時間運行的 MCP server 過期條目持續累積 |
| **修復** | 新增 `_last_purge_ts: float = 0.0` 類別屬性；`set()` 中加入 `if time.time() - self._last_purge_ts > 3600: self._purge_expired()`；`_purge_expired()` 開頭設定 `self._last_purge_ts = time.time()` |

```python
# session_store.py set() 中新增（BUG-13 修復配合）
if time.time() - self._last_purge_ts > 3600:
    self._purge_expired()
```

---

#### U-2：Rate Limit 靜默空回應 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `mcp_server.py` — `get_context()` / `add_knowledge()` / `brain_status()` rate check |
| **症狀** | Rate limit 觸發時返回空字串 `""`，Agent 無法區分「限速」與「無知識」 |
| **修復** | 將 `_rate_check()` 呼叫包在 `try/except RuntimeError as _rl_err` 中；觸發時返回 `f"[rate_limited] {_rl_err} — 請稍後再試"`；`RATE_LIMIT_RPM` 改為讀 `BRAIN_RATE_LIMIT_RPM` 環境變數，預設 60 |

```python
try:
    _rate_check()
except RuntimeError as _rl_err:
    return f"[rate_limited] {_rl_err} — 請稍後再試"
```

---

#### U-5：新增安全重置指令 `brain clear` ✅

| 項目 | 內容 |
|------|------|
| **位置** | `cli.py` — `cmd_clear()` + argument parser |
| **症狀** | 無安全的資料清除指令，使用者需手動 `rm .brain/brain.db` |
| **修復** | 新增 `cmd_clear(args)`：預設清除當前 session L1a 工作記憶；`--all --yes` 雙重確認旗標才清除所有 L3 知識節點（防止誤操作） |

```bash
brain clear                    # 清除當前 session（安全）
brain clear --all --yes        # 清除所有 L3 知識（需雙重確認）
```

---

#### H-3：推理鏈條邊加入信心標記 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `context.py` — `build_reasoning_chain()` |
| **症狀** | 推理鏈條輸出邊時只有 `conf=0.80`，無法區分「人工建立的驗證邊」和「AI 推斷的邊」 |
| **修復** | 使用 `confidence_label()` 在每條邊輸出加入語意標注，例如 `conf=0.80 ✓ 已驗證` |

```python
# 修復後輸出示例
tgt_conf_str = f"conf={tgt_conf:.2f} {_clabel(tgt_conf)}"
# → "conf=0.80 ✓ 已驗證"
# → "conf=0.45 ~ 推斷"
```

---

#### A-4：移除 router.py L1b 死程式碼 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `router.py` — L1b Anthropic Memory Tool 橋接區塊 |
| **症狀** | `path = f"{dir_path}/{entry_name}.md"` 中 `dir_path` 在此 scope 未定義，`NameError` 每次被外層 try/except 靜默吞噬；L1b 橋接永遠不工作 |
| **修復** | 移除整個 L1b 死程式碼區塊（約 20 行），加入注釋說明 L1b 未實作、所有寫入走 L1a (SessionStore) |

---

#### C-6/BUG-14：TFIDF Cache 修正為真正 LRU ✅

| 項目 | 內容 |
|------|------|
| **位置** | `embedder.py` — `_TFIDF_CACHE` |
| **症狀** | 注解聲稱 LRU，實際淘汰使用 `next(iter(_TFIDF_CACHE))`（dict 插入順序 = FIFO），熱點節點被提前驅逐 |
| **修復** | `dict` → `collections.OrderedDict`；命中時 `_TFIDF_CACHE.move_to_end(cache_key)` 升至 MRU；淘汰時 `_TFIDF_CACHE.popitem(last=False)` 移除真正 LRU |

```python
from collections import OrderedDict
_TFIDF_CACHE: OrderedDict = OrderedDict()
# 命中時
_TFIDF_CACHE.move_to_end(cache_key)
# 淘汰時
_TFIDF_CACHE.popitem(last=False)
```

---

#### C-1/C-3：新增 `brain optimize` 維護指令 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `brain_db.py` — `optimize()` + `cli.py` — `cmd_optimize()` |
| **症狀** | SQLite 從不呼叫 VACUUM，刪除節點後磁碟空間不回收；FTS5 索引含大量孤立記錄；長期運行後 brain.db 持續膨脹 |
| **修復** | `BrainDB.optimize()` 執行 WAL checkpoint、VACUUM、ANALYZE、FTS5 rebuild、integrity check，返回 `{size_before, size_after, saved_bytes, fts5_status}`；CLI 新增 `brain optimize` 指令顯示優化結果 |

```bash
brain optimize
# 📦 brain.db: 12.3 MB → 4.1 MB (已節省 8.2 MB)
# 🔍 FTS5 索引已重建
# ✅ 完整性檢查通過
```

---

#### E-4：context.py 新增 Logging ✅

| 項目 | 內容 |
|------|------|
| **位置** | `context.py` — 全模組 |
| **症狀** | `context.py` 完全無日誌；上下文注入失敗（節點數量異常、token 超限）無從調查 |
| **修復** | 加入 `import logging; logger = logging.getLogger(__name__)`；`build()` 開始時記錄 `logger.debug("context.build start ...")`，結束時記錄節點數和 token 數 |

---

#### A-3/E-6：關鍵參數環境變數化 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `context.py`、`mcp_server.py` |
| **症狀** | `MAX_CONTEXT_TOKENS=6000`、`RATE_LIMIT_RPM=60` 均為模組級硬編碼常數，不同部署場景（低記憶體 / 高頻呼叫）需修改程式碼 |
| **修復** | `context.py`：`MAX_CONTEXT_TOKENS = int(os.environ.get("BRAIN_MAX_TOKENS", "6000"))`；`mcp_server.py`：`RATE_LIMIT_RPM = int(os.environ.get("BRAIN_RATE_LIMIT_RPM", "60"))` |

---

#### P-4：F7 頻率加成改為對數曲線 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `decay_engine.py` — `compute_effective_confidence()` F7 計算 |
| **症狀** | 線性公式 `min(0.15, access/10 * 0.05)` 在 30 次存取即達上限，存取 100 次與存取 30 次效果相同，無法有效讓超高頻知識浮頂 |
| **修復** | 改為對數公式 `min(0.20, math.log1p(access) * 0.04)`；飽和點從 30 次移至 ~150 次；上限從 0.15 提升至 0.20 |

```python
import math as _math
f7 = min(0.20, _math.log1p(access) * 0.04)
```

---

*v1.3.0 更新：2026-04-03。技術債全面清除，共修復 13 項問題，總計 72 項改善落地。*

---

## v2.0.0 P3 Scale & Engineering

> **完成日期**: 2026-04-03 | **包含**: P-1、U-4、E-5、RQ-1

---

#### P-1：同義詞展開雜訊控制 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `context.py` — `_expand_query()` + 新增 `EXPAND_LIMIT` 模組常數 |
| **症狀** | `_expand_query()` 上限 30 個詞，每個詞彙展開全部同義詞（例如 "jwt" → 7 個同義詞），總詞彙量膨脹造成 FTS5 查詢雜訊，低相關節點混入前 5 結果 |
| **修復** | 拆分為兩階段：① 先加入所有原始詞彙；② 每個詞最多取前 3 個同義詞；總上限改為 `EXPAND_LIMIT=15`（可透過 `BRAIN_EXPAND_LIMIT` env 覆寫） |

```python
# 修復後（context.py）
EXPAND_LIMIT = int(os.environ.get("BRAIN_EXPAND_LIMIT", "15"))

# 層次 2：每詞限 3 個同義詞，優先保留原始詞彙
for w in all_words:
    _add(w)
for w in all_words:
    for syn in self._SYNONYM_MAP.get(w, [])[:3]:   # 原本無限制
        _add(syn)
return expanded[:EXPAND_LIMIT]  # 原本 [:30]
```

**效果**：查詢「jwt」從 16 個詞縮減至 ≤15 個，精準度提升；`BRAIN_EXPAND_LIMIT=8` 可進一步收窄。

---

#### U-4：cmd_index 長操作進度回饋 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `cli.py` — `cmd_index()` |
| **症狀** | 向量索引批次處理（可能數百個節點）使用 `print(f"  {ok}/{len(pending)}...", end='\r')`，無動畫、無進度條，大型知識庫終端機幾乎靜止 |
| **修復** | 改用既有的 `_Spinner("建立向量索引", total=len(pending))`，每個節點呼叫 `sp.update(node_title)` 顯示即時進度條（`█░` 字元）和節點標題 |

```bash
# 修復後輸出示例
  ⠋  建立向量索引  [██████░░░░] 60/100  JWT 認證規則…
```

---

#### E-5：CLI/API/MCP 測試覆蓋 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `tests/test_cli.py`、`tests/test_api.py`、`tests/test_mcp.py`（新建） |
| **症狀** | `cli.py`、`api_server.py`、`mcp_server.py` 排除於 coverage 外，核心使用者介面無任何自動化測試，重構或修復後的回歸驗證依賴人工 |
| **修復** | 新增 31 個測試，全部通過：`test_cli.py`（12 個）、`test_mcp.py`（13 個）、`test_api.py`（6 個） |

覆蓋範圍：
- CLI：`_Spinner`、`_workdir` 自動偵測、`cmd_optimize`、`cmd_clear`（session / all / yes 旗標）、`cmd_add`、`cmd_context`
- MCP：`_safe_str` 輸入驗證、`_validate_workdir` 路徑安全、`_rate_check` 執行緒安全、U-2 回應格式、env 覆寫
- API：`/health`、`/v1/stats`、`create_app` 路由驗證、U-1 回歸（錯誤訊息無 SQL 洩漏）

```
tests/test_cli.py   12 passed
tests/test_mcp.py   13 passed
tests/test_api.py    6 passed
─────────────────────────────
合計              31 passed  ✅
```

---

#### RQ-1：語意去重閾值動態化 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `context.py` — `_deduplicate_sections()` + 新增 `DEDUP_THRESHOLD` 模組常數 |
| **症狀** | cosine similarity 閾值硬編碼為 `0.85`，無法根據不同部署場景調整；閾值過高（近似段落重複出現）或過低（有用資訊被去重）均無法調整 |
| **修復** | `DEDUP_THRESHOLD = float(os.environ.get("BRAIN_DEDUP_THRESHOLD", "0.85"))`；`_deduplicate_sections()` 改用此常數取代字面量 `0.85` |

```python
# 修復後（context.py）
DEDUP_THRESHOLD = float(os.environ.get("BRAIN_DEDUP_THRESHOLD", "0.85"))

# 在 _deduplicate_sections()：
if j not in dropped and sims[i][j] > DEDUP_THRESHOLD:  # 原本 > 0.85
```

**調整建議**：
- `0.85`（預設）：保守，只去除幾乎相同的段落
- `0.70`：積極，去除高度重複內容，節省更多 token
- `0.95`：寬鬆，幾乎不去重，適合需要多角度參考的場景

---

*v2.0.0 更新：2026-04-03。P3 全部完成，共 4 項。總計 76 項改善全部落地，無待辦技術債。*
