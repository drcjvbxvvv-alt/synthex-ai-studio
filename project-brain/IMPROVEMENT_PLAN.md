# Project Brain — 改善規劃書

> **當前版本**：v0.9.0（2026-04-04）
> **文件用途**：待辦改善項目。已完成項目見 `CHANGELOG.md`。

---

## 優先等級

| 等級 | 說明 | 目標版本 |
|------|------|---------|
| **P1** | 明確影響正確性，應優先處理 | 下一個 minor |
| **P2** | 影響核心功能價值，計劃排入 | 計劃中 |
| **P3** | 長期願景、低頻路徑、實驗性 | 評估中 |

---

## 矩陣優先總覽

> 評分依據：**影響 × (1 / 工時) × 無阻塞係數**。影響評估以「對 Agent 使用知識庫的核心價值改善程度」為基準。

### 四象限分佈

```
高影響
  │  FEAT-01 ──── DEEP-05        ARCH-06
  │  ARCH-05                     DEEP-04
  │─────────────────────────────────────  ← 建議執行線
  │  PERF-03  REF-04             OBS-01
  │  BUG-A03  PERF-04  FEAT-04  REF-01
低影響
     低工時 ────────────────── 高工時
     (半天–1天)              (1週以上)
```

### 建議開發順序

| 優先 | ID | 影響 | 解決方案 | 阻塞依賴 | 象限 | 建議理由 |
|------|----|------|---------|---------|------|---------|
| ~~**P0**~~ ✅ | ~~PERF-03~~ | `_count_tokens()` 高頻呼叫（800+次/req）浪費 CPU | `@lru_cache(maxsize=1024)` 加到 `_count_tokens()` | 無 | ⚡ 快速獲益 | 一行改動，零風險，立即生效 |
| ~~**P0**~~ ✅ | ~~BUG-A03~~ | 6 個懶加載屬性共用鎖，極低概率競態死鎖 | `engine.py` 每個屬性獨立 `threading.Lock()` | 無 | ⚡ 快速獲益 | 防禦性修復，消除死鎖隱患 |
| ~~**P0**~~ ✅ | ~~REF-04~~ | 魔法數字散落 4 處，修改需多點同步 | 新增 `constants.py`，集中定義 4 個常數 | 無 | ⚡ 快速獲益 | 為後續重構與 DEEP-05 調參鋪路 |
| ~~**P0**~~ ✅ | ~~PERF-04~~ | EXPAND_LIMIT=15 固定，短查詢噪音 / 長查詢遺漏 | `_expand_query()` 依詞數動態調整上限（短查詢上限 10，其餘 15）| 無 | ⚡ 快速獲益 | 單函數改動，搜尋精度立即提升 |
| ~~**P1**~~ ✅ | ~~DEEP-05~~ | 知識庫無自學習：有用知識不獎勵，無效不懲罰 | `record_outcome()` + `_factor_adoption()` F6 因子；`adoption_count` 欄位 (v17)；mcp_server 同步 graph.increment_adoption() | 無 | 🎯 高價值 | F6 = min(1.2, 1+adoption×0.02)；越用越聰明 |
| ~~**P1**~~ ✅ | ~~FEAT-01~~ | `update_node()` 直接覆寫，知識演變不可追溯 | `nodes.version` 欄位 (v14) + `change_type` (v15) + `brain history / restore` CLI | 無 | 🎯 高價值 | `node_history` 表已存在；新增 version 欄位與 CLI 別名 |
| ~~**P1**~~ ✅ | ~~ARCH-05~~ | deprecated 節點仍被正常推薦，殭屍知識持續擴散 | `deprecated_at` 欄位 (v16)；`brain deprecated list/purge`；context 加 `[已棄用]` 標記；`GET /v1/knowledge/deprecated` | 無 | 🎯 高價值 | 完整 deprecated 流程：標記→顯示→清理 |
| ~~**P1**~~ ✅ | ~~ARCH-06~~ | `BRAIN_CONFLICT_RESOLVE=1` 設置後直接 ImportError | `conflict_resolver.py` 已存在（完整 LLM 仲裁）；`decay_engine._detect_contradictions()` 寫入 `CONFLICTS_WITH` edges | FEAT-01 | 🎯 高價值 | conflict_resolver 模組已完整，補上 edges 寫入即完成 |
| ~~**P2**~~ ✅ | ~~OBS-01~~ | 問題難重現，Decay 為何降低信心無從追查 | structlog 結構化日誌（`event/node_id/reason`）；`GET /v1/metrics` Prometheus 端點 | 無 | ✅ 完成 | 先做 structlog（1天），再做 Prometheus（2天） |
| ~~**P2**~~ ✅ | ~~DEEP-04~~ | 信心 < 0.5 的節點缺乏確認機制，知識庫品質停滯 | AI 自動裁決（rule-based + LLM-assisted）取代人工確認 | DEEP-05 | ✅ 完成 | 設計調整：AI 自主運作，大幅減少人工介入 |
| ~~**P1**~~ ✅ | ~~KRB-01~~ | KRB 人工審核是系統最後一個人力瓶頸，違背 AI 全自主目標 | 方案 B+C 混合：AI 全自動裁決（閾值驅動）+ 知識來源初始信心差異化；人退出關鍵路徑，只留 audit log | DEEP-04 ✅ | ✅ 完成 | AI 推理能力已超越人工審查速度與一致性；git commit 本身即高可信來源 |
| ~~**P2**~~ ✅ | ~~FED-01~~ | 跨庫導入無溯源，無法查「誰何時導入了什麼」 | `federation_imports` 表；`brain fed imports list/approve/reject` | 無 | ✅ 完成 | FED-02 和 CLI-02 的前置條件 |
| ~~**P2**~~ ✅ | ~~FED-02~~ | Jaccard 去重無法偵測語義近似知識，知識庫膨脹 | `_is_duplicate()` 組合 Jaccard OR 向量相似度（threshold=0.9） | FED-01 | ✅ 完成 | 需向量化依賴可用；搭配 FED-01 同步發布 |
| ~~**P2**~~ ✅ | ~~CLI-02~~ | `sync_all()` 完成但無 CLI 入口，VISION-03 無法使用 | `brain fed sync/export/import/subscribe/unsubscribe` | FED-01 | ✅ 完成 | 補全 Federation 最後一哩路 |
| ~~**P2**~~ ✅ | ~~FEAT-04~~ | L1a session 結束清空，長工作階段洞察遺失 | `SessionStore.archive()`；導出 `.brain/sessions/<id>.md`；90 天自動清理 | 無 | ✅ 完成 | 低頻場景，有餘力時處理 |
| ~~**P2**~~ ✅ | ~~FEAT-03~~ | `temporal_query` 只有骨架，無時間過濾邏輯 | `valid_from`/`valid_until` 欄位；從 git log 推斷有效期；`brain history --at <date>` | 無 | ✅ 完成 | `nodes_at_time()`；SCHEMA_VERSION=19；`brain history --at` CLI |
| ~~**P3**~~ ✅ | ~~REF-01~~ | BrainDB ~1800 行承擔 10+ 職責（God Object） | 逐步抽離 `VectorStore`、`FeedbackTracker` | 覆蓋率≥70% | ✅ 完成 | `vector_store.py` + `feedback_tracker.py`；BrainDB 以 delegation 模式保持 backward compat |
| ~~**P3**~~ ✅ | ~~CLI-01~~ | `cli.py` 2864 行，31 個函數無法維護 | 按功能拆分子模組；抽取 `@require_brain_dir` 裝飾器 | 整合測試 | ✅ 完成 | `cli_utils.py`、`cli_knowledge.py`、`cli_admin.py`、`cli_serve.py`、`cli_fed.py`；`cli.py` 精簡至 ≤500 行 |
| ~~**P3**~~ ✅ | ~~ARCH-04~~ | scope 三路控制流讓使用者困惑 | 合併 `--global`/`--scope` 為單一 `--scope global` | v0.10.0 | ✅ 完成 | `--global` 保留但印棄用警告，導引使用 `--scope global` |
| **⏳** | REV-02 | 衰減效用幫助還是傷害召回率，目前未知 | 對比有/無衰減召回率；統計過時節點前 3 比例 | 90天真實數據 | ⏳ 等待 | 無法提前執行 |

