# Project Brain 深度系統審查

**日期**：2026-05-03  
**審查範圍**：可靠度、實用性、可用性、誠實性、記憶檢索品質、系統架構、成本控制與資源消耗、工程穩定性、缺陷、BUG 修復與功能深化。  
**基準版本**：v0.53.1（`pyproject.toml` 與 `__version__` 一致）  
**前次審查**：v0.47.0（2026-05-02）  
**方法**：閱讀核心程式碼與文件、查驗實際 `.brain/brain.db`、執行主測試集、比對前次審查發現。

---

## 1. 核心結論

自上次審查（v0.47.0）以來，Project Brain 完成了 Phase E 全部六個里程碑（E-01 ~ E-06），從單人本機工具進化為具備團隊共享能力的架構。新增了 write queue、RBAC、overlay query、ingestion pipeline、push to central、WebUI 管理面板與 Prometheus 監控。

**但新功能的品質收尾不足**。Prometheus 測試在全量 suite 中全數失敗（單獨跑通過，疑為 fixture 隔離問題），靜默例外從 25 暴增至 40（主要來自 WebUI 新增程式碼），README 版本未同步更新。這代表功能交付速度超過了品質基線的維護速度。

**總評**：

| 維度 | v0.47.0 | v0.53.1 | 判斷 |
|---|---:|---:|---|
| 本機單人可靠度 | 8/10 | 8/10 | 核心穩定，write queue 加分，但新模組靜默例外增加 |
| 團隊集中式可靠度 | 6/10 | 7/10 | write queue + RBAC + overlay 已實作，但尚未有真實多人使用驗證 |
| 實用性 | 8/10 | 9/10 | ingestion、push、connect 讓 Brain 從被動記錄變主動吸收 |
| 可用性 | 7/10 | 7/10 | WebUI 管理面板大幅提升，但 README 版本落後、test failures 會混淆 |
| 誠實性 | 6/10 | 7/10 | 版本回報已修，但 README 仍寫舊版本號 |
| 記憶檢索品質 | 7/10 | 7/10 | recall@3=29%（100 query benchmark），有改善空間但已有量化基線 |
| 架構 | 7/10 | 7/10 | 前端分離好，但大檔仍大（brain_db 2850 行），新模組增加了總複雜度 |
| 成本控制 | 8/10 | 8/10 | embedding lazy probe 改善冷啟動，Prometheus 零外部依賴 |
| 工程穩定性 | 7/10 | 6/10 | 總測試增至 1726，但 15 failures（含 12 個 Prometheus 隔離問題）|

---

## 2. 已驗證事實

### 2.1 執行狀態

**brain.db 統計**：

- nodes：829（前次 762，+67）
- FTS5 indexed：829（覆蓋率 100%）
- edges：176（前次 168，+8）
- vectors：1428（前次 688，+740 ⬆ 大幅增長）
- traces：14997（前次 928，+14069 ⬆ 大幅增長）
- signal queue pending：0
- schema_version：29（前次 v28，新增 `api_keys` 表）
- DB 大小：8.0 MB（前次 7 MB）
- `.brain/` 總大小：50 MB

**nodes 分佈**：

| type | 數量 | 佔比 |
|------|-----:|------|
| Decision | 394 | 47.5% |
| Rule | 299 | 36.1% |
| Pitfall | 134 | 16.2% |
| Note | 1 | 0.1% |
| Person | 1 | 0.1% |

**版本一致性**：`pyproject.toml` = `__version__` = `0.53.1` ✅

### 2.2 測試結果

主測試集（`-m 'not chaos and not benchmark'`）：

```text
1726 passed, 1 skipped, 15 failed, 197 deselected, 15 warnings in 673.31s
```

與前次比較：

| 指標 | v0.47.0 | v0.53.1 | 變化 |
|------|--------:|--------:|------|
| passed | 1483 | 1726 | +243 |
| failed | 0 | 15 | ⬆ 退步 |
| skipped | 1 | 1 | — |
| deselected | — | 197 | — |

**失敗分析**：

| 測試檔 | 失敗數 | 根因 |
|--------|-------:|------|
| `test_prometheus.py` | 12 | 單獨跑全通過，全量 suite 失敗 → fixture 隔離 / event loop 衝突 |
| `test_silent_exception_audit.py` | 1 | baseline ≤25，實際 40（WebUI 新增 21 個靜默例外） |
| `test_docs_accuracy.py` | 1 | README 未提及 v0.53 |
| `test_arch_decisions_v03.py` | 1 | multilingual embedder priority |

