# Project Brain — 改善規劃書

> **當前版本**：v0.8.0（2026-04-04）
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
| **P2** | DEEP-04 | 信心 < 0.5 的節點缺乏人工確認機制 | `context.build()` 附加 QUESTIONS 區塊；MCP `answer_question(node_id, answer)` tool | DEEP-05 | 📋 計劃執行 | 主動學習依賴反饋閉環（DEEP-05）先就位 |
| ~~**P2**~~ ✅ | ~~FED-01~~ | 跨庫導入無溯源，無法查「誰何時導入了什麼」 | `federation_imports` 表；`brain fed imports list/approve/reject` | 無 | ✅ 完成 | FED-02 和 CLI-02 的前置條件 |
| ~~**P2**~~ ✅ | ~~FED-02~~ | Jaccard 去重無法偵測語義近似知識，知識庫膨脹 | `_is_duplicate()` 組合 Jaccard OR 向量相似度（threshold=0.9） | FED-01 | ✅ 完成 | 需向量化依賴可用；搭配 FED-01 同步發布 |
| ~~**P2**~~ ✅ | ~~CLI-02~~ | `sync_all()` 完成但無 CLI 入口，VISION-03 無法使用 | `brain fed sync/export/import/subscribe/unsubscribe` | FED-01 | ✅ 完成 | 補全 Federation 最後一哩路 |
| ~~**P2**~~ ✅ | ~~FEAT-04~~ | L1a session 結束清空，長工作階段洞察遺失 | `SessionStore.archive()`；導出 `.brain/sessions/<id>.md`；90 天自動清理 | 無 | ✅ 完成 | 低頻場景，有餘力時處理 |
| **P2** | FEAT-03 | `temporal_query` 只有骨架，無時間過濾邏輯 | `valid_from`/`valid_until` 欄位；從 git log 推斷有效期；`brain history --at <date>` | 無 | 🔵 填空 | 邊界場景，需 git 整合 |
| **P3** | REF-01 | BrainDB ~1800 行承擔 10+ 職責（God Object） | 逐步抽離 `VectorStore`、`FeedbackTracker` | 覆蓋率≥70% | 🏗 長期 | 前置條件未達標前不動刀 |
| **P3** | CLI-01 | `cli.py` 2864 行，31 個函數無法維護 | 按功能拆分子模組；抽取 `@require_brain_dir` 裝飾器 | 整合測試 | 🏗 長期 | 先補整合測試再拆分 |
| **P3** | ARCH-04 | scope 三路控制流讓使用者困惑 | 合併 `--global`/`--scope` 為單一 `--scope global` | major 版本 | 🏗 長期 | Breaking change，配合 v2.0.0 |
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

覆蓋率≥70% ──→ REF-01 ──→ CLI-01
major 版本  ──→ ARCH-04
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

### REV-02 — Decay 實際效用未量測

無法驗證衰減是幫助還是傷害召回率。對比有/無衰減知識庫；統計過時節點排前 3 的比例。△ 需 90 天以上數據。

詳見 `tests/TEST_PLAN.md` § 7 — REV-02 衰減效用量測

---

### DEEP-05 — Decay F6 採用率反饋缺失（知識自學習閉環）

**問題**：`decay_engine.py` 設計了 F1–F7 共 7 個衰減因子，但 **F6（採用率反饋）完全未實裝**。每次 Agent 使用知識後，系統無法知道這條知識是否有幫助；有用的知識無法被獎勵，無效知識無法被懲罰，整個知識庫是「靜態評分」而非「自適應評分」。

**實際影響**：
- `report_knowledge_outcome(node_id, was_useful)` 的 MCP 呼叫結果未被 Decay Engine 消費
- 長期使用後，高品質知識和低品質知識的 confidence 分佈無差異
- 知識庫喪失「越用越聰明」的核心能力

**修復方案**：
1. `brain_db.py` 新增 `record_outcome(node_id, was_useful: bool)`：`was_useful=True` → `meta.adoption_count += 1`，`confidence = min(1.0, confidence + 0.03)`；`was_useful=False` → `confidence = max(DECAY_FLOOR, confidence - 0.05)`
2. `decay_engine.py` 新增 `_factor_adoption(node)` → `F6 = min(1.2, 1 + adoption_count * 0.02)`（最多 +20% 加成）
3. `mcp_server.py` 確認 `report_knowledge_outcome` tool 正確呼叫 `record_outcome()`（現在只呼叫 `mark_helpful`）
4. REST 端點補充：`POST /v1/knowledge/<node_id>/outcome`

**工時**：1.5 天

---