### 依賴鏈

```
PERF-03 ──┐
BUG-A03 ──┤ 無依賴，v0.7.0 可立即執行
REF-04  ──┤
PERF-04 ──┘

DEEP-05 ──→ DEEP-04（主動學習需反饋閉環先就位）
FEAT-01 ──→ ARCH-06（版本歷史提供比對基礎）
FED-01  ──→ FED-02
        └─→ CLI-02

覆蓋率≥70% ──→ REF-01 ──→ CLI-01  ✅ 全部完成
v0.10.0     ──→ ARCH-04  ✅ 完成
```

### 象限說明

| 符號 | 象限 | 策略 |
|------|------|------|
| ⚡ | 快速獲益（高ROI × 低工時） | 立即納入下一個 sprint |
| 🎯 | 高價值（高影響，工時可接受） | 按順位排入版本計劃 |
| 📋 | 計劃執行（中影響，中工時） | 排入 v0.9.0 |
| 🔵 | 填空（低影響，低工時） | 有餘力時處理 |
| 🏗 | 長期重構（中影響，高工時） | 達到前置條件後才動 |
| ⏳ | 等待數據（需真實使用） | 不可提前執行 |

---

## P1 — 正確性缺陷

~~BUG-B02~~ ✅ **已修復（2026-04-04）**：`_effective_confidence()`（`brain_db.py`）和 `decay_engine._factor_time()`（`decay_engine.py`）改用 `MAX(created_at, updated_at)` 作為衰減時間基準。820 天前建立但 3 天前更新的節點，effective_confidence 從 0.077 恢復至 0.892。

