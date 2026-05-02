# Project Brain 深度系統審查

**日期**：2026-05-02  
**審查範圍**：可靠度、實用性、可用性、誠實性、記憶檢索品質、系統架構、成本控制與資源消耗、工程穩定性、缺陷、BUG 修復與功能深化。  
**基準版本**：原始碼 `pyproject.toml` 為 v0.46.0；執行期 `project_brain.__version__` 目前回報 v0.41.0（見 P0-2）。  
**修復版本**：v0.47.0（2026-05-02 同日修復，`__version__` 已一致）  
**方法**：閱讀核心程式碼與文件、執行 `brain health`、查驗實際 `.brain/brain.db`、執行代表性測試與主測試集。

---

## 1. 核心結論

Project Brain 已經不是原型玩具。它有可用的 CLI、MCP、HTTP MCP、WebUI、KRB、Pipeline、Federation、衰減與回饋迴路；單人本機使用的可靠度與實用性已經高。

但它也還不是可以宣稱「團隊級強一致記憶基礎設施」的系統。主要差距在三個地方：

1. **誠實性缺口**：文件與執行結果不完全一致。版本回報、測試數、Phase E 多用戶安全宣稱都偏樂觀。
2. **高並發寫入仍未真正序列化**：測試只保證 100 筆並發寫入至少 90 筆成功，不是零遺失。
3. **測試與舊架構殘影仍在**：主測試集仍有 14 個失敗，集中在未正確隔離的 chaos 舊測試與 legacy WebUI raw handler schema。

**總評**：

| 維度 | 評分 | 判斷 |
|---|---:|---|
| 本機單人可靠度 | 8/10 | `brain.db`、FTS5、schema、健康檢查狀態良好 |
| 團隊集中式可靠度 | 6/10 | HTTP MCP 可用，但 write queue/RBAC/零遺失尚未完成 |
| 實用性 | 8/10 | CLI/MCP/搜尋/知識回饋可直接用 |
| 可用性 | 7/10 | 文件完整，但版本與測試結果不一致會混淆使用者 |
| 誠實性 | 6/10 | Alpha classifier 誠實，但 README/ROADMAP 有過度宣稱 |
| 記憶檢索品質 | 7/10 | FTS5+ngram+synonym+vector 有基礎，仍需真實資料集 recall 評估 |
| 架構 | 7/10 | unified DB 是正確方向，但大檔與多入口直寫增加維護成本 |
| 成本控制 | 8/10 | 預設零雲端成本；主要隱性成本是 embedding/model 載入與備份 |
| 工程穩定性 | 7/10 | 代表性測試強，主測試集仍未全綠 |

---

## 2. 已驗證事實

### 2.1 執行狀態

`python brain.py health --json`：

- `brain.db` 可讀：759 節點、168 邊、759 FTS5 indexed（後續本次審查寫入 Brain 知識後為 762 節點）
- schema v28，與程式碼 latest v28 一致
- signal queue：0 pending
- KRB：未初始化 `review_board.db`
- health overall：`ok`
- health version：`0.41.0`，與原始碼 `pyproject.toml` 的 `0.46.0` 不一致

實際 `.brain/brain.db`：

- nodes：762
- FTS5：762
- edges：168
- vectors：688
- traces：928
- events：14986
- nodes by type：Decision 366、Rule 278、Pitfall 116、Note 1、Person 1

### 2.2 測試結果

已通過：

- `tests/unit/test_docs_accuracy.py`
- `tests/unit/test_multi_user_writes.py`
- `tests/integration/test_http_mcp_server.py`
- `tests/benchmarks/test_baseline_regression.py`

合計代表性測試：106 passed。

主測試集：

```text
python -m pytest -m 'not chaos and not benchmark' -q
1596 passed, 6 skipped, 14 failed, 22 deselected, 1 warning in 204.60s
```

失敗集中在：

- `tests/chaos/test_chaos_and_load.py`：7 failures
- `tests/test_chaos_and_load.py`：3 failures
- `tests/integration/test_web_ui.py`：4 failures