### ARCH-05 — 弃用流程缺失（deprecated 節點無通知 / 清理路徑）

**問題**：`decay_engine.py` 當節點 confidence < 0.20 時標記 `meta.deprecated=True`，但此後完全沒有業務流程：
- 弃用節點仍被 `get_context` 正常推薦（Pitfall 類型節點甚至衰減後更危險，因為它們是錯誤建議）
- 無任何通知機制（webhook / nudge）
- 無保留期（deprecated → 軟刪除 → 硬刪除），節點永不被清理

**實際影響**：
- 使用者不知道知識庫有多少「殭屍節點」（框架為 deprecated 但仍活躍推薦）
- `brain status` 的健康分數無法反映實際品質

**修復方案**：
1. **context.py** 推薦 deprecated 節點時加 `[已棄用]` 標記（不過濾，但明示）
2. **nudge_engine.py** 每次衰減執行後，對新增的 deprecated 節點觸發 `deprecated_node` 事件到 `events` 表
3. **brain_db.py** 新增 `deprecated_at` 欄位（v14 migration）；`_apply_decay()` 同步設置
4. **CLI** 新增 `brain deprecated list`（顯示所有 deprecated 節點及棄用時間）和 `brain deprecated purge --older-than <days>`（硬刪除超過指定天數的 deprecated 節點）
5. **api_server.py** 新增 `GET /v1/knowledge/deprecated` 端點

**工時**：2 天

---

### ARCH-06 — ConflictResolver 實裝（VISION-02 矛盾仲裁）

**問題**：`decay_engine.py` 中已有完整的呼叫骨架：

```python
if os.environ.get("BRAIN_CONFLICT_RESOLVE", "0") == "1":
    from project_brain.conflict_resolver import ConflictResolver
    _resolver = ConflictResolver(_bdb_cr, self.graph)
```

但 `project_brain/conflict_resolver.py` **完全不存在**。F4（矛盾檢測）只做關鍵字集合匹配（`contradicts`、`deprecated` 等詞），無法判斷語義層面的矛盾（「永遠使用 RS256」vs「支援 HS256」）。

**實際影響**：
- 知識庫規模 > 200 個節點後，矛盾節點比例顯著上升
- 矛盾節點對稱扣分（兩者均衰減），優勝劣汰機制失效
- `BRAIN_CONFLICT_RESOLVE=1` 的環境變數設置會導致 `ImportError`

**修復方案**：
1. 建立 `project_brain/conflict_resolver.py`：
   - `ConflictResolver(db, graph, llm_client=None)`
   - `resolve(node_a, node_b) → ArbitrationResult(winner_id, reason, confidence)`
   - 無 LLM：基於 confidence、created_at、adoption_count 數值仲裁（保守策略）
   - 有 LLM：呼叫 Claude 進行語義仲裁（需配置 `BRAIN_LLM_KEY`）
2. `edges` 表新增 `CONFLICTS_WITH` 關係類型，記錄矛盾對
3. F4 升級：偵測到矛盾後寫入 edges，仲裁後非對稱調整 confidence（winner 不懲罰，loser 乘 0.5）
4. `brain doctor` 新增矛盾節點數量報告

**工時**：3 天（保守策略版）；+2 天（LLM 仲裁版）

---

### FEAT-01 — 知識版本控制（節點歷史追蹤）

**問題**：`nodes` 表無版本欄位，`update_node()` 直接覆寫。修改一個節點後，歷史內容、原始信心值、修改原因全部消失。無法回答：「這條決策是從什麼時候開始說要用 JWT RS256 的？」

**實際影響**：
- 知識演變不可追溯
- 衰減到底是因為時間久還是因為主動降低？無法區分
- `brain restore` 指令無法實作（沒有歷史）

**注意**：`node_history` 表已存在（`DATA-01` 實作了刪除前的快照），但 **更新操作不寫歷史**，且無 version 欄位。

**修復方案**：
1. `nodes` 表新增 `version INTEGER DEFAULT 1`（v14 migration）
2. `update_node()` 改為：先插入 `node_history`（完整快照），再 UPDATE `nodes`，version +1
3. `node_history` 補充 `change_type TEXT`（`update` / `decay` / `feedback`）和 `change_note TEXT`
4. CLI 新增 `brain history <node_title_or_id>` 顯示版本清單
5. CLI 新增 `brain restore <node_id> --version <N>` 還原到指定版本

**工時**：1.5 天

---

## P3 — 長期 / 低頻 / 實驗性

### 重構類

