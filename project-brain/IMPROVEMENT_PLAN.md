# Project Brain — 改善規劃書

> **當前版本**：v0.24.0（2026-04-06）
> **文件用途**：待辦改善項目。已完成項目見 `CHANGELOG.md`。
> **測試基準**：903 passed / 5 skipped（45 unit tests in `test_mem_improvements.py`）
> **分析基準**：2026-04-06 全程式碼審計，涵蓋 brain_db / engine / context / decay / mcp_server / graph / session_store / extractor

---

## 優先等級

| 等級 | 說明 | 目標 |
|------|------|------|
| **P1** | 資料正確性 / 安全性缺陷，影響生產穩定性 | 立即修復 |
| **P2** | 核心功能品質問題，影響使用體驗 | 1–2 週內 |
| **P3** | 長期改善、效能優化、功能強化 | 1–2 個月內 |

---

## 矩陣優先總覽

### 待辦

| 優先 | ID | 影響摘要 | 狀態 |
|------|----|---------|------|
| **P1** | BUG-01 | FTS5 雙寫非原子：節點存入但搜尋找不到 | ☐ 待實作 |
| **P1** | BUG-02 | Decay Engine 衰減計算不一致（三處重複計算） | ☐ 待實作 |
| **P1** | BUG-03 | Rate Limit 閾值 off-by-one，實際可超過限制 | ☐ 待實作 |
| **P1** | BUG-04 | Session Dedup 記憶體洩漏（無主動 cleanup daemon） | ☐ 待實作 |
| **P1** | BUG-05 | `except Exception: pass` 吞掉真實 Bug，無聲故障 | ☐ 待實作 |
| **P1** | BUG-06 | KnowledgeGraph 節點無樂觀鎖，並發修改遺失 | ☐ 待實作 |
| **P2** | SEC-01 | workdir symlink 路徑遍歷檢查時序錯誤 | ☐ 待實作 |
| **P2** | SEC-02 | scope 白名單正則缺 anchor，可繞過 | ☐ 待實作 |
| **P2** | SEC-03 | subprocess commit_hash 無清理，命令注入風險 | ☐ 待實作 |
| **P2** | SEC-04 | `_brain_cache` 無大小限制，DoS 風險 | ☐ 待實作 |
| **P2** | OPT-01 | Impact Analysis N+1 查詢 | ☐ 待實作 |
| **P2** | OPT-02 | SessionStore purge_expired 單條 DELETE × N | ☐ 待實作 |
| **P2** | OPT-03 | subprocess 無 timeout 防護（extractor.py） | ☐ 待實作 |
| **P2** | OPT-04 | FTS5 N-gram 切詞三處重複，維護不同步 | ☐ 待實作 |
| **P2** | OPT-05 | Hybrid Search FTS/Vector 權重硬編碼，無法調整 | ☐ 待實作 |
| **P2** | OPT-06 | Extractor LLM 呼叫無重試，單次失敗整個 commit 跳過 | ☐ 待實作 |
| **P2** | FEAT-01 | Decay Engine 無自動觸發（只有手動 CLI） | ☐ 待實作 |
| **P2** | FEAT-02 | MCP 工具缺 `batch_add_knowledge` | ☐ 待實作 |
| **P2** | FEAT-03 | ContextEngineer 節點類型預算無上限，Pitfall 可擠爆 | ☐ 待實作 |
| **P3** | FEAT-04 | 知識節點缺版本 diff 視圖（`brain history <id> --diff`） | ☐ 待實作 |
| **P3** | FEAT-05 | 匯入/匯出格式只有 CSV，缺 JSON / GraphML | ☐ 待實作 |
| **P3** | FEAT-06 | BrainDB 無備份策略，毀損無恢復 | ☐ 待實作 |
| **P3** | OPT-07 | Nudge Engine 用未衰減的 confidence，推薦精準度下降 | ☐ 待實作 |
| **P3** | OPT-08 | KnowledgeGraph nodes 無複合索引（type + created_at） | ☐ 待實作 |
| **P3** | OPT-09 | Logging 無結構化（使用 % 格式，難以 grep / 整合 ELK） | ☐ 待實作 |
| **P3** | OPT-10 | Embedder Cache 無 hit/miss 統計 | ☐ 待實作 |
| **P2** | TEST-04 | WebUI 測試覆蓋率 < 12%（scope 欄位 migration 不同步） | ⏸ 擱置 |
| **P2** | FEAT-08 | WebUI 節點行內編輯 | ⏸ 擱置 |
| **P2** | REV-01 | 量化對照實驗 Layer 2/3（需線上數據） | △ 進行中 |
| **P2** | REV-02 | 衰減效用對比測試（需 90 天數據） | △ 進行中 |