**關鍵觀察**：12 個 Prometheus 失敗是**環境隔離問題**而非功能缺陷。單獨執行 `test_prometheus.py` 時 12/12 通過。這需要修正 fixture 或 conftest，但不代表 Prometheus 功能本身有問題。

### 2.3 程式碼規模

- `project_brain/`：98 個 Python 檔（前次 84 個，+14）
- 總行數：約 33,320 行（前次 30,080 行，+3,240）

最大檔案：

| 檔案 | 行數 | 前次 | 變化 |
|------|-----:|-----:|------|
| `core/brain_db.py` | 2,850 | 2,468 | +382 |
| `interfaces/mcp_server.py` | 2,059 | 1,889 | +170 |
| `interfaces/web_ui/server.py` | 1,968 | 2,104 | **-136** ✅ 前端分離 |
| `interfaces/cli_admin.py` | 1,880 | 1,765 | +115 |
| `graph.py` | 1,256 | 1,256 | — |
| `engine.py` | 1,190 | 1,184 | +6 |

**正面變化**：WebUI server.py 通過前端分離（CSS/JS/HTML 拆為獨立檔案）成功減少 136 行。
**負面變化**：brain_db.py 繼續膨脹至 2,850 行，仍未拆分。

### 2.4 v0.47.0 → v0.53.1 重大變更

| 版本 | 功能 | 新增測試 |
|------|------|---------|
| v0.48.0 | Embedding 冷啟動優化（lazy probe + async embed） | ~10 |
| v0.49.0 | E-02 Write Queue + RBAC 基礎（schema v29） | ~33 |
| v0.50.0 | E-03 Central Brain Client（overlay/central/local 模式） | ~24 |
| v0.51.0 | E-04 Ingestion Pipeline（Markdown + GitHub） | ~42 |
| v0.52.0 | E-05 Push to Central + API Key 管理 | ~26 |
| v0.53.0 | E-06 WebUI 管理面板 + Prometheus + Dashboard + Audit | ~36 |
| v0.53.1 | WebUI 前端分離（f-string → static files） | ~9 |

---

## 3. 可靠度

### 進步（相對 v0.47.0）

- **Write Queue**：`BrainDB(serialized_writes=True)` 背景 writer thread，100 threads × 10 writes = 0 loss。這直接解決了前次審查的 P1-1。
- **RBAC 基礎**：`api_keys` table、`rbac.py` 角色層級（reader/contributor/maintainer/admin），為多用戶安全奠基。
- **FTS 覆蓋率持續 100%**：829/829 nodes 全部索引。
- **Schema 遷移穩定**：v28 → v29 無中斷。

### 仍存在的風險

- Write queue 只在 `serialized_writes=True` 啟用，預設模式仍使用 process-local `RLock`。文件需明確標示何時該啟用。
- RBAC 有框架但尚無真實部署驗證。`brain serve --mode central` 的 key validation 路徑需端對端測試。
- `complete_task` 是否已改用 shared connection？前次審查指出此問題，需確認。
- traces 大幅增長（928 → 14997）表示 trace sampling 可能未完全生效，或有其他寫入路徑繞過 sampling。

---

## 4. 實用性

### 顯著提升

v0.48–v0.53 讓 Project Brain 從「被動記錄工具」變成「主動知識管理平台」：

- **Ingestion Pipeline**（v0.51）：`brain ingest files --path docs` + `brain ingest github --repo org/repo`，自動從 Markdown 和 GitHub Issues 擷取知識候選。
- **Push to Central**（v0.52）：`brain push --to <url> --key <key> --kind Pitfall --min-confidence 0.8`，本機知識可推送至團隊 Brain。
- **Overlay Query**（v0.50）：`brain connect <url> --mode overlay`，本機 + 團隊 Brain 透明合併查詢。
- **WebUI 管理面板**（v0.53）：Dashboard、Audit Log、Settings、知識新增——不再只是圖譜展示。
- **API Key 管理**（v0.52）：`brain admin create-key / list-keys / revoke-key`。

### 限制

