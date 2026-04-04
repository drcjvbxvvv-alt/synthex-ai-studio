# Project Brain — 改善規劃書

> **當前版本**：v0.6.0（2026-04-04）
> **文件用途**：記錄未完成的改善方向與技術債。已完成項目見 `CHANGELOG.md`。
> **參考文件**：`ProjectBrain_Enterprise_Analysis.docx.md`（企業級產品價值分析）；`ProjectBrain_FiveDimension_Metrics.docx.md`（五維指標量測範本）

---

## 優先等級定義

| 等級   | 說明                               | 目標版本     |
| ------ | ---------------------------------- | ------------ |
| **P0** | 阻礙核心功能運作的缺陷，須立即修復 | 下一個 patch |
| **P1** | 影響使用者體驗的問題，應優先處理   | 下一個 minor |
| **P2** | 值得做但可延後的優化               | 計劃中       |
| **P3** | 長期願景、實驗性功能               | 評估中       |

---

## 待辦功能

### v0.6.0（飛輪啟動）

| ID       | 等級   | 項目                        | 說明                                                                                                                                                                                        |
| -------- | ------ | --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| FLY-03   | P2     | 知識庫健康度首頁            | `brain status` 輸出「知識庫評分」：節點數、最近 7 天新增數、最常被查到的 3 個 Pitfall。讓用戶看到飛輪在轉                                                                                   |
| REV-01   | **P1** | **建立自我驗證實驗**        | **v0.6.0 發布條件的數據來源。** 在同一個專案跑 30 天對照：Week 1~2 不用 Brain，Week 3~4 用 Brain。記錄 Agent 重複犯相同錯誤的次數、任務完成時間。這是 REV-03「可公開驗證報告」的必要前提    |
| REV-02   | P2     | 量測 Decay 實際效用         | 對比有衰減 vs 無衰減的知識庫，Agent 被導向過時知識的比例。數字必須存在，否則 F2/F3 只是假設                                                                                                 |
| REV-03   | P2     | 輸出可分享的驗證報告        | 哪怕 N=1 的個人專案，數字存在本身就是說服力。發表於 README 或 docs/                                                                                                                         |
| UNQ-03   | P2     | 持續品質基準測試            | 建立基準測試資料集（50 個節點、20 個查詢、已知正確答案），每個版本自動跑並記錄召回率與精確率。量測方法：`SELECT COUNT(*) FROM nodes` 搭配固定查詢集，目標召回率 ≥ 60%（sentence-transformers）/ ≥ 40%（LocalTFIDF） |
| DIR-01   | P2     | 補建驗收標準                | 為已完成的核心功能補建最低品質門檻：`get_context` 召回率 ≥ 60%；`complete_task` 正確寫入率 100%                                                                                             |
| DIR-02   | P2     | 區分完成狀態標記            | 凡功能需使用者自備工具、手動執行步驟才能使用，標記為「架構就緒 (Arch-Ready)」而非「完成 ✅」                                                                                                 |
| ~~STAB-06~~ | ~~P1~~ | ~~ReviewBoard.db 穩定性~~ | ✅ 完成 → CHANGELOG v0.6.0 |
| ~~STAB-07~~ | ~~P1~~ | ~~SR node ID 比對~~       | ✅ 完成 → CHANGELOG v0.6.0 |
| ~~HON-01~~  | ~~P2~~ | ~~README LoRA 說明~~      | N/A：`brain distill` 已於 v10.x 移除，無對象 |
| ~~SYNC-01~~ | ~~P2~~ | ~~Synonym Map 完全同步~~  | ✅ 完成：兩表均擴展至 46 條 → CHANGELOG v0.6.0 |

### v0.7.0（護城河強化）

| ID      | 等級   | 項目                        | 說明                                                                                                                                                                                                                                          |
| ------- | ------ | --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| MON-01  | P2     | 聯邦 bundle 加貢獻者標記    | `FederationBundle` 加 `contributor` 欄位（用 org/team 名稱）；匯入時保留來源，`brain status` 顯示「來自外部聯邦的節點數：N」                                                                                                                  |
| MON-02  | P2     | 公開知識模板庫               | 規劃官方 bundle 倉庫（GitHub repo），預置「通用後端 Pitfall 包」（JWT、Webhook、DB migration、Cache、CORS 各至少 3 條，共 20 條），降低冷啟動問題。**前置條件：MON-04 審核機制完成**                                                          |
| MON-04  | **P1** | **官方 bundle 審核機制**    | **MON-02 的前置條件，聯邦信任的根基。** 進入官方 bundle 的每條 Pitfall 必須：(1) 有可引用來源，(2) KRB 人工審核通過，(3) confidence ≥ 0.85，(4) 無 global scope 污染風險。設計審核流程文件並實作 `brain fed review` 指令                     |
| TECH-01 | P2     | 補建功能完成度標記           | 在 CHANGELOG / README 中對每個功能標記：`🟢 端對端可用` / `🟡 架構就緒（需使用者操作）` / `🔴 實驗性`。目標：標記覆蓋率 100%。現況：0%                                                                                                      |
| TECH-02 | P2     | LoRA 路徑誠實說明            | README 中明確：「`brain distill` 產生訓練用 JSONL 與設定檔，實際訓練需自行執行 Axolotl / Unsloth」（HON-01 已記為 v0.6.0 即時項目；TECH-02 為配套的 README 架構就緒標記）                                                                    |
| TECH-03 | P2     | ANN Index 觸發條件說明      | 文件標注：「HNSW 在節點數 < 1000 時效能與 LinearScan 相近，建議超過 2000 節點後切換」                                                                                                                                                         |
| STAB-08 | P2     | Chaos test 接入 CI gate     | `tests/chaos/test_chaos_and_load.py` 已存在但未接 CI 阻塞點。加入 `pyproject.toml` pytest 配置，使 Chaos test 成為每版本的硬性 gate。量測：CI 每次 push 自動執行，通過率 = 100% 才可合併                                                     |
| DIR-03  | P2     | 每版本隨機審計機制           | 每次發布前隨機抽查 CHANGELOG 裡 3 個「完成」項目，驗證程式碼裡有對應實作（commit hash + 行號）。v0.6.0 已執行一次（發現 graphiti_url 描述不精確）——制度化為發布清單的固定步驟                                                                |
| FLY-04  | P2     | NudgeEngine 命中率量測      | `get_context` 呼叫時 nudge 至少出現一次的比例 ≥ 30%（知識庫 > 20 節點後）。量測方法：events 表 `nudge_triggered` 事件數 ÷ `get_context` 總呼叫數。現況：0（未量測，`events` 表可能需新增）                                                  |
| FLY-05  | P2     | 知識庫自然成長率量測        | 不手動 `brain add` 的情況下，7 天內 `complete_task` 自動寫入的節點數 ≥ 5。量測 SQL：`SELECT COUNT(*) FROM nodes WHERE tags LIKE '%auto:complete_task%' AND created_at >= datetime('now','-7 days')`                                           |
| UNQ-02  | P3     | 競品差距量化追蹤             | 每季評估一次 MemCoder / Lore / Graphiti 的功能進度，記錄 Project Brain 的差異化點（F2 版本落差衰減、F3 git 活動反衰減、`complete_task` 閉環）是否仍然成立。建立 `docs/competitive-analysis.md`，每季更新                                      |