---

## P1 — 緊急缺陷（資料正確性）

### BUG-01 — FTS5 雙寫非原子性

**位置**：`brain_db.py:503–509`（add_node）、`brain_db.py:513–571`（update_node）

**問題**：
FTS5 觸發器在 schema v12 移除後改為手動 `DELETE + INSERT`，但這兩步與主表 `UPDATE/INSERT` 不在同一 transaction 內。若 FTS sync 失敗（例如磁碟空間不足），`nodes` 表已提交，`nodes_fts` 未更新——節點存入 KB 但永遠搜不到。

```python
# brain_db.py:503-509 — 現況（有 Bug）
try:
    self.conn.execute("DELETE FROM nodes_fts WHERE id=?", ...)
    self.conn.execute("INSERT INTO nodes_fts(...) VALUES(...)")
except Exception as _e:
    logger.error("FTS index update failed: %s", _e)
    # ⚠ 此後仍然執行 self.conn.commit()，節點已存入但 FTS 空
self.conn.commit()
```

**修法**：
```python
# 把 nodes INSERT/UPDATE + nodes_fts sync 包進單一 transaction
with self.conn:  # 自動 COMMIT/ROLLBACK
    self.conn.execute("INSERT OR REPLACE INTO nodes ...")
    self.conn.execute("DELETE FROM nodes_fts WHERE id=?", ...)
    self.conn.execute("INSERT INTO nodes_fts ...")
```

**驗收條件**：
- 新增單元測試：mock FTS INSERT 拋出異常 → 驗證 `nodes` 表也未寫入
- `brain add` 後立即 `brain search` 能找到節點

---

### BUG-02 — Decay 衰減計算三處重複，結果不一致

**位置**：
- `decay_engine.py:286–289`（run 時計算衰減）
- `brain_db.py:341–355`（search_nodes 的 _effective_confidence）
- `context.py:269–274`（_node_priority 的即時衰減）

**問題**：
同一個節點在「手動執行 decay」、「搜尋排序」、「組裝 context」三個時機各算一次衰減，但基準時間（`created_at` vs `updated_at` vs 當下）與衰減率（constants.py vs decay_engine.py）不保證相同。導致知識排序在 5 分鐘內多次查詢結果不穩定。

**修法**：
1. `decay_engine.run()` 計算後統一寫入 `nodes.effective_confidence`
2. `search_nodes` 與 `context.py` 直接讀取 `effective_confidence`，不重複計算
3. 衰減常數統一到 `constants.py`，兩處 import

**驗收條件**：
- 同節點 5 分鐘內兩次 `get_context` 排名相同（無即時衰減噪音）
- 衰減參數只有一個定義來源

---

### BUG-03 — Rate Limit Off-by-One

**位置**：`mcp_server.py:86–88`

**問題**：
```python
if len(_call_times) >= RATE_LIMIT_RPM:   # ← 60 個時才拒絕
    raise RuntimeError(...)
_call_times.append(now)                   # ← 拒絕前已允許第 60 個
```
Lock 內邏輯正確，但閾值判斷讓第 60 個請求通過後才拒絕，實際可達 61 次/分鐘。10 執行緒並發實測可達 62 次。

