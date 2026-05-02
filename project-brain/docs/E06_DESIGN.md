# E-06 運維 Agent 整合 — 具體方案分析 ✅ v0.53.0 DONE

## 核心約束

> 使用者是傳產工程人員，完全不懂技術。減少操作難度，提高使用體驗。

這意味著：**WebUI 必須成為主要介面，CLI 只是開發者/管理員的備用工具。**

---

## 現狀問題

| 問題 | 嚴重度 | 說明 |
|------|--------|------|
| **所有操作都需要 CLI** | P0 | 新增知識需要 `brain add`，查詢需要 `brain ask`，非技術人員完全無法使用 |
| **無總覽儀表板** | P0 | 管理者無法一眼看到系統狀態、團隊活動、知識分佈 |
| **無審計追蹤** | P1 | 誰加了什麼、何時改的、為什麼改，完全無紀錄可查 |
| **設定需要編輯 TOML** | P1 | 連線 Central Brain 需要手動編輯 brain.toml |
| **知識品質無警示** | P2 | 過時知識、衝突規則靜默累積 |

---

## 方案設計

### 方案架構

```
WebUI（瀏覽器）← 非技術人員的唯一介面
├── 📊 儀表板（Dashboard）     ← 系統總覽 + 健康狀態
├── 📋 知識管理（Table View）   ← 已有，搜尋/篩選/編輯
├── ➕ 新增知識（Add Form）     ← 新建，免 CLI
├── 📝 審計日誌（Audit Log）    ← 新建，who/what/when
├── ⚙️ 系統設定（Settings）     ← 新建，可視化設定 + 健康檢查
└── 📊 圖譜（Graph View）       ← 已有
```

### Step 1: WebUI 新增知識表單（免 CLI 的第一步）

**目標**：非技術人員可以在瀏覽器中直接新增知識，不需要打開終端。

**實作**：
- WebUI 新增 `➕ 新增` 按鈕（header 或 sidebar）
- 彈出表單：標題、內容、類型（下拉選單：規則/踩坑/決策/筆記）、信心度（滑桿）
- 提交 → POST `/api/node`（新增 endpoint）→ `brain.add_knowledge()`
- 成功後自動跳轉到新節點詳情

**UX 重點**：
- 類型用中文標籤（規則 / 踩坑 / 決策 / 筆記），不顯示英文 kind
- 信心度用滑桿（低/中/高），不顯示數字
- 必填欄位只有「標題」和「內容」，其他自動推斷

### Step 2: 儀表板（Dashboard）

**目標**：管理者一眼看到團隊知識庫狀態。

**API**：`GET /api/admin/dashboard` → JSON

**顯示內容**：
```
┌─────────────────────────────────────────────────┐
│ 📊 知識庫儀表板                    v0.53.0       │
├─────────────────────────────────────────────────┤
│ 知識總量    762 筆    ↑23 本週新增               │
│ 類型分佈    Pitfall 234 | Rule 198 | Decision 156│
│             Note 102 | ADR 72                    │
│                                                  │
│ 知識健康                                         │
│ ✅ 系統正常（0 error, 1 warning）                 │
│ ⚠️  12 筆知識信心度 < 0.3（建議複查）             │
│ ✅ 0 個知識衝突                                   │
│                                                  │
│ 近期活動                                         │
│ 今天   +5 筆    Alice(3) Bob(2)                  │
│ 本週   +23 筆   Alice(12) Bob(8) Charlie(3)      │
│ 本月   +67 筆                                    │
│                                                  │
│ KRB 待審    3 筆 pending                          │
│ Signal 佇列 12 筆待處理                           │
└─────────────────────────────────────────────────┘
```

**後端**：新增 `_route_admin_dashboard()` → 聚合 brain_db 的 SQL 統計

### Step 3: 審計日誌（Audit Log）

**目標**：誰加了什麼、何時改的。企業合規需求。

**API**：`GET /api/admin/audit-log?days=30&author=&kind=` → JSON

**資料來源**：
- `node_history` 表（已有 `changed_by`、`change_note`、`change_type`、`snapshot_at`）
- `staged_nodes` 表（KRB staging 的 `submitter`、`reviewer`、`created_at`、`reviewed_at`）
- `nodes` 表的 `created_at`、`source_url`、`author`

**WebUI**：
- 表格列：時間、操作者、動作（新增/修改/刪除/審核）、節點標題、詳情
- 篩選：日期範圍、操作者、動作類型
- CSV 匯出按鈕

### Step 4: 系統設定面板（Settings）