### v1.0.0（企業就緒）

| ID     | 等級 | 項目                     | 說明                                                                                                                                                                                        |
| ------ | ---- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| PH3-04 | P3   | Cloud 版本               | 託管服務、Team 計畫（$20/月/開發者）、計費系統                                                                                                                                              |
| MON-03 | P2   | 商業啟動計劃草案         | 第一批目標用戶：台灣 AI 輔助開發工程師（使用 Claude Code / Cursor 的個人開發者）。核心激勵：裝好 Brain 後 `brain fed import` 官方 bundle，第一天就有 20 條驗證過的 Pitfall，立刻感受到價值。草案記錄於獨立文件，不阻塞工程進度，但需在 v0.7.0 MON-02 完成前確定 bundle 內容與格式 |
| FLY-06 | P3   | Time to First Value 量測 | 從 `brain setup` 到第一次 `get_context` 返回有效 Pitfall 的時間 ≤ 48 小時（含冷啟動期）。**前置條件：MON-02 官方 bundle 存在**，`brain fed import official-bundle` 讓第一天就有 20 條。現況：bundle 未建立，無法量測 |

---

## 技術審計發現（2026-04-04 深度分析）

> 基於完整原始碼靜態分析（1797+ 行 brain_db.py、1100+ 行 mcp_server.py、900+ 行 context.py 等核心模組）。
> 本節 ID 格式為 `BUG-`/`ARCH-`/`PERF-`/`SEC-`/`REF-`/`DATA-`，對應 IMPROVEMENT_PLAN 內其他項目以交叉引用。

### 問題總覽

| ID      | 等級   | 類別     | 問題摘要                                     | 涉及檔案                   |
| ------- | ------ | -------- | -------------------------------------------- | -------------------------- |
| BUG-A01 | **P0** | 資料一致性 | scope 更新以 title 比對（非唯一），多節點被誤改 | `mcp_server.py` L403-412 |
| BUG-A02 | **P1** | 資料一致性 | FTS5 觸發器與手動同步並存，可能產生重複索引  | `brain_db.py` L507-514     |
| BUG-A03 | P2     | 並發      | double-checked locking 無 volatile 語意      | `engine.py` L87-101        |
| BUG-A04 | P2     | 資料一致性 | Federation 匯出 scope fallback 忽略 scope 過濾，可能洩漏本地節點 | `federation.py` L130-141 |
| BUG-A05 | P2     | 資安     | git branch 參數未驗證格式（使用者輸入）      | `mcp_server.py` L485-487   |
| ARCH-01 | **P1** | 架構耦合 | MCP server 直接 new BrainDB，繞過 ProjectBrain singleton | `mcp_server.py` L403 |
| ARCH-02 | P2     | 資源管理 | thread-local SQLite 連線無清理，長跑伺服器洩漏 fd | `brain_db.py` L88-99  |
| ARCH-03 | P2     | API 一致性 | `search_nodes` / `search_nodes_multi` 簽名不一致、回傳結構不同 | `graph.py` L400-547 |
| ARCH-04 | P2     | API 一致性 | scope 三路控制流（`--global` / `--scope` / 自動推斷）讓使用者困惑 | `cli.py` L381-395 |
| PERF-01 | P2     | 效能     | access_count 在迴圈內逐筆 UPDATE（N+1 寫入）  | `context.py` L297-303      |
| PERF-02 | P2     | 效能     | FTS5 排序含 CASE expression，大資料集全掃後排序 | `brain_db.py` L607-617   |
| PERF-03 | P3     | 效能     | CJK token 計數逐字迭代，無快取                | `context.py` L76-80        |
| SEC-01  | P2     | 資安     | scope filter 以 f-string 拼接 SQL（潛在注入） | `brain_db.py` L607-617     |
| SEC-02  | P2     | 資安     | symlink 不受路徑遍歷保護（`.resolve()` 後才驗證）| `mcp_server.py` L89-93  |
| SEC-03  | P3     | 資安     | PII 正則過於簡陋，漏抓 / 誤抓               | `federation.py` L33-35     |
| REF-01  | P2     | 重構     | BrainDB 1797 行，承擔 10+ 職責（God Object） | `brain_db.py`              |
| REF-02  | P2     | 重構     | Synonym Map 複製於兩處，「master copy」說明矛盾 | `brain_db.py` + `context.py` |
| REF-03  | P2     | 重構     | `_write_guard()` 使用 fcntl（不跨平台，已有 WAL 足夠） | `brain_db.py` L361-405 |
| REF-04  | P3     | 重構     | Magic numbers 散落（`0.003`、`800`、`limit=8` 等）| 多個檔案            |
| DATA-01 | P2     | 資料一致性 | 節點刪除時邊的 cascade 無審計日誌            | `brain_db.py` L125-129     |
| DATA-02 | P2     | 資料一致性 | Migration 失敗後 schema version 仍遞增，破壞未來遷移 | `brain_db.py` L226-310 |