**修法**：
```python
if len(_call_times) >= RATE_LIMIT_RPM:
```
改為：
```python
if len(_call_times) + 1 > RATE_LIMIT_RPM:
```

**驗收條件**：
- 新增並發測試：10 執行緒同時打，1 分鐘內成功次數 ≤ RATE_LIMIT_RPM

---

### BUG-04 — Session Dedup 記憶體洩漏（無主動 cleanup）

**位置**：`mcp_server.py:57–72`（`_cleanup_expired_sessions`）

**問題**：
`_cleanup_expired_sessions()` 只在 `get_context` 被呼叫時才執行，屬「被動清理」。若某個 workdir 在 30 分鐘後再無人查詢，其 `_session_served` entry 永遠不被清除。長期運行的 MCP server 在有大量不同 workdir 的使用場景下記憶體持續增長。

**修法**：
在 `create_server()` 內啟動 daemon thread：
```python
import threading
def _session_cleanup_daemon():
    while True:
        time.sleep(300)  # 每 5 分鐘
        _cleanup_expired_sessions()

_t = threading.Thread(target=_session_cleanup_daemon, daemon=True)
_t.start()
```

**驗收條件**：
- 單元測試：建立 100 個 expired sessions，等 daemon 5 秒後驗證 `_session_served` 為空
- MCP server 長跑 1 小時記憶體不超過 50MB

---

### BUG-05 — `except Exception: pass` 吞掉無聲故障

**位置**（共 6 處）：
- `mcp_server.py:260`（session dedup 更新失敗）
- `mcp_server.py:272`（`_last_shown_ids` 讀取失敗）
- `mcp_server.py:281`（workdir 解析失敗）
- `mcp_server.py:313`（MEM-05 降權失敗）
- `nudge_engine.py:191`, `207`（搜尋失敗無日誌）

**問題**：
```python
try:
    _new_ids = set(getattr(b.context_engineer, '_last_shown_ids', []))
    # MEM-03 session dedup 核心邏輯
except Exception:  # ← 無 logger，真實 Bug 消失
    pass
```
AttributeError（欄位重構後名稱改變）、TypeError（資料格式變）都靜默吞掉，導致 MEM-03 session dedup 失效數週也無人察覺。

**修法**：
```python
except Exception as _e:
    logger.warning("session dedup update failed: %s", _e, exc_info=True)
    # 或改為具體異常類別：except (AttributeError, TypeError) as _e:
```

**驗收條件**：
- 搜尋所有 `except Exception: pass` → 全部加 `logger.warning`
- 新增測試：模擬 `_last_shown_ids` 不存在 → warning 有輸出，不拋錯

---

### BUG-06 — KnowledgeGraph 無樂觀鎖，並發修改遺失

**位置**：`graph.py:234–280`（`add_node` / `update_node`）

**問題**：
BrainDB 的 `nodes` 表有 `version` 欄位（v14 migration），支援 rollback。但 `KnowledgeGraph.nodes` 無版本控制，`ON CONFLICT(id) DO UPDATE` 直接覆蓋，無 `WHERE version=old_version` 的 CAS 保護。兩個執行緒並發修改同一節點時，後者靜默覆蓋前者（Lost Update）。

**修法**：
```sql
-- graph.py nodes 表加 version 欄位
ALTER TABLE nodes ADD COLUMN version INTEGER NOT NULL DEFAULT 0;

-- update 時做 CAS
UPDATE nodes SET ..., version = version + 1
WHERE id = ? AND version = ?;
-- 若 rowcount = 0，拋 ConcurrentModificationError
```

**驗收條件**：
- 並發測試：2 個執行緒同時修改同節點 → 其中一個拋出錯誤，資料不遺失

---

## P2 — 安全性問題

### SEC-01 — workdir symlink 路徑遍歷時序錯誤

**位置**：`mcp_server.py:108–115`