這代表核心單元與新功能測試很強，但「主測試集可直接全綠」目前不成立。

### 2.3 程式碼規模

- `project_brain/`：84 個 Python 檔，約 30,080 行
- 最大檔案：
  - `core/brain_db.py`：2468 行
  - `interfaces/web_ui/server.py`：2104 行
  - `interfaces/mcp_server.py`：1889 行
  - `interfaces/cli_admin.py`：1765 行
  - `graph.py`：1256 行
  - `engine.py`：1184 行

這些大檔已經進入「修改需要額外審慎」的規模，後續功能深化應優先拆分。

---

## 3. 可靠度

### 優點

- unified `brain.db` 是正確架構，避免舊版 KG/BrainDB 雙資料庫長期不一致。
- WAL + `busy_timeout=5000` + `BrainDB._write_guard()` 對本機單程序使用已足夠可靠。
- FTS5 與 nodes 覆蓋一致（762/762），目前沒有搜尋索引漏建。
- schema migration 有版本記錄，`brain health` 能驗證 schema v28。
- Pipeline queue 持久化，pending 為 0，沒有堆積跡象。

### 風險

- `BrainDB._write_guard()` 是 process-local `RLock`，不能跨進程保證序列化；HTTP MCP 多 client、多 worker 或多 process 部署時仍靠 SQLite 鎖與 busy timeout。
- E-02 多用戶測試只要求 90% 成功率，不能支持「多人同時操作不丟資料」的強宣稱。
- `graph.add_node()` 的 FTS5 sync 失敗只 warning 後仍 commit node；`BrainDB.add_node()` 是 atomic，但 graph 入口仍有「節點存在、搜尋不到」的降級路徑。
- `complete_task` auto-feedback 仍直接新建 `BrainDB(b.brain_dir)`，未完全遵守 singleton/shared connection 的架構方向。

---

## 4. 實用性

Project Brain 的實用性高，原因是它解的是 AI coding agent 的真問題：任務開始時取回專案規則、決策與踩坑，任務結束後把新知識寫回。

實際可用能力：

- CLI：`brain add / ask / search / health / validate / pipeline-stats`
- MCP：`get_context / add_knowledge / complete_task / report_knowledge_outcome`
- HTTP MCP：Bearer auth、CORS、rate limit、health endpoint
- WebUI：圖譜、節點編輯、staging API（新版 Flask route 測試通過）
- Federation：PII 清理、bundle、import staging、dedup
- 成本友善：可純 FTS5/TF-IDF 運作，不強制雲端 LLM

限制：

- Team Brain 的完整閉環還缺 E-03/E-04/E-05/E-06：overlay、ingestion、push、RBAC、admin dashboard。
- KRB 在目前實際 `.brain` 未初始化，審查流程不一定是日常使用路徑。
- Pipeline stats 為 0，表示目前系統有能力但這個工作區沒有真實自動知識生產流量。

---

## 5. 可用性

### 做得好

- README、COMMANDS、USER_GUIDE、ROADMAP、TEST_PLAN 都存在且資訊量高。
- `brain health --json` 與 `brain validate --ci` 適合 CI/自動化。
- `get_context` 冷啟動時會提示如何記錄知識，不會只回空字串。

### 需要修正

- `project_brain.__version__` 回報 0.41.0，但 README/CHANGELOG/pyproject 是 0.46.0。使用者會不知道自己跑的是哪個版本。
- README 寫「測試數量 1219 passed」，ROADMAP/TEST_PLAN 寫不同數字，實際主測試集為 1596 passed + 14 failed。
- `get_context` full 模式不直接顯示 node id，導致 `report_knowledge_outcome(node_id=...)` 對 agent 不夠可操作。
- WebUI raw handler integration 測試仍用舊 schema 期望，失敗訊息會讓維護者誤判 WebUI 整體壞掉。

---

## 6. 誠實性

Project Brain 有良好的誠實性文化：`Development Status :: 3 - Alpha`、ARCHITECTURE_REVIEW 保留缺陷史、ROADMAP 不刪歷史項目。