---

### 詳細分析

#### BUG-A01：scope 更新以 title 比對（P0）

**根本原因**：`mcp_server.py` 中 `add_knowledge` 新增節點後，以 `WHERE title=?` 更新 scope，但 title 不唯一——兩個相同標題的節點（不同 scope）會同時被改寫。

```python
# 現況（危險）
_db.conn.execute("UPDATE nodes SET scope=? WHERE title=?", (scope, title_c))

# 修法：add_node 回傳 node_id 後直接用 id 更新
_db.conn.execute("UPDATE nodes SET scope=? WHERE id=?", (scope, node_id))
```

**解決方案**：`add_knowledge` 取得 `add_node()` 回傳的 `node_id`，改用 `WHERE id=?`；加入 `logger.warning` 取代 `except Exception: pass`。

---

#### BUG-A02：FTS5 觸發器 + 手動同步並存（P1）

**根本原因**：`_setup()` 建立了 `nodes_fts_insert` / `nodes_fts_delete` 觸發器，但 `add_node()` 又手動執行 `DELETE FROM nodes_fts` + `INSERT INTO nodes_fts`。`INSERT OR REPLACE INTO nodes` 觸發 delete+insert 觸發器，再加上手動同步，可能產生重複 FTS5 row。

**解決方案**：選一。建議保留手動同步（更可控），刪除觸發器，在 migration 中 `DROP TRIGGER IF EXISTS`。

---

#### ARCH-01：MCP Server 直接 new BrainDB（P1）

**根本原因**：`add_knowledge`、`search_knowledge` 等 MCP 工具裡有 `_db = BrainDB(_bdir)` 直接實例化，繞過了 `ProjectBrain.db` singleton，造成多個 writer 同時持有 WAL lock。

**解決方案**：統一透過 `b = _resolve_brain(workdir); db = b.db` 取得 BrainDB 實例，不在工具內自行 new。

---

#### ARCH-02：thread-local 連線無清理（P2）

**根本原因**：`BrainDB.conn` 以 `threading.local()` 儲存每執行緒的連線，執行緒結束時 Python 不保證呼叫 `__del__`，file descriptor 不會釋放。在 `api_server.py` 每請求一執行緒的場景下，長跑會耗盡 fd。

**解決方案**：改用單一 `check_same_thread=False` 連線加 `threading.RLock`（已有 `_write_guard`，套用即可），或在 `api_server.py` handler 完成後顯式 `close()`。

---

#### SEC-01：scope filter f-string SQL 拼接（P2）

**根本原因**：`search_nodes()` 的 scope 過濾以字串拼接：

```python
sf = " AND n.scope=?" if scope else ""
# ... f" WHERE nodes_fts MATCH ? {sf} ..."
```

`sf` 本身不含使用者輸入，但其他呼叫者傳入的 `scope` 值理論上可觸達。

**解決方案**：改為完整參數化查詢；明確驗證 scope 只含 `[a-z0-9_]`，不接受任意字串。

---

#### REF-01：BrainDB God Object（P2）

BrainDB（1797 行）承擔 schema 遷移、FTS5 tokenizer、同義詞展開、write lock、節點 CRUD、episode、feedback、歷史快照、衰減計算、vector 搜尋等超過 10 個職責，違反單一職責。

**建議拆分方向**（不需一次做完，可逐步重構）：

| 類別 | 職責 | 目標類別名 |
|------|------|-----------|
| Schema | `_setup()` + migrations | `BrainSchema` |
| 文字處理 | `_ngram()` + `_sanitize_fts()` | `TextProcessor` |
| 同義詞 | `_SYNONYM_MAP` + `build_synonym_index()` | `SynonymIndex`（獨立模組） |
| Write lock | `_write_guard()` | 內聯至 `conn`，或刪除（WAL 足夠） |
| Feedback | `record_feedback()` | `FeedbackTracker` |
| Vector | `add_vector()` + `search_nodes_by_vector()` | `VectorStore` |

---

#### REF-02：Synonym Map 兩份（P2）

`brain_db.py` 和 `context.py` 各有一份 `_SYNONYM_MAP`，注解相互指向對方為「master copy」，邏輯矛盾。SYNC-01 雖已同步至 46 條，但下次修改仍需同時改兩處。

**解決方案**：新增 `project_brain/synonyms.py`，兩處改為 `from .synonyms import SYNONYM_MAP`。

---

#### REF-03：`_write_guard()` 的 fcntl 已非必要（P2）