> P1 項目全數完成，本節保留供 CHANGELOG 同步後移除。

---

## P2 — 核心功能缺口

~~BUG-B01~~ ✅ **已修復（2026-04-04）**：移除 `BrainDB.session_set/get/list/clear` 四個方法及 `ReadBrainDB` 中的 2 個 override；`import_json` 改用直接 SQL INSERT 替代 `session_set()`；移除 `MAX_SESSION_ENTRIES` 常數及 `TestDef06SessionLRU` 測試。`SessionStore`（`session_store.py`）是 L1a 的唯一入口，brain.db 的 `sessions` 表格仍保留供舊資料統計用（`stats()` / `health_report()`）。

---

### ~~KRB-01~~ ✅ — 自主審核（Autonomous KRB）**（已完成 2026-04-04）**

**設計背景**：KRB（Knowledge Review Board）的人工 approve/reject 流程是系統中最後一個人力瓶頸。AI Agent（Claude Code、Cursor、CodeX）產生的 git commit 本身即高度結構化的可信來源，不需要人工背書。

**核心設計：方案 B + C 混合**

#### 裁決閾值（方案 B）— 環境變數可覆蓋

| 來源信心值 | 自動動作 | 說明 |
|-----------|---------|------|
| ≥ 0.75（`BRAIN_KRB_AUTO_APPROVE`） | **auto-approve** → 直接進入 active graph，保留原始信心值 | git_sync / mcp / manual 全部命中 |
| 0.50–0.74 | **auto-approve（降信心）** → confidence = 0.55 | 讓採用率閉環（DEEP-05 F6）自然篩選 |
| < 0.50（`BRAIN_KRB_AUTO_REJECT`） | **auto-reject** → 記錄至 audit log，不入庫 | 成本低於誤導 Agent |