**問題**：
```python
raw = Path(workdir)
if ".." in raw.parts:          # ← 在 resolve 前檢查
    raise ValueError(...)
path = raw.resolve()           # ← resolve 後 symlink 已展開，可指向任意路徑
```
攻擊者可用 `/safe/link` 這個指向 `/../etc` 的 symlink 繞過 `..` 檢查。

**修法**：先 `resolve()`，再驗證結果在合法根目錄下：
```python
path = Path(workdir).resolve()
allowed_root = Path("/Users").resolve()  # 或從 env 取
if not str(path).startswith(str(allowed_root)):
    raise ValueError("workdir 超出允許範圍")
```

---

### SEC-02 — scope 白名單正則缺 anchor

**位置**：`brain_db.py:580–583`

**問題**：
```python
_SCOPE_RE = re.compile(r"[a-z0-9_-]{1,64}")
if not _SCOPE_RE.match(scope):   # match 只比對開頭，非全字串
    raise ValueError(...)
# "abc!global" 會通過，因為 match 到 "abc"
```

**修法**：改用 `re.fullmatch` 或加 `^...$`：
```python
_SCOPE_RE = re.compile(r"^[a-z0-9_-]{1,64}$")
if not _SCOPE_RE.match(scope):
    raise ValueError(...)
```

---

### SEC-03 — subprocess commit_hash 無清理

**位置**：`extractor.py:209–218`（`from_git_history`）

**問題**：
```python
diff = subprocess.check_output(
    ["git", "show", "--stat", commit_hash],  # ← commit_hash 未驗證格式
    ...
)
```
若 commit_hash 來自外部輸入（API / federation），可注入 `--upload-pack=malicious_script`。

**修法**：
```python
import re
if not re.fullmatch(r"[0-9a-f]{7,40}", commit_hash):
    raise ValueError(f"invalid commit hash: {commit_hash!r}")
```

---

### SEC-04 — `_brain_cache` 無大小限制

**位置**：`mcp_server.py:133–147`（`_resolve_brain`）

**問題**：
```python
_brain_cache: dict[str, ProjectBrain] = {}
# 每個不同 workdir 都加入 cache，無上限
# 攻擊者傳入 1000 個不同 workdir → 1000 個 ProjectBrain 實例駐記憶體
```

**修法**：使用 LRU cache 限制大小：
```python
from functools import lru_cache
# 或手動維護 maxsize=32 的 OrderedDict
MAX_BRAIN_CACHE = int(os.environ.get("BRAIN_CACHE_SIZE", "32"))
```

---

## P2 — 效能與品質問題

### OPT-01 — Impact Analysis N+1 查詢

**位置**：`context.py:162–170`

**問題**：
```python
for comp in components[:2]:
    impact = self.graph.impact_analysis(comp)  # 每個 comp 各查一次 DB
```

**修法**：新增 `graph.impact_analysis_batch(components: list[str]) -> dict`，一次 `WHERE source IN (?, ?)` 查詢。

---

### OPT-02 — SessionStore 單條 DELETE × N

**位置**：`session_store.py:251–262`（`purge_expired`）

**問題**：
```python
for entry in expired_entries:
    self.delete(entry.key)  # 每筆各一次 DELETE SQL
```

**修法**：
```python
self._conn.execute("DELETE FROM entries WHERE expires_at < ?", (now_iso,))
```

---

### OPT-03 — subprocess 無 timeout

**位置**：`extractor.py:225–229`（`from_git_history`）

**問題**：
```python
log_output = subprocess.check_output(
    ["git", "log", ...],
    # ← 無 timeout，若 git 掛住，MCP server 整個 block
)
```

**修法**：加 `timeout=30`，捕捉 `subprocess.TimeoutExpired`。

---

### OPT-04 — FTS5 N-gram 切詞三處重複

**位置**：
- `brain_db.py:308–311`
- `graph.py:220–223`
- `context.py:587–591`