SQLite WAL 模式 + `PRAGMA busy_timeout` 已提供跨進程寫入串列化。`fcntl.flock()` 在 macOS 的 NFS / APFS 下行為不一致，且每次寫入增加 1-2ms syscall。

**解決方案**：移除 `fcntl` 相關程式碼，依賴 SQLite WAL + busy_timeout（目前已設 5000ms）。

---

#### DATA-02：Migration version 在失敗後仍遞增（P2）

`_run_migrations()` 的 except 區塊記 warning 後繼續執行，`schema_version` 照常 +1。下次啟動時，失敗的 migration 被視為已完成而跳過，導致 schema 永久損壞。

**解決方案**：失敗的 migration 不遞增 version；可考慮引入 `migration_log` 表記錄每次遷移的實際結果（success / failure / skipped）。

---

### 修復優先順序（建議納入 v0.7.0）

```
P0（立即）：BUG-A01（title-based scope update）
P1（v0.7.0）：BUG-A02（FTS5 dual sync）、ARCH-01（BrainDB singleton bypass）
P2（v0.7.0~v1.0.0）：SEC-01、ARCH-02、ARCH-03、PERF-01、DATA-02、REF-02、REF-03
P3（backlog）：PERF-03、SEC-03、REF-04
```

---

## 待辦技術改善

| 優先 | ID      | 項目                          | 說明                                                                                             | 涉及檔案                      |
| ---- | ------- | ----------------------------- | ------------------------------------------------------------------------------------------------ | ----------------------------- |
| P0   | BUG-A01 | scope 更新改用 node_id        | `add_knowledge` 以 `WHERE id=?` 取代 `WHERE title=?`；加 logger.warning                         | `mcp_server.py`               |
| P1   | BUG-A02 | 移除 FTS5 觸發器              | 刪除 `nodes_fts_insert/delete` 觸發器，統一走手動同步，加 migration 清除舊觸發器                 | `brain_db.py`                 |
| P1   | ARCH-01 | BrainDB 透過 singleton 存取   | MCP 工具內改用 `b.db`，不直接 `new BrainDB`                                                      | `mcp_server.py`               |
| P2   | SEC-01  | scope filter 參數化           | 用完整參數化查詢取代 f-string 拼接；`scope` 值白名單驗證                                         | `brain_db.py`                 |
| P2   | ARCH-02 | thread-local 連線清理         | API server handler 結束時 close connection，或改用單一帶鎖連線                                   | `brain_db.py`, `api_server.py`|
| P2   | ARCH-03 | 統一 graph 搜尋 API           | `search_nodes` / `search_nodes_multi` 合併為單一函式，統一回傳結構與 scope 支援                  | `graph.py`                    |
| P2   | PERF-01 | access_count 批次 UPDATE      | 收集節點 ID 清單，context 組裝完後一次 `UPDATE ... WHERE id IN (...)`                            | `context.py`                  |
| P2   | DATA-02 | Migration 失敗不遞增 version  | except 區塊內不執行 `schema_version += 1`；引入 `migration_log` 表                               | `brain_db.py`                 |
| P2   | REF-02  | Synonym Map 獨立模組          | 新增 `synonyms.py`，`brain_db.py` / `context.py` 共同 import                                    | `brain_db.py`, `context.py`   |
| P2   | REF-03  | 移除 fcntl write lock         | 依賴 SQLite WAL + busy_timeout，刪除 `fcntl.flock()` 相關程式碼                                  | `brain_db.py`                 |
| P2   | BUG-A04 | Federation export scope 驗證  | 匯出前明確檢查 scope column 存在；fallback 必須維持 scope 過濾                                   | `federation.py`               |
| P2   | BUG-A05 | git branch 名稱驗證           | 加 `^[a-zA-Z0-9._\-/]+$` 正則驗證；非法值回傳 error 而非執行                                   | `mcp_server.py`               |
| P3   | REF-01  | BrainDB 拆分（逐步）          | 優先抽 `VectorStore`（add_vector/search_by_vector）和 `FeedbackTracker`（record_feedback）       | `brain_db.py`                 |
| P3   | PERF-02 | FTS5 排序複合索引             | 加 `(is_pinned DESC, confidence DESC)` 複合索引                                                  | `brain_db.py`                 |
| P3   | ARCH-04 | scope 控制流簡化              | 合併 `--global` / `--scope` 為單一 `--scope global`；保留自動推斷                               | `cli.py`                      |
| P3   | REF-04  | 魔法數字集中管理              | 新增 `constants.py`，遷入 `limit=8`、`budget=800`、`0.003` 衰減率等                             | 多個檔案                      |
| P3   | DATA-01 | 節點刪除審計日誌              | `delete_node()` 寫入 `node_history` 或 `events` 表，記錄被 cascade 刪除的 edge 清單             | `brain_db.py`                 |
| P3   | SEC-02  | symlink 路徑遍歷              | `resolve(strict=True)` 或在 resolve 前先驗證                                                     | `mcp_server.py`               |
| P3   | SEC-03  | PII 正則加強                  | 引入 Microsoft Presidio 或 spaCy NER 作為 PII 偵測後端（可選依賴）                              | `federation.py`               |
| P3   | PERF-03 | CJK token 計數快取            | `_count_tokens()` 加 `lru_cache`                                                                 | `context.py`                  |
| P3   | —       | 合併兩套資料庫                | `knowledge_graph.db` 遷入 `brain.db`，消除雙庫一致性風險                                        | `graph.py`, `brain_db.py`     |

---

## 版本路線圖