- Ingestion pipeline 的 LLM 判斷層依賴外部 LLM（Ollama/Anthropic），離線環境只能用 heuristic extraction。
- GitHub ingest 使用 stdlib `urllib`，無 pagination 與 rate limit 處理的文件說明。
- WebUI 管理面板目前無認證機制（本機模式可接受，remote 部署需加 auth）。

---

## 5. 可用性

### 做得好

- **前端分離完成**：WebUI 從 f-string 模板遷移到獨立 CSS（439 行）、JS（1,157 行）、HTML（311 行），大幅提升可維護性。
- **淺色模式**：WebUI 支援明暗主題切換。
- **管理面板五個分頁**：Graph、Admin、Dashboard、Audit、Settings，功能完整。
- **設定頁面可編輯**：中文介面，配置面板可直接修改系統設定。
- **版本回報一致**：`__version__` = `pyproject.toml` = 0.53.1。

### 需要修正

- **P-NEW-01：README 版本未同步**：README 未提及 v0.53，`test_docs_accuracy` 失敗。
- **P-NEW-02：設定頁儲存後內容消失**：最近兩個 commit 修復此 bug，但需驗證是否完全解決。
- **P-NEW-03：中文亂碼**：設定頁面曾出現中文亂碼（已修），需確認 UTF-8 encoding 在所有路徑一致。

---

## 6. 誠實性

### 改善

- **版本誠實性**：已修復。`__version__` 與 `pyproject.toml` 一致。
- **測試數更新**：README 寫 ~1483 passed，實際為 1726 passed——這是**保守**的，可接受。
- **Phase 狀態**：E-01 ~ E-06 全部標示完成，與程式碼實際狀態一致。

### 仍需修正

- **README 版本落後**：README 未提及 v0.53，需更新。
- **靜默例外宣稱**：v0.47.0 建立 baseline ≤25，目前實際 40。新增的 WebUI 管理面板程式碼引入了 21 個 `except: pass`，違反了自己設定的品質基線。
- **Prometheus 測試穩定性**：文件若宣稱 E-06 完成且測試通過，但全量 suite 中 Prometheus 測試全部失敗，這是誠實性缺口。

**建議**：
- 將靜默例外 baseline 分為兩層：核心模組 ≤15、WebUI 擴展 ≤25，總計 ≤40。或者修復 WebUI 中不必要的靜默例外。
- 修復 Prometheus 測試的 fixture 隔離，使全量 suite 通過。

---

## 7. 記憶檢索品質

### 量化基線（已建立）

```text
recall@1  = 25%
recall@3  = 29%    （前次首測 21%，改善 +8pp）
recall@5  = 30%
recall@10 = 30%
MRR       = 0.269
nDCG@3    = 0.273
noise@3   = 90.3%  ⚠ 仍然很高
avg tokens = 624
avg latency = 1.7ms
```

**分類召回率**：

| 節點類型 | 查詢數 | recall@3 |
|---------|-------:|---------|
| Pitfall | 31 | 45.2% |
| Decision | 34 | 23.5% |
| Rule | 35 | 20.0% |

### 分析

- **Pitfall 檢索最好**（45.2%），因為 Pitfall 內容通常包含具體錯誤訊息和技術關鍵詞，FTS5 容易匹配。
- **Rule 檢索最差**（20.0%），因為 Rule 內容多為抽象原則，措辭與查詢的語意距離較大。
- **noise@3 = 90.3%** 是核心問題——每 3 個結果中有 2.7 個無關。這意味著即使命中了正確結果，agent 仍需處理大量雜訊。
- **recall@5 = recall@10 = 30%** 表示超過 top-3 後幾乎沒有增量召回，說明 ranking 的長尾品質差。

### 改善方向

1. **降低 noise rate**：對低相關結果加入 minimum score threshold，寧可少回傳也不要回傳雜訊。
2. **Rule 類型增強**：為 Rule 節點加入 synonym expansion 或 example-based 索引，提升語意匹配。
3. **vector search 利用率**：vectors 已有 1428 個，但 eval report 顯示 `search_mode: fts5`。Hybrid ranking 是否真正啟用需確認。
4. **定期重跑 eval**：每次調整 ranking 後用同一 100-query dataset 回歸。

---

## 8. 系統架構

### 新增架構層

v0.48–v0.53 引入了清楚的整合層：