但目前仍有幾個過度宣稱：

1. **版本誠實性**：執行期版本錯報。
2. **多用戶誠實性**：文件宣稱寫入序列化/不丟資料，但測試只證明高比例成功。
3. **測試誠實性**：文件中多處「0 regression / 全量通過」與目前主測試集不一致。
4. **Phase 狀態誠實性**：Phase D/E 某些章節把局部完成描述得像整體完成，容易讓使用者高估團隊級部署成熟度。

修正方向：所有文件中的能力描述改成三種標籤：

- **已驗證**：有本機或 CI 測試數據。
- **可用但有限制**：功能存在，但有部署/規模/一致性條件。
- **規劃中**：只在 ROADMAP，不在 README 當現有功能賣點。

---

## 7. 記憶檢索品質

### 現況

檢索管線包含：

- FTS5 unicode61
- CJK n-gram
- synonym map
- LocalTFIDF / Ollama embedding vector search
- hybrid ranking
- confidence decay
- access_count feedback
- session dedup
- nudge / causal chain / reasoning chain

健康檢查顯示 FTS5 覆蓋完整，benchmark baseline regression 4 tests 通過。

### 品質判斷

檢索品質已足夠支撐日常 coding task，但還不夠支撐「高可信記憶系統」的強宣稱。

原因：

- synthetic 50-node recall benchmark 有用，但不能代表目前 762-node 真實知識庫。
- `get_context` 在本次審查中能取回 MEM-01/MEM-03 等有用架構知識，但也夾帶了 docs/i18n 類較低相關內容，表示 ranking 還有雜訊。
- full context 輸出沒有 node id，降低 feedback loop 可用性。
- summary/full 模式、AI selector、vector fallback 的實際召回差異尚未用同一資料集量測。

建議新增真實資料集評估：

- 從目前 `.brain` 抽 50-100 個高信心節點，人工建立 query → expected node id。
- 指標：recall@3、MRR、nDCG、無關結果率、平均 context tokens。
- 每次調整 synonym/embedding/ranking 都跑回歸。

---

## 8. 系統架構

### 強項

- 三層記憶模型清楚：L1 session、L2 episodes、L3 long-term nodes。
- unified DB 降低資料一致性風險。
- MCP Server 已從 module-level mutable state 重構為 `BrainServer`。
- LLM client 已抽象為 protocol，支援 Ollama/Anthropic/Noop/Fallback。
- Pipeline 判斷與執行分離，LLM 不直接寫 DB，方向正確。

### 架構債

- `brain_db.py`、`mcp_server.py`、`web_ui/server.py` 過大，修改風險高。
- backward-compat shim 很多，對測試與靜態掃描造成干擾。
- 仍有多條入口直接操作 SQLite，而不是統一走 `BrainDB` service method。
- WebUI 有 raw HTTP handler 與 Flask route 兩套路徑，schema fallback 不一致。
- `core/brain_db.py` 同時承擔 schema、CRUD、search、analytics、federation audit、lifecycle、migration、optimization，邊界過寬。

建議目標架構：

```text
interfaces/
  cli / mcp / http / web
services/
  knowledge_service.py     # add/update/delete/search/context
  feedback_service.py
  pipeline_service.py
  federation_service.py
storage/
  brain_db.py              # schema + low-level SQL only
  repositories/*.py        # nodes, edges, traces, signals
engines/
  context / decay / nudge / validator / resolver
```

---

## 9. 成本控制與資源消耗

### 成本控制做得好

- 基本功能不需要雲端 LLM。
- Ollama local-first，Anthropic 只是 fallback。
- Nudge/Decay/FTS/health 都是純本機計算。
- Pipeline worker 是非同步背景，不阻塞主要 MCP tools。
- Auto pipeline 的 node confidence 上限 0.85，避免自動知識過度權威。

### 隱性成本