| ID | 問題 | 影響 | 解決方案 | 工時 | 備註 |
|----|------|------|---------|------|------|
| REF-01 | BrainDB ~1800 行，承擔 10+ 職責（God Object） | 難以維護，重構前需測試覆蓋率 ≥ 70% | 逐步抽離：`VectorStore`（add/search vector）、`FeedbackTracker`（record_feedback）| 2 週+ | 前提：覆蓋率 ≥ 70% |
| CLI-01 | `cli.py` 2864 行，31 個 `cmd_*` 函數全在同一檔案 | 比 BrainDB 更大；每個命令函數重複 `_workdir + brain_dir.exists()` 樣板；`cmd_serve` 240 行、`cmd_doctor` 378 行 | 按功能群組拆分：`cli_serve.py`、`cli_admin.py`、`cli_knowledge.py` 等；抽取 `@require_brain_dir` 裝飾器消除樣板 | 1.5 週 | 先補整合測試覆蓋率，再拆分 |
| ARCH-04 | scope 三路控制流（`--global` / `--scope` / 自動推斷）讓使用者困惑 | UX 複雜，Breaking change | 合併 `--global` / `--scope` 為單一 `--scope global`；保留自動推斷 | 1 週 | Breaking change，需 major 版本 |
| REF-04 | 魔法數字散落（`0.003`、`800`、`400`、`limit=8`） | 維護時難以追蹤意圖，修改需同步多處 | 新增 `project_brain/constants.py`，遷入四個常數 | 半天 | 📋 `tests/unit/test_ref04_constants.py` |

### 修正類

| ID | 問題 | 影響 | 解決方案 | 工時 | 備註 |
|----|------|------|---------|------|------|
| PERF-03 | CJK token 計數逐字迭代，無快取 | 高頻呼叫時浪費 CPU（800+ 次/request） | `_count_tokens()` 加 `@lru_cache(maxsize=1024)` | 30 分 | 📋 `tests/unit/test_perf03_token_cache.py` |
| BUG-A03 | `engine.py` 6 個懶加載屬性共用 `_init_lock`（非可重入）| 極低概率競態：雙重初始化 + 鏈式呼叫死鎖 | 拆分為各屬性獨立 `threading.Lock()` | 1 小時 | 📋 `tests/unit/test_bug_a03_locking.py` |
| PERF-04 | Synonym 擴展 `EXPAND_LIMIT=15` 為固定值 | 短查詢過度擴展引入噪音；長查詢不足遺漏知識 | 動態調整：詞數 < 3 → 上限 10；3–5 詞 → 15；> 5 詞 → 20；`BRAIN_EXPAND_MODE` env var 控制 | 半天 | context.py `_expand_query()` |
| FEAT-03 | `temporal_query` MCP 工具有框架，無有效時間過濾邏輯 | 無法回答「v0.3.0 時這條知識是否有效」 | 從 git log 推斷節點有效期；實作 `valid_from`/`valid_until` 過濾；`brain history --at <date>` 時間機器 | 4 天 | 需 git 整合 |

### 功能深化類

| ID | 問題 | 影響 | 解決方案 | 工時 | 備註 |
|----|------|------|---------|------|------|
| ~~**P2**~~ ✅ | ~~DEEP-04~~ | 低信心節點無確認機制，知識庫品質停滯 | AI 自動裁決（rule-based + LLM-assisted）取代人工確認；`auto_resolve_knowledge()` MCP tool；`get_context()` 背景靜默執行 rule-based auto-resolve | 無 | 設計調整：系統目標是讓 AI 自主運作，應大量減少人工介入 |
| FED-01 | Federation 導入無審計日誌，無法溯源「哪個專案、何時、匯入了什麼」 | 多知識庫聯邦場景下責任不清晰 | 新增 `federation_imports` 表（source / node_id / imported_at / status）；`brain fed imports list/approve/reject`；REST `GET /v1/federation/imports` | 3 天 | 前提：Federation 被積極使用 |
| FED-02 | Federation 去重只用 Jaccard 集合匹配，無法偵測語義重複 | 批量匯入造成語義近似的知識膨脹（「JWT RS256」vs「RS256 JWT 驗證」） | chromadb 可用時加語義相似度比對（threshold=0.9）；`FederationImporter._is_duplicate()` 組合 Jaccard OR 向量相似度 | 2 天 | 需向量化依賴可用 |
| CLI-02 | `federation.py` 的 `sync_all()` 完成，CLI `brain fed sync` 未實裝 | Federation 自動同步功能（VISION-03）無入口 | `cmd_fed_sync()`：`brain fed sync [--dry-run] [--confidence 0.5]`；`brain fed export/import/subscribe/unsubscribe` | 2 天 | 搭配 FED-01 |
| FEAT-04 | Session 結束時 L1a 全部清空，可能丟失工作階段洞察 | 長時間工作的中間結論無法保留 | `SessionStore.archive()`：導出當前 session 為 `.brain/sessions/<id>.md`；`brain session archive [--session <id>]`；90 天後自動清理 | 1.5 天 | 低頻場景 |