**目標**：可視化顯示系統設定 + 服務健康狀態，不需要編輯 TOML。

**API**：`GET /api/admin/settings` → JSON

**顯示**：
```
┌─────────────────────────────────────┐
│ ⚙️ 系統設定                         │
│                                     │
│ 運行模式     本地模式（standalone）   │
│ Embedding    LocalTFIDF（零依賴）    │
│ LLM          未設定                  │
│ Schema       v29                     │
│                                     │
│ 服務狀態                             │
│ ✅ brain.db   正常（762 nodes）      │
│ ⚠️  Ollama    未連線                 │
│ ✅ Central    未設定                  │
│                                     │
│ 儲存空間                             │
│ brain.db     12.3 MB                │
│ 備份         7 份 / 45.2 MB          │
└─────────────────────────────────────┘
```

### Step 5: Prometheus `/metrics` 端點

**目標**：讓 Grafana / 監控系統可以拉取指標。

**實作**：在 `http_transport.py` 的 `HealthEndpoint` 加上 `/metrics` 路徑。

```
# HELP brain_nodes_total Total knowledge nodes
# TYPE brain_nodes_total gauge
brain_nodes_total{kind="Pitfall"} 234
brain_nodes_total{kind="Rule"} 198
brain_nodes_total{kind="Decision"} 156
brain_nodes_total{kind="Note"} 102
# HELP brain_staging_pending Pending KRB staging nodes
# TYPE brain_staging_pending gauge
brain_staging_pending 3
# HELP brain_api_keys_active Active API keys
# TYPE brain_api_keys_active gauge
brain_api_keys_active 5
```

### Step 6: 引導式首次設定（WebUI Onboarding）

**目標**：第一次打開 WebUI 時，引導使用者完成基本設定。

**流程**：
1. 偵測 `.brain/` 不存在或 `nodes` 為空 → 顯示歡迎頁面
2. 引導步驟：「輸入第一筆知識」→「選擇你的角色」→「完成！」
3. 自動建立必要的 DB schema

**不做**：
- 不做 Ollama/LLM 設定（太技術）→ 預設用 LocalTFIDF
- 不做 Central Brain 連線設定 → 管理員用 CLI 設定

### Step 7: 測試 + 文件

**測試**：
- `test_webui_dashboard.py` — dashboard API 回傳正確統計
- `test_webui_audit_log.py` — audit log 篩選 + 分頁
- `test_prometheus_metrics.py` — /metrics 格式正確

**文件**：CHANGELOG v0.53.0 + ROADMAP E-06 DONE

---

## 實作優先順序

| 順序 | 功能 | 影響 | 工作量 |
|------|------|------|--------|
| 1 | WebUI Add Knowledge 表單 | **消除 CLI 依賴** | 4h |
| 2 | Dashboard（儀表板） | **管理者可視化** | 6h |
| 3 | Audit Log（審計日誌） | **合規 + 追蹤** | 5h |
| 4 | Settings 面板 | **系統透明度** | 3h |
| 5 | Prometheus /metrics | **監控整合** | 2h |
| 6 | Onboarding 引導 | **首次體驗** | 3h |
| 7 | Tests + Docs | **品質保證** | 3h |

---

## 關鍵設計原則

1. **零 CLI 原則**：非技術人員只用瀏覽器。所有 CRUD 操作都有 WebUI 入口。
2. **中文優先**：所有 UI 文字用中文，專業術語附括號解釋（例：「信心度（系統對這筆知識的確信程度）」）。
3. **預設安全**：不需要設定就能用。LocalTFIDF embedding（零依賴）、standalone 模式。
4. **漸進揭露**：新手只看到「新增/搜尋/瀏覽」，進階功能（衰減、Pipeline、Federation）藏在「進階設定」。
5. **錯誤用人話**：不顯示 traceback，顯示「系統暫時無法處理，請稍後再試」+ 建議操作。

---

## 修改的檔案

| 檔案 | 修改類型 |
|------|---------|
| `project_brain/interfaces/web_ui/server.py` | 新增 /api/node POST + /api/admin/* endpoints + dashboard/audit HTML |
| `project_brain/interfaces/http_transport.py` | /metrics Prometheus endpoint |
| `project_brain/core/brain_db.py` | audit log 查詢方法 |
| `project_brain/health.py` | 擴展統計（knowledge distribution, contributor activity） |
| `tests/unit/test_webui_admin.py` | **新建** |
| `tests/unit/test_prometheus.py` | **新建** |