```text
project_brain/
├── integrations/
│   ├── central_brain_client.py    # E-03 overlay query
│   ├── push_central.py            # E-05 push to central
│   └── ingest/                    # E-04 ingestion pipeline
│       ├── base.py                # RawDocument, KnowledgeCandidate
│       ├── chunker.py             # Markdown heading split
│       ├── files.py               # Local files source
│       ├── github.py              # GitHub issues source
│       └── pipeline.py            # LLM + heuristic extraction
├── interfaces/
│   ├── cli_connect.py             # E-03
│   ├── cli_ingest.py              # E-04
│   ├── cli_push.py                # E-05
│   ├── cli_admin_keys.py          # E-05
│   └── web_ui/
│       ├── server.py              # 1968 lines (reduced)
│       ├── static/app.js          # 1157 lines
│       ├── static/style.css       # 439 lines
│       └── templates/index.html   # 311 lines
└── rbac.py                        # E-02 RBAC
```

### 架構強項

- **integrations/ 層結構清楚**：ingest、push、connect 各自獨立，職責分明。
- **前端分離完成**：WebUI 從 Python f-string 遷移到獨立 static files，大幅降低 server.py 複雜度。
- **RBAC 獨立模組**：`rbac.py` 不與 `brain_db.py` 耦合，符合 SRP。

### 架構債（持續）

- **`brain_db.py` 2,850 行**：繼續增長，仍同時承擔 schema、CRUD、search、analytics、federation、lifecycle、migration、optimization。前次審查建議拆分為 storage/repositories + services，尚未執行。
- **`mcp_server.py` 2,059 行**：工具函式數持續增加，未按 domain 拆檔。
- **WebUI 靜默例外 21 處**：新增程式碼的錯誤處理品質低於核心模組。
- **測試 fixture 隔離不足**：Prometheus 測試 event loop 衝突表示 conftest 設計有缺陷。

### 建議目標架構（更新）

```text
interfaces/
  cli / mcp / http / web
services/
  knowledge_service.py     # add/update/delete/search/context
  feedback_service.py
  pipeline_service.py
  federation_service.py
  ingestion_service.py     # ← NEW: wrap integrations/ingest
storage/
  brain_db.py              # schema + low-level SQL only
  repositories/*.py        # nodes, edges, traces, signals, api_keys
engines/
  context / decay / nudge / validator / resolver
integrations/
  central_brain_client.py
  push_central.py
  ingest/
```

---

## 9. 成本控制與資源消耗

### 改善

- **Embedding 冷啟動優化**（v0.48）：`get_embedder()` lazy probe + `BRAIN_EMBED_LAZY=1` 環境變數，測試環境不再載入 model weights。
- **Async embed**：`add_knowledge` 立即回傳 `node_id`，embedding 在 daemon thread 完成，不阻塞使用者。
- **Prometheus 零外部依賴**：metrics endpoint 直接輸出 text format，不需要 `prometheus_client` library。

### 隱性成本（更新）

- **traces 爆量**：14,997 條（前次 928）。即使有 sampling，traces 仍以 ~16x 速度增長。需確認 sampling rate 是否正確生效，或是否有未走 sampling 的寫入路徑。
- **vectors 翻倍**：1,428 條（前次 688）。這可能是 async embed 補齊了之前缺失的 vectors，是正面變化，但也增加了 DB 大小。
- **新模組增加記憶體佔用**：ingestion pipeline + LLM client + RBAC 各自有 import 成本，CLI 冷啟動可能變慢。
- **`.brain/` 50MB 穩定**：DB 從 7MB 增至 8MB，總目錄大小不變，備份管理正常。

---

## 10. 已驗證缺陷

### 新發現缺陷

#### P-NEW-01：README 版本未同步 ⚠ OPEN

**位置**：`README.md`  
**現象**：`test_readme_has_version_reference` 失敗，README 未提及 v0.53。  
**影響**：使用者無法從 README 確認目前版本。  
**修復**：更新 README 中的版本參考。

#### P-NEW-02：靜默例外超出 baseline ⚠ OPEN

**位置**：主要是 `web_ui/server.py`（21 處）  
**現象**：`test_count_silent_exceptions_in_critical_modules` 失敗，實際 40 > baseline 25。  
**分佈**：
- `web_ui/server.py`：21
- `brain_db.py`：7
- `mcp_server.py`：5
- `context.py`：4
- `health.py`：3