| 版本      | 主題       | 鎖定目標                                                                                                                                                                          | 發布條件（Gate）                                                                                                             |
| --------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| **v0.6.0**| 飛輪啟動   | FLY-03 + **REV-01**（必要）+ UNQ-03 + STAB-06 + STAB-07 + HON-01 + SYNC-01 + DIR-01~02                                                                                          | REV-01 對照實驗完成並有數據；靜默失效路徑數 = 0；ReviewBoard.db 損壞可恢復；SR node ID 比對完成                              |
| **v0.7.0**| 護城河強化 | **MON-04**（必要）+ MON-01~02 + MON-03 草案確認 + TECH-01~03 + STAB-08 + DIR-03 + FLY-04~05 + UNQ-02 + **BUG-A01**（P0）+ **BUG-A02**（P1）+ **ARCH-01**（P1）+ SEC-01 + PERF-01 + DATA-02 + REF-02~03 | 所有 P0/P1 audit 項目修復；聯邦 bundle 可第三方驗證；Chaos test 接 CI；NudgeEngine 命中率有量測數據 |
| **v1.0.0**| 企業就緒   | PH3-04 Cloud 基礎架構 + FLY-06 Time to First Value + UNQ-02 季度更新 + REV-03 可公開驗證報告 + REF-01 BrainDB 拆分（VectorStore/FeedbackTracker）+ ARCH-02~04 + PERF-02          | 內外部 QA 通過；知識庫真實專案跑滿 30 天數據；Time to First Value ≤ 48hr；BrainDB ≤ 800 行                                  |

---

## 五維指標量測基準（v0.6.0）

> 每個 minor 版本發布前執行完整核查。Gate 條件欄位為硬性阻塞點，不可跳過。
> 完整說明見 `ProjectBrain_FiveDimension_Metrics.docx.md`。

### 一、走向（Direction）

| 指標                      | 門檻            | 量測方法                                                                      | v0.6.0 現況 |
| ------------------------- | --------------- | ----------------------------------------------------------------------------- | ----------- |
| 版本發布條件達成率        | 100%（Gate）    | CHANGELOG 每版本 Gate checklist 完成數 ÷ 總數                                 | ✅ 達成      |
| 計劃打勾 vs 程式碼完成率  | 100%            | 每版本 code review 隨機抽查 5 項，確認有 commit hash + 行號可查               | △ 發現 graphiti_url 描述不精確 |
| 技術債清零週期            | P0 ≤ 當版本；其餘 ≤ 2 版本 | IMPROVEMENT_PLAN 歷史紀錄，計算每個 Bug ID 從出現到 ✅ 的版本跨距 | ✅ 符合       |
| Arch-Ready vs 端對端比例  | ≥ 70%           | 功能表中 🟢 端對端可用 ÷ (🟢 + 🟡 架構就緒)                                  | ❌ 待 TECH-01 完成後量測 |
| 版本週期一致性            | 相鄰版本完成數差距 ≤ 30% | CHANGELOG 各版本 completed items 數量統計                           | ❌ 未量測    |

### 二、穩定性（Stability）

| 指標                         | 門檻             | 量測方法                                                                                     | v0.6.0 現況 |
| ---------------------------- | ---------------- | -------------------------------------------------------------------------------------------- | ----------- |
| 靜默失效路徑數               | 0（Gate）        | `grep -rn 'except' --include='*.py'` 後過濾無 logger 行                                     | ✅ 0（v0.6.0 修復後） |
| Migration 失敗可觀察率       | 100%             | 故意破壞 schema v11 後執行 `brain doctor`，確認有 warning 輸出                               | ✅ 已修復    |
| Chaos test 通過率            | 100%（Gate v0.7.0）| CI 自動執行 `tests/chaos/test_chaos_and_load.py`                                           | ❌ 未接 CI（STAB-08） |
| SR node 追蹤準確率           | 誤判率 0%        | 故意注入含 emoji 標題，確認 access_count 更新對象正確                                        | ✅ 已修復（STAB-07） |
| ReviewBoard.db 損壞恢復能力  | 有可操作錯誤訊息 | 故意損壞 review_board.db 後，確認 `brain review list` 給出可操作訊息而非 stack trace         | ✅ 已修復（STAB-06）|

### 三、新技術誠實性（Tech Honesty）

| 指標                       | 門檻     | 量測方法                                                                | v0.6.0 現況 |
| -------------------------- | -------- | ----------------------------------------------------------------------- | ----------- |
| 功能狀態標記覆蓋率         | 100%     | README 和 CHANGELOG 中每個功能是否有 🟢/🟡/🔴 標記                     | ❌ 0%（TECH-01） |
| LoRA 路徑說明準確性        | 已標注   | README `brain distill` 說明是否含「需自行執行 Axolotl / Unsloth」      | ❌ 未更新（HON-01） |
| Synonym Map 條目數一致性   | 差距 ≤ 2 | `len(brain_db._SYNONYM_MAP)` vs `len(context.py._SYNONYM_MAP)`         | ✅ 兩表均為 46 條（SYNC-01） |
| ANN 觸發條件文件化         | 已標注   | 安裝文件中是否標注「建議 > 2000 節點後切換 HNSW」                      | ❌ 未標注（TECH-03） |
| 每版本宣稱 vs 實際審計     | 每版本執行 | 隨機抽查 3 個 CHANGELOG「完成」項目，確認有 commit hash + 行號        | ✅ v0.6.0 已執行一次（DIR-03 制度化中） |

### 四、未來性 — 飛輪（Flywheel）

