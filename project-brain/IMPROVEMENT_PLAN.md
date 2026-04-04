# Project Brain — 改善規劃書

> **當前版本**：v0.6.0（2026-04-04）
> **文件用途**：待辦改善項目，依優先級排序。已完成項目見 `CHANGELOG.md`。

---

## 優先等級

| 等級 | 說明 | 目標版本 |
|------|------|---------|
| **P0** | 阻礙核心功能 / 資料損毀風險，必須立即修復 | 下一個 patch |
| **P1** | 明確影響可靠性或正確性，應優先處理 | 下一個 minor |
| **P2** | 值得做但可計劃排入 | 計劃中 |
| **P3** | 長期願景、低頻路徑、實驗性 | 評估中 |

---

## P0 — 立即修復

| ID | 問題 | 影響 | 解決方案 | 工時 |
|----|------|------|---------|------|
| ~~BUG-A01~~ | ~~`add_knowledge` 以 `WHERE title=?` 更新 scope，title 不唯一~~ | ~~同名節點全部被改寫，靜默資料損毀~~ | ✅ **已修復（2026-04-04）**：改用 `WHERE id=?`，直接使用 `b.db`（移除多餘的 new BrainDB），`except` 改 `logger.warning` | 30 分 |

---

## P1 — 下一個 minor（v0.7.0）

| ID | 問題 | 影響 | 解決方案 | 工時 |
|----|------|------|---------|------|
| ~~BUG-A02~~ | ~~FTS5 觸發器（`nodes_fts_au/ad`）與手動同步並存~~ | ~~重複索引風險~~ | ✅ **已修復（2026-04-04）**：移除兩個觸發器；`delete_node()` 補手動 FTS5 清理；v12 migration `DROP TRIGGER IF EXISTS` | 1 天 |
| ~~ARCH-01~~ | ~~MCP tools 直接 `BrainDB(_bdir)`，繞過 singleton~~ | ~~多 WAL writer 鎖爭用~~ | ✅ **已修復（2026-04-04）**：`temporal_query`、`mark_helpful`、`report_knowledge_outcome` 改用 `_resolve_brain().db` | 1 天 |

---

## P2 — 計劃中（v0.7.0 ~ v1.0.0）

### 資安

| ID | 問題 | 影響 | 解決方案 | 工時 |
|----|------|------|---------|------|
| ~~SEC-01~~ | ~~`search_nodes()` scope filter 以 f-string 拼接 SQL~~ | ~~scope 值含特殊字元時有潛在注入路徑~~ | ✅ **已修復（2026-04-04）**：`search_nodes()` 入口加 `re.match(r'^[a-z0-9_-]+$', scope)` 白名單；非法值 → `scope=None` | 1 小時 |
| ~~SEC-02~~ | ~~`mcp_server.py` 路徑以 `.resolve()` 後才驗 `..`，symlink 可繞過~~ | ~~任意路徑讀取風險~~ | ✅ **已修復（2026-04-04）**：`_validate_workdir()` 在 `.resolve()` 前先驗 `".." in raw.parts` | 1 小時 |
| ~~BUG-A05~~ | ~~`git_activity` 的 branch 名稱未驗證格式~~ | ~~使用者輸入直接傳入 subprocess，可能命令注入~~ | ✅ **已修復（2026-04-04）**：`temporal_query` 加 `re.match(r'^[a-zA-Z0-9._\-/]+$', git_branch)` 驗證 | 30 分 |

### 資料一致性

| ID | 問題 | 影響 | 解決方案 | 工時 |
|----|------|------|---------|------|
| ~~DATA-02~~ | ~~`_run_migrations()` 失敗後 `schema_version` 仍 +1~~ | ~~失敗的 migration 下次啟動被視為已完成而跳過，schema 永久損壞~~ | ✅ **已修復（2026-04-04）**：引入 `_genuine_failure` flag；只有成功或 benign 錯誤（"already exists"）才遞增 version | 1 小時 |
| ~~BUG-A04~~ | ~~federation 匯出 scope fallback 忽略 scope 過濾~~ | ~~本地私有節點意外洩漏給接收方~~ | ✅ **已修復（2026-04-04）**：fallback query 補上 `AND (scope IS NULL OR scope = 'global' OR scope = ?)` | 1 小時 |
| ~~DATA-01~~ | ~~節點刪除無審計日誌~~ | ~~cascade 刪除的 edge 無紀錄，無法回溯~~ | ✅ **已修復（2026-04-04）**：`delete_node()` 刪除前先 INSERT 到 `node_history`（title, content, confidence, change_note='deleted'） | 2 小時 |