#### 知識來源初始信心差異化（方案 C）— `INITIAL_CONF_BY_SOURCE`

| 來源 (`source` 欄位) | `initial_confidence` | 理由 |
|---------------------|---------------------|------|
| `git-<hash>`（`brain sync`） | **0.85**（最高） | AI 生成、結構化、CI 驗證，品質最一致 |
| `mcp`（AI Agent `add_knowledge`） | **0.80** | AI 主動判斷，明確意圖 |
| `manual` / `brain add` | **0.75** | 人類明確意圖，直接命中 auto-approve 門檻 |
| `brain-scan` / `auto-scan` / `scan` | **0.60** | 大批量歷史掃描，降信心後 auto-approve |

> git_sync 為最高初始信心，因 AI 提交的 commit 格式標準化程度高於人工輸入。

#### 人類角色轉移

```
舊流程：知識 → staging → 人工佇列 → approve/reject → active
新流程：知識 → staging → auto_approve_by_confidence()（< 1ms）→ active / rejected
                                  ↓
                             audit log（永久保留，隨時可查）
```

- `brain review list` → 預設顯示 **audit log**（裁決紀錄）
- `brain review list --pending` → 顯示待人工審查（KRB-01 模式下永遠為空）
- 人類可隨時 override：`brain review approve <id>` / `brain review reject <id>` 仍有效

**已實作檔案**：
- `review_board.py`：`RB_SCHEMA_VERSION=3`；`INITIAL_CONF_BY_SOURCE`；`confidence` 欄位遷移；`submit()` 存入 source 信心；`approve()` 傳遞 confidence 至 L3；`auto_approve_by_confidence()`；`list_audit_log()`
- `engine.py`：`StagingGraph` 收集 `_staged_ids`；scan 後自動呼叫 `auto_approve_by_confidence()` for each
- `cli_knowledge.py`：`brain review list` 預設 audit log；`--pending` flag
- `cli_utils.py`：新增 `--pending` argparse flag

**安全網**：若誤批一條壞知識 → adoption_count 永遠 = 0 → F6 無加成 → Decay 降低 confidence → deprecated → auto-purge（90 天）

**依賴**：DEEP-04 ✅、DEEP-05 ✅

---

### ~~FEAT-03~~ ✅ — 時間感知查詢（Temporal Query）**（已完成 2026-04-04）**

**問題**：`temporal_query` MCP 工具只查詢 `temporal_edges` 表，無法回答「某個時間點有哪些節點有效」。`nodes` 表只有 `valid_until`，沒有 `valid_from`，也沒有 git 日期推斷邏輯。

**實作**：

- `brain_db.py` SCHEMA_VERSION=19：`ALTER TABLE nodes ADD COLUMN valid_from TEXT DEFAULT NULL`
- `add_node()` 新增 `valid_from` kwarg；INSERT OR REPLACE 前先讀取現有值，確保 OR REPLACE 後 `valid_from` 不遺失
- `nodes_at_time(at_time, limit, node_type)` 方法：查詢 `valid_from <= at_time AND (valid_until IS NULL OR valid_until > at_time)`
- `engine.py` `learn_from_commit()`：使用 `git log -1 --pretty=%aI` 取得實際 commit 日期（非 `datetime.now()`）；`_store_chunk()` 同步寫入 `brain.db` 並帶 `valid_from`
- `mcp_server.py` `temporal_query` 工具：回傳 `edges` + `nodes`（節點時間快照）
- `cli_knowledge.py` `cmd_history` + `_at_snapshot()`：`brain history --at <date|ref>` 顯示時間點知識快照；支援 git branch/tag 名稱解析
- `cli_utils.py` `history` parser：`node_id` 改為 `nargs='?'`；新增 `--at` 參數

### REV-02 — Decay 實際效用未量測

無法驗證衰減是幫助還是傷害召回率。對比有/無衰減知識庫；統計過時節點排前 3 的比例。△ 需 90 天以上數據。