**修法**：統一到 `utils.py` 的 `tokenize(text: str) -> list[str]`，三處 import 同一函式。

---

### OPT-05 — Hybrid Search 權重硬編碼

**位置**：`brain_db.py:370–391`（`_adaptive_weights`）

**問題**：FTS:Vector 預設 `0.4:0.6`，無配置入口，不適合所有查詢模式（短查詢應更依賴 FTS，長查詢依賴 Vector）。

**修法**：
```python
# .brain/config.json
"search": {
  "fts_weight": 0.4,
  "vector_weight": 0.6
}
# 或 env: BRAIN_FTS_WEIGHT=0.4
```

---

### OPT-06 — Extractor LLM 無重試

**位置**：`extractor.py:126–155`（`_call`）

**問題**：API timeout 或 429 時直接回傳空 `knowledge_chunks`，整個 commit 知識跳過。

**修法**：加 exponential backoff 重試（最多 3 次）：
```python
for attempt in range(3):
    try:
        return self._call_once(content, max_tokens)
    except anthropic.RateLimitError:
        time.sleep(2 ** attempt)
return _empty
```

---

## P2 — 功能缺口

### FEAT-01 — Decay Engine 無自動觸發

**位置**：`decay_engine.py`（整體設計）

**問題**：Ebbinghaus 衰減只在手動執行 `brain decay --run` 時生效。若開發者不記得，知識信心永遠不衰減，KB 不會「遺忘」過時知識，Decay Engine 的設計價值完全無法體現。

**修法選項 A（推薦）**：MCP server 啟動時起一個 daemon thread，每天 00:00 UTC 自動執行 decay：
```python
import threading, datetime
def _daily_decay_daemon():
    while True:
        now = datetime.datetime.now(datetime.timezone.utc)
        secs_until_midnight = 86400 - (now.hour * 3600 + now.minute * 60 + now.second)
        time.sleep(secs_until_midnight)
        for b in list(_brain_cache.values()):
            try:
                DecayEngine(b.graph).run()
            except Exception as e:
                logger.warning("daily decay failed: %s", e)
```

**修法選項 B**：PostStop hook 加入 `brain decay --run --quiet`（比 A 更簡單，但依賴 Claude 啟動）。

**驗收條件**：
- 新增 `brain decay --status` 顯示上次執行時間
- 測試：安裝 daemon → 等待 1 秒模擬時鐘 → 驗證 effective_confidence 有更新

---

### FEAT-02 — MCP 工具缺 `batch_add_knowledge`

**位置**：`mcp_server.py`（`add_knowledge` tool）

**問題**：Agent 在 `complete_task` 後有多個 Pitfall/Decision 要寫，目前需逐條呼叫 `add_knowledge`，每次都過 rate limit 和 validation，延遲 × N。

**修法**：新增 MCP tool：
```python
@mcp.tool()
def batch_add_knowledge(
    items: list[dict],   # [{title, content, kind, tags, confidence}, ...]
    workdir: str = "",
) -> dict:
    """批次寫入最多 10 條知識節點，單次 rate limit 扣點。"""
```

**驗收條件**：
- `batch_add_knowledge` 10 條 → 1 次 rate limit 扣點
- 任一條 validation 失敗時 → partial success，回傳 `{ok: true, created: N, errors: [...]}`

---

### FEAT-03 — ContextEngineer 節點類型無預算上限

**位置**：`context.py:323–360`（節點優先度排序）

**問題**：Pitfall 永遠排序最高，若 KB 有 20 條 Pitfall 且全部與查詢相關，整個 context 預算都被 Pitfall 佔滿，Rule / Decision 完全擠不進去。

**修法**：
```python
TYPE_BUDGET = {
    "Pitfall":      0.50,  # 最多佔 50%
    "Rule":         0.30,
    "Decision":     0.20,
    "Architecture": 0.20,
}
```
context 組裝時按類型做配額限制，保證多樣性。