### 架構

| ID | 問題 | 影響 | 解決方案 | 工時 |
|----|------|------|---------|------|
| ~~ARCH-02~~ | ~~thread-local SQLite 連線無清理~~ | ~~API server 每請求一執行緒，長跑洩漏 file descriptor~~ | ✅ **已修復（2026-04-04）**：`BrainDB`/`KnowledgeGraph` 改用單一 `_conn_obj`（`check_same_thread=False`）；`_make_connection()` 虛方法供 `ReadBrainDB` 覆寫；新增 `close()` 方法 | 2 天 |
| ~~ARCH-03~~ | ~~`search_nodes` / `search_nodes_multi` 簽名不一致，回傳結構不同~~ | ~~呼叫方需 workaround，API 令人困惑~~ | ✅ **已修復（2026-04-04）**：`search_nodes` 加 `terms: list \| None` 參數；`search_nodes_multi` 改為 thin wrapper；`context.py` 改呼叫 `search_nodes(terms=terms)` | 3 天 |

### 效能

| ID | 問題 | 影響 | 解決方案 | 工時 |
|----|------|------|---------|------|
| ~~PERF-01~~ | ~~`context.py` 迴圈內逐筆 `UPDATE access_count`（N+1 寫入）~~ | ~~大量節點時 context 組裝慢~~ | ✅ **已修復（2026-04-04）**：移除迴圈內 UPDATE；SR block（executemany）是唯一的 access_count 更新路徑 | 2 小時 |
| ~~PERF-02~~ | ~~FTS5 排序含 `CASE expression`，大資料集全掃後排序~~ | ~~> 5000 節點時查詢變慢~~ | ✅ **已修復（2026-04-04）**：v13 migration 加 `idx_nodes_pinned_conf ON nodes(is_pinned DESC, confidence DESC)`；SCHEMA_VERSION → 13 | 1 小時 |

### 重構

| ID | 問題 | 影響 | 解決方案 | 工時 |
|----|------|------|---------|------|
| ~~REF-02~~ | ~~`_SYNONYM_MAP` 複製於 `brain_db.py` 和 `context.py` 兩處~~ | ~~每次修改需同步兩處，易失同步~~ | ✅ **已修復（2026-04-04）**：新增 `project_brain/synonyms.py`；兩處改為 `from .synonyms import SYNONYM_MAP as _SYNONYM_MAP` | 1 小時 |
| ~~REF-03~~ | ~~`_write_guard()` 使用 `fcntl.flock()`（不跨平台）~~ | ~~Windows 完全失效；每次寫入多 1–2ms syscall~~ | ✅ **已修復（2026-04-04）**：改用 `threading.RLock`（`self._write_lock`），移除 fcntl 相關程式碼 | 1 小時 |

### 功能 / 量測