| 指標                       | 門檻                           | 量測 SQL / 方法                                                                                         | v0.6.0 現況 |
| -------------------------- | ------------------------------ | ------------------------------------------------------------------------------------------------------- | ----------- |
| 知識庫自然成長率           | 7 天內 ≥ 5 節點（自動寫入）    | `SELECT COUNT(*) FROM nodes WHERE tags LIKE '%auto:complete_task%' AND created_at >= datetime('now','-7 days')` | ❌ 0（未開始） |
| NudgeEngine 命中率         | ≥ 30%（> 20 節點後）           | events 表 `nudge_triggered` 事件數 ÷ `get_context` 總呼叫數                                            | ❌ 0（未量測，FLY-04） |
| REV-01 對照實驗完成        | 有可量化輸出（Gate v0.6.0）    | Agent 重複犯錯次數（無 Brain）vs（有 Brain）的差值                                                     | ❌ 尚未開始 |
| `get_context` 召回率       | ≥ 60%（sentence-transformers）| UNQ-03 基準測試資料集，50 節點 + 20 查詢 + 已知正確答案                                                | ✅ 95%（MultilingualEmbedder + hybrid search，2026-04-04）詳見 `tests/benchmarks/benchmark_recall.py` |
| Time to First Value        | ≤ 48 小時（v1.0.0）            | `brain setup` → 第一次 `get_context` 返回有效 Pitfall 的時間                                          | ❌ bundle 未建立（FLY-06） |

### 五、壟斷策略（Moat）

| 指標                       | 門檻                        | 量測方法                                                                                 | v0.6.0 現況 |
| -------------------------- | --------------------------- | ---------------------------------------------------------------------------------------- | ----------- |
| 官方 bundle 覆蓋率         | 20 條（v0.7.0 Gate）        | JWT / Webhook / DB migration / Cache / CORS 各 ≥ 3 條，每條有可引用來源                 | ❌ 0 條     |
| 聯邦知識去重率             | ≤ 20%（cos similarity > 0.85）| `brain fed import` 時的 dedup 報告                                                    | ❌ 未量測   |
| 第三方引用數               | ≥ 1（v0.7.0 Gate）          | GitHub release download 數量估算                                                         | ❌ 0        |
| 官方 bundle 審核機制       | 已設計（Gate for MON-02）   | 審核流程文件 + `brain fed review` 指令實作                                               | ❌ 未設計（MON-04） |
| 競品差距量化追蹤           | 每季更新                    | `docs/competitive-analysis.md`：MemCoder / Lore / Graphiti 功能比對                    | ❌ 未建立（UNQ-02） |

---

## 系統深度評估報告（2026-04-04，v0.6.0 後）

> 基於完整原始碼靜態分析（含 v0.6.0 修復後的實際狀態）。評分為 1–10，反映現實狀況而非設計意圖。

### 總覽

| 維度                   | 評分       | 主要待辦問題                                                              |
| ---------------------- | ---------- | ------------------------------------------------------------------------- |
| 可靠度（Reliability）  | 8.5 / 10   | Chaos test 未接 CI gate（STAB-08）                                        |
| 實用性（Practicality） | 7.5 / 10   | Federation bundle 無匯出時間戳；SR node ID 追蹤不準確                     |
| 可用性（Usability）    | 7.0 / 10   | `brain init` 後無自我測試；錯誤訊息仍不夠精準                             |
| 誠實性（Honesty）      | 7.0 / 10   | 信心賦值任意（`brain add` 預設 0.8 無依據）；用戶無提示                   |
| 記憶檢索品質           | 6.0 / 10   | SR node 追蹤脆弱；DEDUP=0.85 偏保守；embedding 不持久化                   |
| 系統架構               | 6.5 / 10   | 兩套並行資料庫（knowledge_graph.db + brain.db）；ReviewBoard.db 無 schema 版控 |
| 成本控制與資源消耗     | 7.5 / 10   | Embedding 無持久化快取；每次重啟重新計算                                  |
| 程式碼與工程穩定性     | 6.5 / 10   | Magic numbers 散落（`max_c=800`、`access×0.04`）                          |
| **綜合評分**           | **7.1/10** | STAB-06/07 + SYNC-01 再提升 ~0.1 分；剩餘主要風險：Chaos test 未接 CI   |

---

### 1. 可靠度（Reliability）8.0 / 10

**改善（v0.5.0 ~ v0.6.0）**
- STB-01~05 修復：BrainDB 初始化失敗改為 `logging.warning`；`access_count` 遞增失敗改為 `logging.debug`
- 過期知識加 ⏰ 標記；Context 截斷加 ⚠ 提示；`brain add` 落為 global 時加警告
- Migration 迴圈異常改為 `logger.warning`（`already exists`/`duplicate column` 記 debug，其餘記 warning）
- `context.py` 4 處 `except: pass` 全數加 `logger.debug`（dedup / SR 外層 / causal chain / reasoning chain）

**改善（v0.6.0 STAB-07）**
- SR node 追蹤改用 `_shown_node_ids`（build() 入口統一追蹤），消除 title 子字串比對誤判；access_count 遞增移至 budget 確認後，修正截斷節點被錯誤計為已訪問的舊 bug

**仍存在的問題**

| 位置 | 問題 | 後果 |
| ---- | ---- | ---- |
| `tests/chaos/` | Chaos test 未接 CI gate | 每版本手動執行，容易遺漏（STAB-08） |

---

### 2. 實用性（Practicality）7.5 / 10

**改善（v0.5.0 ~ v0.6.0）**
- FLY-01：空 Brain 冷啟動回傳引導訊息
- FLY-02：`_infer_scope` 優先 git remote → 子目錄 → workdir 名稱
- NudgeEngine 補接 BrainDB：`brain add` 手動加入的 Pitfall 現在可觸發主動提醒
- Synonym Map 同步：`brain_db._SYNONYM_MAP` 擴展至 32 條，`search_knowledge` 與 `get_context` 語義擴展不再不對稱