**驗收條件**：
- 測試：加入 10 條 Pitfall + 5 條 Rule，`get_context` 中 Rule 至少出現 1 條

---

## P3 — 長期改善

### FEAT-04 — 知識節點版本 Diff 視圖

**位置**：`brain_db.py`（`node_history` 表已存快照）

**現況**：`node_history` 在每次 update 時存整份 content，但無 diff 計算與展示 CLI。

**修法**：新增 `brain history <node_id> --diff`：
```python
import difflib
def show_diff(old_content: str, new_content: str) -> str:
    return "\n".join(difflib.unified_diff(
        old_content.splitlines(), new_content.splitlines(),
        lineterm=""
    ))
```

---

### FEAT-05 — 匯入/匯出支援 JSON / GraphML

**位置**：`cli_knowledge.py`（`cmd_export` / `cmd_import`）

**現況**：只支援 CSV。GraphML 可直接匯入 Gephi / Neo4j 做圖形分析。

---

### FEAT-06 — BrainDB 自動備份策略

**位置**：`brain_db.py`（`__init__`）

**修法**：每天啟動時做 `VACUUM INTO '.brain/backups/brain_YYYYMMDD.db'`，保留最近 7 天。

---

### OPT-07 — Nudge Engine 使用未衰減的 confidence

**位置**：`nudge_engine.py:191`（`generate_questions`）

**問題**：`node.confidence` 可能是 6 個月前寫入的原始值，未經 decay_engine 更新。Nudge Engine 應讀 `effective_confidence`。

---

### OPT-08 — KnowledgeGraph 缺複合索引

**位置**：`graph.py`（CREATE TABLE nodes）

**修法**：
```sql
CREATE INDEX IF NOT EXISTS idx_nodes_type_created
ON nodes(type, created_at DESC);
```
對「列出所有 Pitfall 按時間排序」類查詢速度提升 10× 以上。

---

### OPT-09 — Logging 非結構化

**位置**：全域（`logger.warning("msg: %s", val)` 模式）

**修法**：改用 `structlog` 或標準 JSON formatter，讓日誌可機器讀取：
```json
{"level": "warning", "module": "brain_db", "event": "FTS sync failed", "node_id": "abc"}
```

---

### OPT-10 — Embedder Cache 無統計

**位置**：`embedder.py`（`_TFIDF_CACHE`）

**修法**：加 `_cache_hits`, `_cache_misses` counter，`brain status` 顯示 cache 命中率。

---

## 驗收標準（下一版本 v0.25.0）

```bash
pytest tests/ -q --ignore=tests/benchmarks --ignore=tests/chaos/test_decay_load.py
# 目標：930+ passed（新增 BUG-01~06、SEC-01~04 測試）
```

| 項目 | 驗收條件 |
|------|---------|
| BUG-01 | FTS 失敗時 nodes 也 rollback；add → search 必定成功 |
| BUG-02 | 同節點 5 分鐘內兩次查詢排名相同 |
| BUG-03 | 10 執行緒並發 1 分鐘，成功次數 ≤ RATE_LIMIT_RPM |
| BUG-04 | 100 個 expired sessions，daemon 5 秒後清空 |
| BUG-05 | 全專案無 `except Exception: pass`（無 logger） |
| BUG-06 | 並發修改同節點，後者拋錯，資料不遺失 |
| SEC-01 | symlink 指向 `/etc` 的 workdir 被拒絕 |
| SEC-02 | `"abc!global"` 的 scope 被拒絕 |
| SEC-03 | 非法格式 commit_hash 拋 ValueError |
| SEC-04 | 傳入 100 個不同 workdir，cache 最多 32 個 |
| FEAT-01 | `brain decay --status` 顯示上次執行時間 |
| FEAT-02 | `batch_add_knowledge` 10 條，1 次 rate limit 扣點 |
| FEAT-03 | 10 Pitfall + 5 Rule，context 中 Rule 至少 1 條 |