| ID | 問題 | 影響 | 解決方案 | 工時 |
|----|------|------|---------|------|
| FLY-03 | `brain status` 無知識庫健康度評分 | 用戶看不到飛輪在轉，無感知 | 加入節點數、近 7 天新增數、最常命中的 3 個 Pitfall | 半天 |
| REV-02 | 尚未量測 Decay 實際效用 | 無法驗證 F2/F3 是假設還是事實 | 對比有衰減 vs 無衰減知識庫，Agent 被導向過時知識的比例 | 1 天 |
| DIR-01 | 核心功能無最低品質門檻 | 無 CI gate，品質無法被持續保護 | 補建驗收標準：`get_context` 召回率 ≥ 60%；`complete_task` 正確寫入率 100% | 半天 |
| DIR-02 | 需使用者手動步驟才能運作的功能，標記為「完成 ✅」 | 誤導使用者對功能完備性的判斷 | 標記 `🟡 架構就緒（Arch-Ready）` vs `🟢 端對端可用` | 半天 |
| TECH-01 | CHANGELOG / README 無功能完成度標記 | 用戶無法判斷功能是否端對端可用 | 每個功能加 🟢 端對端 / 🟡 架構就緒 / 🔴 實驗性 | 半天 |
| TECH-02 | README `brain distill` 未說明需自行執行 Axolotl / Unsloth | 使用者期望工具自動完成訓練，造成誤解 | 明確標注「產生 JSONL 設定檔，實際訓練需自行執行」 | 15 分 |
| TECH-03 | 無 ANN Index 觸發條件說明 | 用戶不知何時切換 HNSW，可能錯誤配置 | 文件標注「建議 > 2000 節點後切換 HNSW」 | 15 分 |
| ~~STAB-08~~ | ~~Chaos test 存在但未接 CI gate~~ | ~~每版本容易遺漏手動執行~~ | ✅ **已修復（2026-04-04）**：`pyproject.toml` 加 `chaos` marker；6 個 Chaos/Load 測試類加 `@pytest.mark.chaos`；CI 可執行 `pytest -m chaos` | 半天 |
| DIR-03 | 每版本隨機審計未制度化 | v0.6.0 執行一次後未固化為流程 | 每次發布前隨機抽查 3 個「完成」項目，確認 commit hash + 行號可查 | 半天 |
| FLY-04 | NudgeEngine 命中率未量測 | 無法知道 nudge 是否真正觸發 | events 表記錄 `nudge_triggered`；量測：nudge 事件數 ÷ `get_context` 呼叫數，目標 ≥ 30% | 1 天 |
| FLY-05 | 知識庫自然成長率未量測 | 無法驗證 `complete_task` 閉環有效 | SQL：`SELECT COUNT(*) FROM nodes WHERE tags LIKE '%auto:complete_task%' AND created_at >= datetime('now','-7 days')`，目標 ≥ 5 | 半天 |
| UNQ-03 | ~~召回率基準~~ | ✅ **已完成**：MultilingualEmbedder + hybrid search = **95%**（2026-04-04，`tests/benchmarks/benchmark_recall.py`） | — | — |

---

## P3 — 長期 / 低頻 / 實驗性

| ID | 問題 | 影響 | 解決方案 | 工時 |
|----|------|------|---------|------|
| REF-01 | BrainDB 1797 行，承擔 10+ 職責（God Object） | 難以維護，重構前需測試覆蓋率 ≥ 70% | 逐步抽離：`VectorStore`（add/search vector）、`FeedbackTracker`（record_feedback）、`SynonymIndex`（synonyms.py） | 2 週+ |
| ARCH-04 | scope 三路控制流（`--global` / `--scope` / 自動推斷）讓使用者困惑 | UX 複雜，Breaking change | 合併 `--global` / `--scope` 為單一 `--scope global`；保留自動推斷 | 1 週 |
| REF-04 | 魔法數字散落（`0.003`、`800`、`limit=8` 等） | 維護時難以追蹤意圖 | 新增 `constants.py`，遷入衰減率、budget、預設 limit | 半天 |
| PERF-03 | CJK token 計數逐字迭代，無快取 | 高頻呼叫時浪費 CPU | `_count_tokens()` 加 `@lru_cache` | 30 分 |
| BUG-A03 | `engine.py` double-checked locking 無 volatile 語意 | 極低概率的競態條件 | 改用 `threading.Lock` 正確包裹 | 1 小時 |

---

## 版本路線圖

| 版本 | 主題 | 必要項目 | 發布 Gate |
|------|------|---------|----------|
| **v0.7.0** | 穩定強化 | BUG-A02、ARCH-01、STAB-08、SEC-01、PERF-01、DATA-02、REF-02、REF-03 | 所有 P1 修復；Chaos test 接 CI；NudgeEngine 命中率有數據 |
| **v1.0.0** | 長期穩定 | REF-01 拆分（VectorStore/FeedbackTracker）、ARCH-02~04、PERF-02 | 測試覆蓋率 ≥ 70%；BrainDB ≤ 800 行 |

---

## 四維指標量測基準（v0.6.0）

> 每個 minor 版本發布前執行完整核查。Gate 條件欄位為硬性阻塞點，不可跳過。

### 一、走向（Direction）