**仍存在的問題**
- **Federation bundle 無匯出時間戳**：`federation.py:114-150` 匯出節點不含 `exported_at` 欄位，匯入方無法判斷資料新鮮度
- **SR node ID 追蹤用標題子字串比對**（`context.py:316`）：`n['title'] in result` 在含截斷或 emoji 的輸出中易誤判，造成 access_count 更新對象錯誤

---

### 3. 可用性（Usability）7.0 / 10

**優點**
- `_workdir` 仿 git 向上查找 `.brain/`，符合開發者直覺
- 輸入驗證完善（型別檢查、長度限制、路徑穿越防護）
- 常見打字錯誤自動修正
- `brain config` 指令：一個指令顯示並驗證所有 6 處設定來源，含敏感值自動遮蔽

**待辦**
- `brain init` 成功後不自我測試（寫入測試節點、查詢、刪除）
- 錯誤訊息仍不夠精準：BrainDB 失敗只顯示「Brain 尚未初始化」即使已初始化

---

### 4. 誠實性（Honesty）7.0 / 10

**改善（v0.5.0 ~ v0.6.0）**
- `Nudge.to_dict()` 已含 `confidence_label`（`nudge_engine.py:57`），API 回應可見信心等級
- Nudge 注入 context 時加入 `[conf=X.XX]` 標記；urgency=high 用 ⚠，其餘用 ℹ
- Decay 即時化：`_node_priority` 內即時套用 F1（時間衰減）+ F7（使用頻率加成），不再依賴 `brain decay`

**仍存在的問題**
- **信心賦值任意**：`brain add` 預設 0.8、AI 提取預設 0.5~0.6，均無依據；用戶無提示說明各信心值含義

---

### 5. 記憶檢索品質 6.0 / 10

**改善（v0.5.0 ~ v0.6.0）**
- `_search_batch` 嘗試向量 embedding 後做 `hybrid_search`，FTS5 為備援
- BrainDB + KnowledgeGraph 結果合併去重（BUG-09 fix）
- Synonym Map 同步：兩個入口的語義擴展不對稱問題消除

**仍存在的問題**
- **SR node 追蹤脆弱**（`context.py:316`）：title 子字串比對對截斷文字失效，實際 access_count 累積不準確
- **DEDUP_THRESHOLD=0.85** 預設值偏保守，0.80 相似的節點雙雙進 context，語義重複率高
- **embedding 不持久化**：每次重啟重新 embed 所有節點，sentence-transformers 首次載入數秒

---

### 6. 系統架構 6.5 / 10

**優點**
- 三層記憶（L3/L2/L1）職責分明
- `engine.py` 所有屬性懶初始化 + double-checked lock，避免死鎖
- BrainDB schema v11，versioned migrations，可重入
- `engine.py` 死碼清理：`graphiti_url`/redis 殘留已移除

**待辦**
- **兩套並行資料庫**：`knowledge_graph.db`（graph.py）與 `brain.db`（brain_db.py）各自維護 nodes + edges；`context.py` 必須同時查兩庫再合併
- ~~**ReviewBoard.db 獨立**：無 schema 版本控制，損壞無遷移路徑~~ → ✅ STAB-06 已修復

---

### 7. 成本控制與資源消耗 7.5 / 10

**優點**
- API 呼叫上限可設定（`BRAIN_RATE_LIMIT_RPM=60`）
- Embedding 本地優先（multilingual → Ollama → OpenAI → LocalTFIDF）
- Rate limiter 有 threading.Lock 保護（BUG-04 fix）
- `nodes(scope, confidence)` 複合索引（schema v11）：10k 節點下查詢延遲 < 50ms
- `brain optimize --prune-episodes`：支援清理超過 N 天的 L2 episode 記錄

**待辦**
- **Embedding 無持久化快取**：每次重啟重新計算，sentence-transformers 首次載入浪費啟動時間

---

### 8. 程式碼與工程穩定性 6.5 / 10

**優點**
- `from __future__ import annotations` + 型別提示廣泛
- Chaos testing 存在（`tests/chaos/`）
- `context.py` 公開方法有 docstring
- 死碼清理：空 for 迴圈、未用 import、graphiti/redis 殘留均已移除
- `NodeDict` TypedDict：`_node_priority` 等內部方法有靜態型別支撐
- 測試覆蓋率門檻：三個主要入口納入統計，`fail_under = 50`

**仍存在的問題**
- **Magic numbers 散落**：`context.py:248`（`max_c=800`/`400`）、`decay_engine.py:302`（`access×0.04`）均未定名為常數

---

## 戰略七維評估（2026-04-04，v0.6.0 後）

| 維度         | 評價                                                                   | 關鍵行動                                         |
| ------------ | ---------------------------------------------------------------------- | ------------------------------------------------ |
| 專案走向     | v0.6.0 完成所有 P1/P2/P3 修復；從 MVP 品質向 Beta 穩定過渡            | REV-01 對照實驗是 v0.6.0 正式發布的最後阻塞點   |
| 穩定性       | 8.5/10，靜默失效消除；SR node 追蹤修正；ReviewBoard.db 版控完善         | STAB-06/07 已完成，剩餘風險：Chaos test 未接 CI  |
| 革命性       | REV-01~03 驗證路徑已規劃；需數據支撐衰減因子的實際效用                 | REV-01 對照實驗待執行；30 天數據是可信度關鍵    |
| 新技術       | Synonym Map 已同步；TypedDict 已加；技術誠實性標記（TECH-01~03）待補   | TECH-01：在 CHANGELOG/README 補全端對端可用標記  |
| 未來性       | FLY-01~02 已落地；NudgeEngine + BrainDB 貫通；飛輪路徑完整             | FLY-03 知識庫健康度首頁是 v0.6.0 最後一項功能   |
| 壟斷潛力     | MON-01~02 護城河基礎設施已規劃；bundle 20 條內容待定                   | MON-02 bundle 內容與格式需在 v0.7.0 前確定       |
| 獨一無二性   | UNQ-02~03 + DIR-01 量化機制框架已建立；基準測試資料集待執行            | DIR-01 召回率門檻需明確 embedding 測試環境       |