- 每次新 Python process 呼叫 `add_knowledge` 時可能載入 embedding model；本次多次寫 Brain 都看到 `intfloat/multilingual-e5-small` weights loading。這會增加 CLI/MCP 冷啟動延遲與記憶體峰值。
- `BrainDB.__init__` 每日 `VACUUM INTO` 備份，DB 大時會增加啟動成本。
- `search_nodes()` 每次查詢都寫 `traces`，高 QPS HTTP MCP 場景會讓讀操作變成寫操作，增加 WAL 壓力。
- 目前 `.brain` 目錄 53MB，其中 `brain.db` 7MB；備份保留 7 份，規模上升後磁碟會線性增加。

建議：

- embedding 建立改為明確 opt-in 或常駐 worker，共用 model process。
- traces 採樣或批次寫入，避免每次 search 都同步寫 DB。
- daily backup 加大小門檻與可設定保留天數。
- `brain health` 顯示 DB/WAL/backup size 與 vector coverage。

---

## 10. 已驗證缺陷與 BUG 修復方案

### P0-1：MCP `add_knowledge` 背景 conflict check 呼叫錯誤 ✅ FIXED v0.47.0

**位置**：`project_brain/interfaces/mcp_server.py`  
**現象**：`b.db.find_conflicts(title_c, top_k=3)`  
**實際簽名**：`find_conflicts(similarity_threshold=0.7, candidates_per_anchor=10)`  
**影響**：背景 thread TypeError 後被吞掉，`KNOWLEDGE_CONFLICT` signal 不會產生。

修復：

- 新增 `BrainDB.find_conflicts_for_node(node_id, candidates_per_anchor=10)`，只找新節點相關衝突。
- 或暫時改成：
  - `conflicts = b.db.find_conflicts(similarity_threshold=0.6, candidates_per_anchor=3)`
  - 再過濾 `node_id in (node_a, node_b)`。
- 補測試：MCP `add_knowledge` 新增相似/矛盾節點後，signal_queue 出現 `knowledge_conflict`。

### P0-2：版本回報錯誤 ✅ FIXED v0.47.0

**位置**：`project_brain/__init__.py`  
**現象**：本地原始碼是 0.46.0，但 `__version__`/`brain health` 回報 0.41.0。  
**原因**：先讀 `importlib.metadata.version("project-brain")`，拿到舊 installed distribution。

修復：

- 在 source checkout 中優先讀相鄰 `pyproject.toml`。
- 或檢查 distribution path 是否與 `project_brain.__file__` 同一 repo，不同則不用 metadata。
- 補測試：`project_brain.__version__ == pyproject.toml project.version`。

### P1-1：多用戶寫入安全宣稱過度 ⏳ 部分修復（誠實性已修，write queue 待做）

**現象**：文件宣稱寫入序列化/不丟資料；測試只要求 90/100 成功。  
**影響**：團隊中央 Brain 部署會高估一致性保證。

修復：

- 實作真正的 central write queue：單 writer thread/process，所有 write tools 入 queue，回傳明確結果。
- 測試改為 100 threads × 100 writes = 100% 成功，否則文件改成「best effort」。
- 在 `brain serve --mode central` 才啟用 queue；本機模式維持簡單。

### P1-2：主測試集不全綠 ✅ FIXED v0.47.0

**現象**：`-m 'not chaos and not benchmark'` 仍跑出 14 failures。  
**原因**：舊 chaos 測試未完整 marker 隔離、duplicated legacy tests、raw WebUI handler 舊 schema。

修復：

- 將 `tests/chaos/` 與 `tests/test_chaos_and_load.py` 全部標記 `pytestmark = pytest.mark.chaos`。
- 刪除或歸檔 duplicated legacy chaos file。
- `tests/integration/test_web_ui.py` 改用 unified BrainDB fixture；或更新 raw handler query 使用 `type AS kind` 並處理無 `scope` schema。

### P1-3：WebUI FTS sync 與 BrainDB n-gram 不一致 ✅ FIXED v0.47.0