詳見 `tests/TEST_PLAN.md` § 7 — REV-02 衰減效用量測

---

### ~~DEEP-05~~ ✅ — Decay F6 採用率反饋（知識自學習閉環）**（已完成）**

**問題**：`decay_engine.py` F6（採用率反饋）未實裝；有用知識無法被獎勵，知識庫是「靜態評分」。

**實裝內容**：
1. `brain_db.py` v17 migration：`adoption_count INTEGER NOT NULL DEFAULT 0`；`feedback_tracker.py` `record_outcome()` 實作採用率累計與信心調整
2. `decay_engine.py` `_factor_adoption(adoption_count)` → `F6 = min(1.2, 1 + adoption_count × 0.02)`（最多 +20%）
3. `mcp_server.py` `report_knowledge_outcome` 工具：呼叫 `record_feedback()` + `graph.increment_adoption()`
4. `graph.py` `increment_adoption(node_id)` — knowledge_graph.db 同步 adoption_count
5. `api_server.py` **`POST /v1/knowledge/<id>/outcome`**：REST 入口，接收 `{"was_useful": bool, "notes": "..."}`，回傳 `{"confidence": 0.85, "delta": 0.03}`

---

### ~~ARCH-05~~ ✅ — 弃用流程（deprecated 節點通知 / 清理路徑）**（已完成 2026-04-04）**

**已實作**：
1. **`context.py`** 推薦 deprecated 節點時加 `[已棄用]` 標記（不過濾，但明示）
2. **`brain_db.py`** SCHEMA_VERSION=16：`deprecated_at` 欄位；`_apply_decay()` 同步設置；`list_deprecated()` / `purge_deprecated(older_than_days)` 方法
3. **`cli_knowledge.py`** `brain deprecated list` / `brain deprecated purge --older-than <days>`
4. **`api_server.py`** `GET /v1/knowledge/deprecated` 端點

---

### ~~ARCH-06~~ ✅ — ConflictResolver 實裝（VISION-02 矛盾仲裁）**（已完成 2026-04-04）**

**已實作**：
1. **`conflict_resolver.py`** 建立：`ConflictResolver(db, graph, llm_client=None)`；`resolve(node_a, node_b) → ArbitrationResult`；無 LLM 時數值保守仲裁；有 LLM（`BRAIN_LLM_KEY`）時語義仲裁
2. **`decay_engine.py`** F4 升級：`_detect_contradictions()` 偵測矛盾後寫入 `CONFLICTS_WITH` edges；仲裁後非對稱調整 confidence（winner 不懲罰，loser × 0.5）
3. `BRAIN_CONFLICT_RESOLVE=1` 不再導致 ImportError

---

### ~~FEAT-01~~ ✅ — 知識版本控制（節點歷史追蹤）**（已完成 2026-04-04）**

**已實作**：
1. **`brain_db.py`** SCHEMA_VERSION=14：`nodes.version INTEGER DEFAULT 1`；SCHEMA_VERSION=15：`node_history.change_type TEXT`；`update_node()` 先插入 `node_history` 快照再 UPDATE，`version +1`
2. **`cli_knowledge.py`** `brain history <node_title_or_id>` 顯示版本清單；`brain restore <node_id> --version <N>` 還原指定版本

---

## P3 — 長期 / 低頻 / 實驗性

### 重構類