| 指標 | 門檻 | 量測方法 | v0.6.0 現況 |
|------|------|---------|------------|
| 版本發布條件達成率 | 100%（Gate） | CHANGELOG 每版本 Gate checklist 完成數 ÷ 總數 | ✅ 達成 |
| 計劃打勾 vs 程式碼完成率 | 100% | 每版本 code review 隨機抽查 5 項，確認有 commit hash + 行號可查 | △ 發現 graphiti_url 描述不精確 |
| 技術債清零週期 | P0 ≤ 當版本；其餘 ≤ 2 版本 | IMPROVEMENT_PLAN 歷史紀錄，計算每個 Bug ID 從出現到 ✅ 的版本跨距 | ✅ 符合 |
| Arch-Ready vs 端對端比例 | ≥ 70% | 功能表中 🟢 端對端可用 ÷ (🟢 + 🟡 架構就緒) | ❌ 待 TECH-01 完成後量測 |
| 版本週期一致性 | 相鄰版本完成數差距 ≤ 30% | CHANGELOG 各版本 completed items 數量統計 | ❌ 未量測 |

### 二、穩定性（Stability）

| 指標 | 門檻 | 量測方法 | v0.6.0 現況 |
|------|------|---------|------------|
| 靜默失效路徑數 | 0（Gate） | `grep -rn 'except' --include='*.py'` 後過濾無 logger 行 | ✅ 0（v0.6.0 修復後） |
| Migration 失敗可觀察率 | 100% | 故意破壞 schema v11 後執行 `brain doctor`，確認有 warning 輸出 | ✅ 已修復 |
| Chaos test 通過率 | 100%（Gate v0.7.0） | CI 自動執行 `tests/chaos/test_chaos_and_load.py` | ❌ 未接 CI（STAB-08） |
| SR node 追蹤準確率 | 誤判率 0% | 故意注入含 emoji 標題，確認 access_count 更新對象正確 | ✅ 已修復（STAB-07） |
| ReviewBoard.db 損壞恢復能力 | 有可操作錯誤訊息 | 故意損壞後確認 `brain review list` 給出可操作訊息而非 stack trace | ✅ 已修復（STAB-06） |

### 三、技術誠實性（Tech Honesty）

| 指標 | 門檻 | 量測方法 | v0.6.0 現況 |
|------|------|---------|------------|
| 功能狀態標記覆蓋率 | 100% | README 和 CHANGELOG 中每個功能是否有 🟢/🟡/🔴 標記 | ❌ 0%（TECH-01） |
| LoRA 路徑說明準確性 | 已標注 | README `brain distill` 說明是否含「需自行執行 Axolotl / Unsloth」 | ❌ 未更新（HON-01） |
| Synonym Map 條目數一致性 | 差距 ≤ 2 | `len(brain_db._SYNONYM_MAP)` vs `len(context.py._SYNONYM_MAP)` | ✅ 兩表均為 46 條（SYNC-01） |
| ANN 觸發條件文件化 | 已標注 | 安裝文件中是否標注「建議 > 2000 節點後切換 HNSW」 | ❌ 未標注（TECH-03） |
| 每版本宣稱 vs 實際審計 | 每版本執行 | 隨機抽查 3 個 CHANGELOG「完成」項目，確認有 commit hash + 行號 | ✅ v0.6.0 已執行一次（DIR-03 制度化中） |

### 四、飛輪（Flywheel）

| 指標 | 門檻 | 量測 SQL / 方法 | v0.6.0 現況 |
|------|------|--------------|------------|
| 知識庫自然成長率 | 7 天內 ≥ 5 節點（自動寫入） | `SELECT COUNT(*) FROM nodes WHERE tags LIKE '%auto:complete_task%' AND created_at >= datetime('now','-7 days')` | ❌ 0（未開始） |
| NudgeEngine 命中率 | ≥ 30%（> 20 節點後） | events 表 `nudge_triggered` 事件數 ÷ `get_context` 總呼叫數 | ❌ 0（未量測，FLY-04） |
| `get_context` 召回率 | ≥ 60%（sentence-transformers） | UNQ-03 基準測試資料集，50 節點 + 20 查詢 + 已知正確答案 | ✅ 95%（MultilingualEmbedder + hybrid search，2026-04-04）詳見 `tests/benchmarks/benchmark_recall.py` |