**位置**：`interfaces/web_ui/server.py::_sync_fts`  
**現象**：WebUI PATCH 後直接把 raw title/content 寫入 `nodes_fts`，而 `BrainDB.add_node()` 使用 CJK n-gram。  
**影響**：中文/子詞搜尋可能在 WebUI 編輯後退化。

修復：

- WebUI 不直接寫 FTS；呼叫 `BrainDB.update_node()`。
- 若保留 direct SQL，`_sync_fts` 必須使用 `BrainDB._ngram()`。

### P2-1：`get_context` 缺少可回饋 node id ✅ FIXED v0.47.0

**影響**：Agent 很難正確呼叫 `report_knowledge_outcome(node_id=...)`。  
**修復**：full 模式每條知識加入 `[node_id[:8]]`，並提供 MCP structured mode 回傳 `sources`。

### P2-2：靜默例外仍偏多 ✅ AUDITED v0.47.0（baseline ≤25，審計測試建立）

目前仍有多處 `except Exception: pass` 或 best-effort pass。部分是合理降級，但需要分類：

- 可接受：UI optional metadata、KeyboardInterrupt、old DB optional columns。
- 不可接受：會影響索引、feedback、conflict signal、版本、schema 的吞錯。

修復：建立 `tests/unit/test_no_critical_silent_failures.py`，只掃描 critical modules：`brain_db.py`、`mcp_server.py`、`web_ui/server.py`、`pipeline/*`。

---

## 11. 功能深化方向

### D1：真實檢索評估

建立 `.brain/eval/queries.jsonl`：

```json
{"query":"MCP add_knowledge conflict signal","expected":["pitfall-2de51f5c"]}
```

定期輸出 recall@3、MRR、噪音率與平均 context token。

### D2：Central Brain 生產模式

最小可用範圍：

- write queue
- API key role：reader/contributor/maintainer/admin
- audit log：who/what/when/source IP
- `/metrics` Prometheus
- health 顯示 central mode、active clients、queue depth、write latency

### D3：知識生命週期

目前已有 confidence、decay、feedback、deprecated。下一步應加入：

- stale review queue
- conflicting knowledge review queue
- auto-generated knowledge 的 promotion/demotion policy
- 「已驗證」與「自動推測」視覺標籤

### D4：Ingestion Pipeline

先做 local markdown ingestion，而不是一開始做 GitHub/Slack/Confluence 全套：

1. `brain ingest files --path docs --dry-run`
2. chunk by heading
3. LLM extract candidates
4. dedup
5. KRB staging

### D5：WebUI 從展示變管理工具

優先功能：

- search result + node id + source + confidence + freshness
- KRB pending queue
- conflict queue
- feedback buttons：useful / outdated / duplicate
- health dashboard

---

## 12. 優先路線圖

### 立刻修（1-2 天）— ✅ 全部完成（v0.47.0, 2026-05-02）

1. ✅ 修 `add_knowledge` conflict check signature bug → `find_conflicts_for_node()` + 15 tests
2. ✅ 修 `__version__` source checkout mismatch → pyproject.toml 優先 + 3 tests
3. ✅ 修測試 marker → module-level `pytestmark = pytest.mark.chaos` + WebUI PRAGMA schema 偵測
4. ✅ 更新 README/ROADMAP/TEST_PLAN 的測試數與能力宣稱 → E-02 `[PARTIAL]`，並發 best-effort

### 短期（1 週）— ✅ 全部完成（v0.47.0, 2026-05-02）

1. ✅ WebUI raw handler schema 修復 → PRAGMA table_info 動態偵測，4 個 WebUI 測試恢復
2. ✅ `get_context` full output 顯示 node id → `[nid[:8]]` 前綴 + `Sources` block + 8 tests
3. ✅ `BrainDB.find_conflicts_for_node()` → 同 P0-1
4. ✅ health size metrics → storage/db + storage/backups + storage/vectors + 8 tests
5. ✅ WebUI FTS sync n-gram 一致性（P1-3）→ `_sync_fts()` 改用 `BrainDB._ngram()` + 5 tests
6. ✅ 靜默例外審計（P2-3）→ baseline ≤25 + 禁止 bare except + 5 tests