| ID | 問題 | 影響 | 解決方案 | 工時 | 備註 |
|----|------|------|---------|------|------|
| ~~REF-01~~ ✅ | ~~BrainDB ~1800 行，承擔 10+ 職責（God Object）~~ | 已解決 | 抽離 `VectorStore`（`vector_store.py`）+ `FeedbackTracker`（`feedback_tracker.py`）；BrainDB 以 delegation 模式保持 backward compat | 完成 | — |
| ~~CLI-01~~ ✅ | ~~`cli.py` 2864 行，31 個 `cmd_*` 函數全在同一檔案~~ | 已解決 | 拆分為 `cli_utils.py`、`cli_knowledge.py`、`cli_admin.py`、`cli_serve.py`、`cli_fed.py`；`cli.py` 精簡至 ≤500 行 | 完成 | — |
| ~~ARCH-04~~ ✅ | ~~scope 三路控制流（`--global` / `--scope` / 自動推斷）讓使用者困惑~~ | 已解決 | `--global` 保留但印棄用警告（stderr），導引使用 `--scope global` | 完成 | — |
| ~~REF-04~~ ✅ | ~~魔法數字散落（`0.003`、`800`、`400`、`limit=8`）~~ | 已解決 | `project_brain/constants.py`；四個常數集中定義 | 完成 | — |

### 修正類

| ID | 問題 | 影響 | 解決方案 | 工時 | 備註 |
|----|------|------|---------|------|------|
| ~~PERF-03~~ ✅ | ~~CJK token 計數逐字迭代，無快取~~ | 已解決 | `@lru_cache(maxsize=1024)` 加到 `_count_tokens()` | 完成 | — |
| ~~BUG-A03~~ ✅ | ~~`engine.py` 共用鎖競態死鎖~~ | 已解決 | 每個屬性獨立 `threading.Lock()` | 完成 | — |
| ~~PERF-04~~ ✅ | ~~Synonym 擴展 `EXPAND_LIMIT=15` 為固定值~~ | 已解決 | 動態調整：詞數 < 3 → 10；3–5 → 15；> 5 → 20 | 完成 | — |
| ~~FEAT-03~~ ✅ | ~~`temporal_query` MCP 工具有框架，無有效時間過濾邏輯~~ | 已解決 | `nodes_at_time()`；SCHEMA_VERSION=19；`brain history --at` CLI | 完成 | — |

### 功能深化類

| ID | 問題 | 影響 | 解決方案 | 工時 | 備註 |
|----|------|------|---------|------|------|
| ~~**P2**~~ ✅ | ~~DEEP-04~~ | 低信心節點無確認機制，知識庫品質停滯 | AI 自動裁決（rule-based + LLM-assisted）取代人工確認；`auto_resolve_knowledge()` MCP tool；`get_context()` 背景靜默執行 rule-based auto-resolve | 無 | 設計調整：系統目標是讓 AI 自主運作，應大量減少人工介入 |
| ~~FED-01~~ ✅ | ~~Federation 導入無審計日誌~~ | 已解決 | `federation_imports` 表（source/node_id/imported_at/status）；`brain fed imports`→`cmd_fed_import_list()`；`brain_db.get_federation_imports()` | 完成 | — |
| ~~FED-02~~ ✅ | ~~Federation 去重只用 Jaccard~~ | 已解決 | `_is_duplicate()` 組合 Jaccard + TF-IDF cosine similarity（sklearn，threshold=0.82）；chromadb 可用時自動升級為向量比對 | 完成 | — |
| ~~CLI-02~~ ✅ | ~~CLI `brain fed sync` 未實裝~~ | 已解決 | `brain fed sync/export/import/subscribe/unsubscribe/imports` 全部在 `cli_fed.py` 實裝 | 完成 | — |
| ~~FEAT-04~~ ✅ | ~~Session 結束 L1a 全部清空~~ | 已解決 | `SessionStore.archive()`；導出 `.brain/sessions/<id>.md`；90 天自動清理；`brain session archive/list`（`cmd_session()`） | 完成 | — |

### 可觀測性類

| ID | 問題 | 影響 | 解決方案 | 工時 | 備註 |
|----|------|------|---------|------|------|
| ~~OBS-01~~ ✅ | ~~系統運行時難以觀察~~ | 已解決 | structlog 結構化日誌（`{event, node_id, reason, old_val, new_val}`）；`GET /v1/metrics` Prometheus 格式（`brain_nodes_total`、`brain_decay_count`、`brain_nudge_trigger_rate`、`brain_context_tokens_avg`） | 完成 | — |