---

## 版本決策記錄

| 版本   | 決策                                                       | 理由                                                   |
| ------ | ---------------------------------------------------------- | ------------------------------------------------------ |
| v0.6.0 | 全面清除靜默失效路徑，補齊 NudgeEngine + BrainDB 缺口      | 飛輪要轉，所有進入點必須一致；可觀察性是信任的前提。**✅ 測試保護**：`test_arch_decisions_v06.py::TestNudgeEngineSilentFailureElimination`（4 個測試） |
| v0.6.0 | Synonym Map 兩表均擴展至 **46 條**，keys 完全一致          | 兩個查詢入口不對稱讓 `search_knowledge` 成為二等公民。**✅ 測試保護**：`test_arch_decisions_v06.py::TestSynonymMapSync`（3 個測試） |
| v0.6.0 | `brain config` 單一指令顯示所有 6 處設定來源               | 設定分散是 debug 地獄；統一入口降低用戶認知負擔。**✅ 測試保護**：`test_arch_decisions_v06.py::TestBrainConfigSixSources`（3 個測試） |
| v0.6.0 | `review_board.db` 加 `schema_meta` 表追蹤版本；DB 損壞轉為 `RuntimeError` 含 `brain doctor` 提示 | 所有 DB 都需版本可追蹤；stack trace 對使用者毫無意義。**✅ 測試保護**：`test_arch_decisions_v06.py::TestReviewBoardSchemaVersion`（4 個測試） |
| v0.6.0 | SR access_count 遞增移至 `_add_if_budget` 之後，用 `_shown_node_ids` 取代 title 子字串比對 | title 比對在含截斷/emoji 時必然誤判；budget 截斷前遞增是邏輯錯誤。**✅ 測試保護**：`test_arch_decisions_v06.py::TestSRShownNodeIds`（3 個測試） |
| v0.5.0 | STB/FLY 修復優先於新功能                                   | 靜默失效比崩潰更危險，信任建立先於功能擴展。**✅ 測試保護**：`test_arch_decisions_v05.py`（12 個測試：STB-04 global 警告、FLY-01 冷啟動引導、FLY-02 scope 推斷優先序） |
| v0.3.0 | OllamaClient duck-typed，不強制 anthropic SDK              | 讓 KRB 審核可離線運行，降低企業採購門檻。**✅ 測試保護**：`test_arch_decisions_v03.py::TestOllamaClientDuckTyped`（4 個測試） |
| v0.3.0 | MultilingualEmbedder 優先級高於 Ollama embedder            | sentence-transformers 對中英混搜效果顯著優於 nomic。**✅ 測試保護**：`test_arch_decisions_v03.py::TestMultilingualEmbedderPriority`（3 個測試） |
| v0.3.0 | federation export 時清理 PII，而非 import 時               | bundle 本身即安全，接收方無需信任發送方的清理。**✅ 測試保護**：`test_arch_decisions_v03.py::TestFederationPIIOnExport`（5 個測試） |
| ~~v0.3.0~~ | ~~LoRA 訓練設定生成三套（Axolotl / Unsloth / LLaMA-Factory）~~ | ~~不綁定單一框架，使用者選擇熟悉工具~~ **（`brain distill` 已於 v10.x 移除，此決策已失效）** |
| v0.3.0 | ANN index fallback 為 LinearScan（純 Python）              | sqlite-vec 是 C 擴充，確保零依賴環境仍可運作。**✅ 測試保護**：`test_arch_decisions_v03.py::TestANNIndexFallback`（4 個測試） |
| v0.2.0 | `BRAIN_WORKDIR` 改為非必要（自動偵測為主）                 | 多專案工作流不應被環境變數綁死。**✅ 測試保護**：`test_arch_decisions_v02.py::TestBrainWorkdirDecision`（6 個測試） |
| v0.2.0 | 查詢展開限每詞 3 個同義詞，總上限 15                       | 原本 30 個同義詞造成大量無關結果。**✅ 測試保護**：`test_arch_decisions_v02.py::TestQueryExpansionDecision`（7 個測試） |
| v0.1.0 | 使用 SQLite WAL 而非 PostgreSQL                            | 零依賴部署，備份 = 複製一個文件。**✅ 測試保護**：`test_arch_decisions_v01.py::TestWALDecision`（3 個測試） |
| v0.1.0 | 知識衰減不刪除節點，只降低可見度                           | 歷史記錄有考古價值，刪除不可逆。**✅ 測試保護**：`test_arch_decisions_v01.py::TestDecayNoDeleteDecision`（5 個測試） |

---

## 如何使用此文件

1. **發現問題** → 加入「待辦技術改善」表格，標記等級
2. **想到新功能** → 加入對應版本的「待辦功能」，標記等級
3. **開始實作某項** → 在描述後加 `🚧 進行中`
4. **完成** → 移至 `CHANGELOG.md`，從本文件移除