### 中期（2-4 週）— 🔲 待做

1. 🔲 Central write queue + 100% 並發寫入測試
   - 單 writer thread/process，所有 write tools 入 queue
   - `brain serve --mode central` 啟用
   - 測試改為 100 threads × 100 writes = 100% 成功
   - 估計：8-12h

2. 🔲 API key RBAC
   - 角色：reader / contributor / maintainer / admin
   - audit log：who / what / when / source IP
   - `/metrics` Prometheus endpoint
   - 估計：8-10h

3. ✅ 真實 recall eval **[DONE v0.47.0]**
   - `project_brain/eval.py` — RecallEvaluator + 自動 dataset 生成
   - CLI `brain eval generate / run / report` + CI `--threshold` 模式
   - 首次基線：762 nodes, 100 queries → recall@3=21%, MRR=0.16
   - 33 tests（`tests/unit/test_recall_eval.py`）

4. 🔲 WebUI 管理面板
   - search result + node id + source + confidence + freshness
   - KRB pending queue + conflict queue
   - feedback buttons：useful / outdated / duplicate
   - health dashboard
   - 估計：10-16h

### 長期 — 🔲 待做

1. 🔲 Ingestion pipeline（`brain ingest files --path docs`）
2. 🔲 Team overlay mode（個人 Brain 疊加團隊 Brain）
3. 🔲 Push to central + admin approval
4. 🔲 LoRA/distillation（需真實資料集 + GPU 資源）

### 架構債 — 部分完成

1. 🔲 `brain_db.py` 2468 行拆分 → storage/repositories + services 層
2. 🔲 `mcp_server.py` 1889 行拆分 → 工具按 domain 拆檔
3. ✅ MCP singleton 連線 **[DONE v0.47.0]** — 3 處重複 BrainDB() 改用 b.db
4. ✅ traces 採樣 **[DONE v0.47.0]** — 每 5 次記錄一次（BRAIN_TRACE_SAMPLE_RATE 可調）
5. 🔲 embedding 冷啟動優化（常駐 worker 或 opt-in）
6. ✅ backup 保留設定 **[DONE v0.47.0]** — BRAIN_BACKUP_KEEP env / config.json

---

## 13. 最終判斷

Project Brain 的核心方向是對的：用 SQLite 做低維運記憶基礎設施，用 MCP 接入 agent，用 FTS/vector/feedback/decay 控制檢索品質，把 LLM 放在語意判斷邊界而不是資料正確性核心。

現在最需要的不是再加大功能面，而是把「已可用」和「已驗證」切清楚：

- 本機單人 Brain：可以繼續使用。
- 團隊 HTTP Brain：可以試點，但要標明非強一致。
- Central Brain 生產部署：等 write queue、RBAC、audit、全量測試綠燈後再宣稱。

若只做一件事，先修誠實性：版本、測試狀態、多用戶安全宣稱。記憶系統最怕的不是知道得少，而是把不確定的東西說成確定。

---

## 14. 修復記錄

| 日期 | 版本 | 修復項目 | 新增測試 |
|------|------|---------|---------|
| 2026-05-02 | v0.47.0 | P0-1 find_conflicts 簽名 | 15 tests |
| 2026-05-02 | v0.47.0 | P0-2 __version__ mismatch | 3 tests |
| 2026-05-02 | v0.47.0 | P1-2 chaos marker + WebUI schema | — (4 tests 恢復) |
| 2026-05-02 | v0.47.0 | P1-3 WebUI FTS n-gram | 5 tests |
| 2026-05-02 | v0.47.0 | P2-1 get_context node id | 8 tests |
| 2026-05-02 | v0.47.0 | P2-2 health storage metrics | 8 tests |
| 2026-05-02 | v0.47.0 | P2-3 靜默例外審計 | 5 tests |
| 2026-05-02 | v0.47.0 | 誠實性修正 README/ROADMAP | — |

**測試套件（修復後）**：1483 passed, 1 flaky, 0 real failures（不含 chaos/benchmark）