### 可觀測性類

| ID | 問題 | 影響 | 解決方案 | 工時 | 備註 |
|----|------|------|---------|------|------|
| OBS-01 | 系統運行時難以觀察：Decay 為何降低信心？Context 為何沒推薦某知識？Nudge 的觸發率是多少？ | 問題難重現，調優無依據 | 結構化日誌（structlog）記錄 `{event, node_id, reason, old_val, new_val}`；新增 `GET /v1/metrics`（Prometheus 格式）涵蓋 `brain_nodes_total`、`brain_decay_count`、`brain_nudge_trigger_rate`、`brain_context_tokens_avg` | 3 天 | 可分兩步：先 structlog，再 Prometheus |

---

## 版本路線圖

| 版本 | 主題 | 主要工作 | 發布 Gate |
|------|------|---------|----------|
| **v0.7.0** ✅ | 正確性優先 | ~~BUG-B02~~✅、~~BUG-B01~~✅、~~REF-04~~✅、~~PERF-03~~✅、~~BUG-A03~~✅、~~PERF-04~~✅ | 所有測試通過；Chaos 100%；召回率 ≥ 60% |
| **v0.8.0** ✅ | 知識自適應 | ~~DEEP-05~~（F6 採用率）、~~ARCH-05~~（弃用流程）、~~ARCH-06~~（ConflictResolver）、~~FEAT-01~~（版本控制）| 採用率反饋閉環可驗證；deprecated 流程有 CLI 入口；ConflictResolver 保守策略通過測試 |
| **v0.9.0** ✅ | 深化功能 | ~~DEEP-04~~（AI 自動裁決）✅、~~FED-01~~+~~FED-02~~（Federation 強化）✅、~~OBS-01~~（可觀測性）✅、~~CLI-02~~（fed sync CLI）✅、~~FEAT-04~~（session archive）✅ | auto-resolve 採纳率可量測；federation 審計可追蹤；structlog 覆蓋所有核心流程 |
| **v1.0.0** | 長期穩定 | REF-01（BrainDB 拆分）、CLI-01（cli.py 拆分）、ARCH-04（scope UX）| 覆蓋率 ≥ 70%；BrainDB ≤ 800 行；cli.py ≤ 500 行 |

---

## 架構診斷摘要（2026-04-04）

基於完整原始碼分析，系統各層實作完整度：

| 層 / 模組 | 實作完整度 | 最大缺口 |
|----------|-----------|---------|
| L1a SessionStore | ✅ 完整 | ~~FEAT-04~~ ✅ Session archive 已實裝 |
| L2 Episodes / Temporal | ⚠️ 框架完成 | temporal_query 邏輯空缺（FEAT-03）|
| L3 KnowledgeGraph | ✅ 完整 | — |
| BrainDB（統一儲存） | ✅ 完整 | v14-v17 遷移：version/change_type/deprecated_at/adoption_count |
| DecayEngine（衰減） | ✅ 7/7 因子 | F6 採用率 ✅；ARCH-05 deprecated 流程 ✅；ARCH-06 CONFLICTS_WITH ✅ |
| ContextEngineer | ✅ 完整 | `[已棄用]` 標記 ✅ |
| NudgeEngine | ✅ 完整 | `auto_resolve_batch()` ✅；rule-based + LLM-assisted；get_context 背景觸發 |
| ConflictResolver | ✅ 完整 | LLM/Ollama 仲裁 + CONFLICTS_WITH edges ✅ |
| Federation | ✅ 完整 | ~~FED-01~~ ✅ 審計日誌；~~FED-02~~ ✅ 語義去重；~~CLI-02~~ ✅ fed sync/imports CLI |
| MCP Server | ✅ 完整 | report_outcome → graph.increment_adoption() 串聯 ✅ |
| API Server | ✅ 完整 | `GET /v1/knowledge/deprecated` ✅ |
| CLI | ✅ 主命令完整 | `brain history/restore/deprecated/session/fed` ✅；~~CLI-02~~ ✅ |
| 可觀測性 | ✅ 完整 | ~~OBS-01~~ ✅ 結構化日誌 + `GET /v1/metrics` Prometheus 端點 |