---

## 版本路線圖

| 版本 | 主題 | 主要工作 | 發布 Gate |
|------|------|---------|----------|
| **v0.7.0** ✅ | 正確性優先 | ~~BUG-B02~~✅、~~BUG-B01~~✅、~~REF-04~~✅、~~PERF-03~~✅、~~BUG-A03~~✅、~~PERF-04~~✅ | 所有測試通過；Chaos 100%；召回率 ≥ 60% |
| **v0.8.0** ✅ | 知識自適應 | ~~DEEP-05~~（F6 採用率）、~~ARCH-05~~（弃用流程）、~~ARCH-06~~（ConflictResolver）、~~FEAT-01~~（版本控制）| 採用率反饋閉環可驗證；deprecated 流程有 CLI 入口；ConflictResolver 保守策略通過測試 |
| **v0.9.0** ✅ | 深化功能 | ~~DEEP-04~~（AI 自動裁決）✅、~~FED-01~~+~~FED-02~~（Federation 強化）✅、~~OBS-01~~（可觀測性）✅、~~CLI-02~~（fed sync CLI）✅、~~FEAT-04~~（session archive）✅ | auto-resolve 採纳率可量測；federation 審計可追蹤；structlog 覆蓋所有核心流程 |
| **v0.10.0** ✅ | 長期穩定 | ~~REF-01~~（BrainDB 拆分）✅、~~CLI-01~~（cli.py 拆分）✅、~~ARCH-04~~（scope UX）✅ | cli.py = 240 行 ✅（目標 ≤500）；parser 抽至 cli_utils._build_parser() |
| **v0.11.0** ✅ | AI 全自主 | ~~KRB-01~~（自主審核）✅：AI 全自動裁決 + 知識來源初始信心差異化；人退出關鍵路徑 | ✅ 完成 |

---

## 架構診斷摘要（2026-04-04）

基於完整原始碼分析，系統各層實作完整度：

| 層 / 模組 | 實作完整度 | 最大缺口 |
|----------|-----------|---------|
| L1a SessionStore | ✅ 完整 | ~~FEAT-04~~ ✅ Session archive 已實裝 |
| L2 Episodes / Temporal | ✅ 完整 | ~~FEAT-03~~ ✅ `nodes_at_time()`；`brain history --at` |
| L3 KnowledgeGraph | ✅ 完整 | — |
| BrainDB（統一儲存） | ✅ 完整 | v14-v17 遷移：version/change_type/deprecated_at/adoption_count |
| DecayEngine（衰減） | ✅ 7/7 因子 | F6 採用率 ✅；ARCH-05 deprecated 流程 ✅；ARCH-06 CONFLICTS_WITH ✅ |
| ContextEngineer | ✅ 完整 | `[已棄用]` 標記 ✅ |
| NudgeEngine | ✅ 完整 | `auto_resolve_batch()` ✅；rule-based + LLM-assisted；get_context 背景觸發 |
| ConflictResolver | ✅ 完整 | LLM/Ollama 仲裁 + CONFLICTS_WITH edges ✅ |
| Federation | ✅ 完整 | ~~FED-01~~ ✅ 審計日誌；~~FED-02~~ ✅ 語義去重；~~CLI-02~~ ✅ fed sync/imports CLI |
| KRB（知識審核） | ✅ 完整 | ~~KRB-01~~ ✅ AI 全自動裁決；source-based confidence；audit log |
| MCP Server | ✅ 完整 | report_outcome → graph.increment_adoption() 串聯 ✅ |
| API Server | ✅ 完整 | `GET /v1/knowledge/deprecated` ✅ |
| CLI | ✅ 主命令完整 | `brain history/restore/deprecated/session/fed` ✅；~~CLI-02~~ ✅ |
| 可觀測性 | ✅ 完整 | ~~OBS-01~~ ✅ 結構化日誌 + `GET /v1/metrics` Prometheus 端點 |