**影響**：WebUI 管理面板中的錯誤會被靜默吞掉，增加除錯難度。  
**修復**：逐一審查 WebUI 的 21 處靜默例外，合理降級的保留並 log warning，不合理的改為 raise 或 log error。調整 baseline 至合理數值。

#### P-NEW-03：Prometheus 測試 fixture 隔離 ⚠ OPEN

**位置**：`tests/unit/test_prometheus.py`  
**現象**：單獨跑 12/12 通過，全量 suite 中 12/12 失敗。  
**原因推測**：asyncio event loop 被其他測試污染，或 ASGI app scope 未正確隔離。  
**影響**：CI 中 Prometheus 功能顯示為失敗，降低測試可信度。  
**修復**：在 conftest 中確保 event loop fixture 獨立，或使用 `pytest-asyncio` 的 `auto` mode。

#### P-NEW-04：Multilingual embedder priority 測試失敗 ⚠ OPEN

**位置**：`tests/unit/test_arch_decisions_v03.py`  
**現象**：`test_multilingual_selected_over_ollama_when_both_available` 失敗。  
**影響**：可能代表 embedding 選擇邏輯有回歸，或測試假設不正確。

### 前次缺陷狀態追蹤

| 缺陷 | v0.47.0 狀態 | v0.53.1 狀態 |
|------|-------------|-------------|
| P0-1 find_conflicts 簽名 | ✅ FIXED | ✅ 維持 |
| P0-2 __version__ mismatch | ✅ FIXED | ✅ 維持 |
| P1-1 write queue / 多用戶安全 | ⏳ 待做 | ✅ FIXED（v0.49.0 write queue） |
| P1-2 主測試集不全綠 | ✅ FIXED | ⚠ 回歸（15 failures） |
| P1-3 WebUI FTS n-gram | ✅ FIXED | ✅ 維持 |
| P2-1 get_context 缺 node id | ✅ FIXED | ✅ 維持 |
| P2-2 靜默例外 baseline | ✅ AUDITED (≤25) | ⚠ 超標（40） |

---

## 11. 功能深化方向（更新）

### 已完成（v0.47.0 路線圖對照）

| 項目 | 原估計 | 完成版本 |
|------|--------|---------|
| Central write queue + 100% 並發寫入 | 8-12h | v0.49.0 ✅ |
| API key RBAC | 8-10h | v0.49.0 + v0.52.0 ✅ |
| 真實 recall eval | — | v0.47.0 ✅ |
| WebUI 管理面板 | 10-16h | v0.53.0 ✅ |
| Ingestion pipeline | 長期 | v0.51.0 ✅ |
| Team overlay mode | 長期 | v0.50.0 ✅ |
| Push to central + admin approval | 長期 | v0.52.0 ✅ |
| MCP singleton 連線 | — | v0.47.0 ✅ |
| traces 採樣 | — | v0.47.0 ✅ |
| backup 保留設定 | — | v0.47.0 ✅ |

### D1：檢索品質深化（優先）

- recall@3=29%、noise@3=90.3% 是最大實用性瓶頸。
- 嘗試啟用 hybrid ranking（FTS5 + vector），目前 eval 只測了 FTS5 模式。
- Rule 類型加入 synonym / example indexing。
- 加入 minimum relevance threshold，降低雜訊回傳。

### D2：Central Brain 生產部署準備

- Prometheus metrics ✅（已實作），但需修 fixture 隔離讓 CI 通過。
- Audit log ✅（已實作）。
- 缺少：rate limiting 文件、multi-worker 部署指南、central mode 健康檢查 dashboard。

### D3：工程品質收尾

- 修復全部 15 個 test failures，恢復全綠。
- WebUI 靜默例外清理。
- README 版本同步。
- `brain_db.py` 拆分（2,850 行，早該做）。

### D4：使用者指南

- 用戶已明確要求詳細用戶指南文件。
- 建議按使用場景分章：本機快速入門、CLI 日常使用、MCP 配置、WebUI 管理、團隊部署。

---

## 12. 優先路線圖

### 立刻修（1-2 天）

1. 🔲 更新 README 版本參考至 v0.53
2. 🔲 修復 `test_prometheus.py` fixture 隔離（event loop 衝突）
3. 🔲 審查 WebUI 21 處靜默例外，降至合理數值
4. 🔲 確認 `test_arch_decisions_v03` multilingual embedder 測試邏輯

### 短期（1 週）

1. 🔲 恢復主測試集全綠（0 real failures）
2. 🔲 recall 改善實驗：啟用 hybrid ranking + minimum threshold
3. 🔲 traces 增長調查：確認 sampling 是否正確生效
4. 🔲 Central mode 部署文件

### 中期（2-4 週）

1. 🔲 `brain_db.py` 拆分為 storage/repositories + services
2. 🔲 `mcp_server.py` 按 domain 拆檔
3. 🔲 使用者指南文件（按使用場景分章）
4. 🔲 recall@3 目標提升至 40%+

### 長期

1. 🔲 LoRA/distillation（需真實資料集 + GPU 資源）
2. 🔲 Multi-worker central 部署 + load testing
3. 🔲 KRB 審查流程整合 WebUI

### 架構債

| 項目 | 狀態 | 備註 |
|------|------|------|
| `brain_db.py` 拆分 | 🔲 待做 | 2,850 行，最優先 |
| `mcp_server.py` 拆分 | 🔲 待做 | 2,059 行 |
| MCP singleton 連線 | ✅ 完成 | v0.47.0 |
| traces 採樣 | ✅ 完成 | v0.47.0（但效果需驗證） |
| backup 保留設定 | ✅ 完成 | v0.47.0 |
| embedding 冷啟動優化 | ✅ 完成 | v0.48.0 |
| WebUI 前端分離 | ✅ 完成 | v0.53.1 |
| 靜默例外清理 | ⚠ 回歸 | v0.47.0 建立 baseline，v0.53 超標 |

---

## 13. 最終判斷

Project Brain 在功能面完成了顯著跨越：Phase E 全部六個里程碑交付，從單人工具進化為具備團隊共享、知識吸收、運維監控能力的平台。

但**品質基線沒有跟上功能交付速度**。這是目前最需要修正的問題：

1. **15 個測試失敗**比 v0.47.0 的 0 failures 退步。
2. **靜默例外從 25 增至 40**，新程式碼的錯誤處理品質低於核心模組。
3. **README 版本落後**是一個簡單但反覆出現的問題。

**建議優先順序**：
1. **恢復測試全綠**——這是所有其他工作的基礎。
2. **檢索品質提升**——recall@3=29% 是 Brain 作為記憶系統的核心指標，需要優先改善。
3. **架構債清理**——`brain_db.py` 2,850 行拆分不能再拖。

若只做一件事：**先修測試，再修 recall，最後修架構**。功能已經夠多了，現在需要的是品質收斂。

---

## 14. 修復記錄

| 日期 | 版本 | 修復項目 | 新增測試 |
|------|------|---------|---------|
| 2026-05-02 | v0.47.0 | P0-1 find_conflicts 簽名 | 15 |
| 2026-05-02 | v0.47.0 | P0-2 __version__ mismatch | 3 |
| 2026-05-02 | v0.47.0 | P1-2 chaos marker + WebUI schema | 4 恢復 |
| 2026-05-02 | v0.47.0 | P1-3 WebUI FTS n-gram | 5 |
| 2026-05-02 | v0.47.0 | P2-1 get_context node id | 8 |
| 2026-05-02 | v0.47.0 | P2-2 health storage metrics | 8 |
| 2026-05-02 | v0.47.0 | P2-3 靜默例外審計 | 5 |
| 2026-05-02 | v0.47.0 | 誠實性修正 README/ROADMAP | — |
| 2026-05-02 | v0.48.0 | Embedding 冷啟動優化 | ~10 |
| 2026-05-02 | v0.49.0 | Write Queue + RBAC | ~33 |
| 2026-05-02 | v0.50.0 | Central Brain Client | ~24 |
| 2026-05-02 | v0.51.0 | Ingestion Pipeline | ~42 |
| 2026-05-02 | v0.52.0 | Push to Central + API Keys | ~26 |
| 2026-05-02 | v0.53.0 | WebUI 管理面板 + Prometheus | ~36 |
| 2026-05-02 | v0.53.1 | WebUI 前端分離 | ~9 |
| 2026-05-03 | — | 設定頁儲存後內容消失修復 | — |
| 2026-05-03 | — | 設定頁面中文亂碼修復 | — |

**測試套件（v0.53.1）**：1726 passed, 15 failed, 1 skipped（不含 chaos/benchmark）  
**目標**：0 real failures
