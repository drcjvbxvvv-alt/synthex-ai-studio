# Project Brain — 改善規劃書

> **當前版本**：v0.2.0（2026-04-03）
> **文件用途**：記錄未來改善方向、技術債、功能規劃。每個版本迭代前更新。
> **參考文件**：`ProjectBrain_Enterprise_Analysis.docx.md`（2026.04 企業級產品價值分析）

---

## 優先等級定義

| 等級 | 說明 | 目標版本 |
|------|------|---------|
| **P0** | 阻礙核心功能運作的缺陷，須立即修復 | 下一個 patch |
| **P1** | 影響使用者體驗的問題，應優先處理 | 下一個 minor |
| **P2** | 值得做但可延後的優化 | 計劃中 |
| **P3** | 長期願景、實驗性功能 | 評估中 |

---

## 已知問題（Bugs）

| ID | 等級 | 描述 | 狀態 |
|----|------|------|------|
| BUG-01 | P0 | `engine.py` `context_engineer`/`review_board` 屬性在 `_init_lock` 內部再次嘗試獲取同一鎖，造成死鎖，`brain status` 完全無回應 | ✅ 已修復（2026-04-03） |
| BUG-02 | P1 | `status_renderer.py` v10 區塊引用未定義的 `db` 變數（被 try/except 靜默吞掉），節點/邊數量不顯示 | ✅ 已修復（2026-04-03） |

---

## 致命缺陷（Fatal Flaws）

> 以下三個問題不是「待改善的功能」，是「讓整個系統失去意義的根本矛盾」。

### F1：知識生產迴路斷裂（P0）

知識庫的價值完全取決於豐富程度，但目前 100% 依賴人工 `brain add`。
CLAUDE.md 只有 8 行通用指令，沒有任何 Brain 行為協議，導致：

- Agent 不會在任務開始前主動呼叫 `get_context()`
- Agent 不會在任務結束後呼叫 `add_knowledge()` 寫入學習
- 沒有知識有效性回饋迴路（knowledge 好不好用沒有閉合）
- `extractor.py` 只從 commit message 提取，不捕捉過程中的決策與踩坑

**解法方向**：重寫 CLAUDE.md 生成邏輯 + 新增 MCP 工具 `complete_task` / `report_knowledge_outcome` + session-aware extractor。

### F2：沒有可度量的 ROI（P1）

企業採購需要能回答「這個工具幫我省了幾小時、避免了幾個 bug」。
目前 Brain 無法提供任何 ROI 數據。Nudge 有沒有阻止 bug 發生、get_context 返回的知識有沒有被用到——完全不知道。

**解法方向**：新建 `analytics_engine.py` + `brain report` 指令 + Web UI dashboard 強化。

### F3：`core/` 雙重程式碼庫是維護炸彈（P1）

`core/brain/` 和 `project_brain/` 幾乎是同一套模組的兩個副本。
任何功能改動都必須在兩個地方做，任何 bug 修復都必須記得應用兩次。
外部貢獻者看到這個結構會立刻失去信心。

**解法方向**：保留 `project_brain/` 為唯一來源，`core/brain/` 改為從它導入（thin adapter）。

---

## 技術債

| ID | 等級 | 模組 | 描述 |
|----|------|------|------|
| TD-01 | P2 | `context.py` | `_SYNONYM_MAP` 硬編碼中文同義詞，應改為可從 `.brain/synonyms.json` 載入 |
| TD-02 | P2 | `embedder.py` | LocalTFIDF 的 hash 投影維度（256）固定，應可透過環境變數調整 |
| TD-03 | P2 | `graph.py` | `add_edge()` 尚未支援批次操作，大量 edges 逐筆 INSERT 效能差 |
| TD-04 | P3 | `decay_engine.py` | F2 技術版本落差偵測規則硬編碼（React 16/18 等），無法自訂 |
| TD-05 | P1 | `core/brain/` | 與 `project_brain/` 幾乎完全重複，應降格為薄整合層（對應 F3） |
| TD-06 | P1 | `pyproject.toml` | version 欄位為 0.1.0，與實際 `__version__` 0.2.0 不一致；URLs 仍為模板佔位 |
| TD-07 | P1 | `status_renderer.py` | L246 引用未定義的 `db` 變數（被 try/except 靜默吞掉），v10 區塊功能失效 |

---

## 功能規劃

### Phase 0（立即，1-2 週）：堵漏洞

> 在做任何新功能之前，先把現有漏洞堵上。

| ID | 等級 | 功能 | 說明 |
|----|------|------|------|
| PH0-01 | P1 | `pyproject.toml` 修正 | version → 0.2.0，URLs 改為真實 GitHub 連結（對應 TD-06） | ✅ 2026-04-03 |
| PH0-02 | P1 | `core/` 目錄重組 | 移除業務邏輯，改為從 `project_brain/` 導入（對應 F3/TD-05） | ✅ 2026-04-03（已是 shim，更新 docstring 與邊界規則） |
| PH0-03 | P1 | `CONTRIBUTING.md` 更新 | 說明 `core/` vs `project_brain/` 的邊界，防止貢獻者寫錯地方 | ✅ 2026-04-03 |
| PH0-04 | P1 | 測試覆蓋補全 | 至少為 CLI 核心命令（init、add、ask）補充整合測試 | ✅ 2026-04-03（`tests/integration/test_cli.py`，13 個無 Mock 端對端測試，全數通過） |
| PH0-05 | P1 | `status_renderer.py` 修正 | 修復 `db` 未定義問題（TD-07），讓 v10 區塊正確顯示 | ✅ 2026-04-03 |

### Phase 1（4-6 週）：修復知識生產迴路（對應 F1）

> 這是整個路線圖最高優先級的工作。一個正確的 CLAUDE.md，讓知識生產從「需要人工記得去做」變成「每次任務完成後自動發生」。

| ID | 等級 | 功能 | 說明 |
|----|------|------|------|
| PH1-01 | P0 | 重寫 CLAUDE.md 生成模板 | `setup_wizard.generate_claude_md()` 含完整 Brain 行為協議：Task Start / Task Complete / Knowledge Feedback，全英文 | ✅ 2026-04-03 |
| PH1-02 | P0 | MCP 工具：`complete_task` | 參數：`task_description, decisions[], lessons[], pitfalls[]`；任務結束後批次寫入本次學習 | ✅ 2026-04-03 |
| PH1-03 | P0 | MCP 工具：`report_knowledge_outcome` | 參數：`node_id, was_useful, notes`；閉合知識有效性的回饋迴路，驅動 confidence 動態更新 | ✅ 2026-04-03 |
| PH1-04 | P1 | 強化 `extractor.py` | Session-aware 提取：從 git diff + session log 中提取「過程知識」，不只依賴 commit message | ✅ 2026-04-03（新增 `from_session_log()` 無 LLM 直接轉換 + `from_git_diff_staged()`） |
| PH1-05 | P1 | `analytics_engine.py` 基礎版 | 記錄所有查詢事件、命中率、使用者回饋（explicit + implicit） | ✅ 2026-04-03（新建 `analytics_engine.py`：ROI score、query hit rate、useful knowledge rate、pitfall avoidance score） |
| PH1-06 | P1 | `brain report` 指令 | 生成週期性使用統計，顯示知識庫健康度基本指標 | ✅ 2026-04-03（`brain report [--days N] [--format json] [--output file]`，ROI + 使用率 + Top Pitfalls 一頁報告） |

### Phase 2（6-12 週）：ROI 可見化（對應 F2）

| ID | 等級 | 功能 | 說明 |
|----|------|------|------|
| PH2-01 | P1 | Web UI dashboard 強化 | 顯示 ROI 指標、知識庫健康度、最高效益 Pitfall 節點、Nudge Effectiveness Rate | ✅ 2026-04-03（`/api/analytics` 端點，回傳 ROI + usage + top_pitfalls JSON） |
| PH2-02 | P1 | `brain search` 指令 | 純語意搜尋（不組裝 Context），快速查特定知識 | ✅ 2026-04-03（`brain search <keywords> [--limit N] [--kind TYPE] [--scope S] [--format json]`） |
| PH2-03 | P2 | `brain add` 互動模式 | 無參數執行時進入互動式輸入（title / kind / scope 分步問） |
| PH2-04 | P2 | `brain export --format markdown` | 匯出為人類可讀 Markdown，方便放進 wiki / Confluence |
| PH2-05 | P2 | 同義詞設定檔 | `.brain/synonyms.json`，讓台灣業務術語可自定義（對應 TD-01） |
| PH2-06 | P2 | GitHub Issues / Linear 整合 | 追蹤 Nudge 警告 → bug 開單的相關性，建立可歸因的 ROI 數據 |
| PH2-07 | P2 | `brain ask --json` | 輸出結構化 JSON，方便腳本串接 |

### Phase 3（12-20 週）：建立護城河

| ID | 等級 | 功能 | 說明 |
|----|------|------|------|
| PH3-01 | P2 | `federation.py` | 跨專案知識分享協議；public scope 知識池；訂閱特定技術領域更新 |
| PH3-02 | P2 | `knowledge_distiller.py` Layer 3 完工 | LoRA fine-tuning pipeline；Axolotl / Unsloth 整合；讓組織知識蒸餾進私有模型，不佔 context window |
| PH3-03 | P2 | AI 輔助 KRB 審核 | 由 Claude Haiku 輔助審核自動提取的知識，降低人工負擔 |
| PH3-04 | P3 | Cloud 版本 | 託管服務、Team 計畫（$20/月/開發者）、計費系統 |
| PH3-05 | P3 | ANN 向量索引 | sqlite-vec HNSW 索引，大型知識庫（5000+ 節點）搜尋 O(log N) |
| PH3-06 | P3 | 多語言 embedding | 支援 multilingual-e5 等多語言模型，中英混搜 |

### 長期願景（v1.0+）

| ID | 等級 | 功能 | 說明 |
|----|------|------|------|
| VISION-01 | P3 | 動態 confidence 更新 | Agent 執行後自動回饋知識節點是否有效，confidence 動態調整（部分由 PH1-03 實現） |
| VISION-02 | P3 | 知識衝突自動解決 | 偵測到矛盾知識時，透過 LLM 輔助仲裁而非雙方懲罰 |
| VISION-03 | P3 | 跨專案知識遷移 | 將 A 專案的通用規則推送到 B 專案（scope=global），組成聯邦知識網路 |
| VISION-04 | P3 | 唯讀共享模式 | `brain serve --readonly` 讓團隊成員查詢但不能修改 |
| VISION-05 | P3 | 多知識庫合併查詢 | 同時查詢多個專案的 `.brain/`（monorepo 場景） |

---

## 架構約束（修改前必讀）

修改核心模組前需遵守以下約束，詳細設計見 `docs/BRAIN_MASTER.md`：

| 約束 | 說明 |
|------|------|
| **SQLite 單寫者** | 不使用多進程並行寫入，用 WAL + `busy_timeout=5000` 處理競爭 |
| **per-thread connections** | `graph.py` 和 `session_store.py` 均使用 `threading.local()`，不跨 thread 共享連線 |
| **鎖重入禁止** | `engine.py` 的 `_init_lock` 是非可重入鎖（`threading.Lock`）；在持鎖狀態下不得呼叫其他需要同一鎖的屬性（見 BUG-01） |
| **KRB 人工把關** | AI 自動提取的知識必須先進 Staging，不直接入 L3 |
| **零外部依賴（核心）** | 核心功能只依賴 Python 標準函式庫 + SQLite，進階功能以 optional dep 形式提供 |
| **降級優先** | 任何功能失敗應靜默降級，不阻斷 Agent 運作 |
| **`project_brain/` 為唯一業務邏輯來源** | `core/brain/` 是薄整合層，修改業務邏輯永遠只改 `project_brain/` |

---

## 版本決策記錄

| 版本 | 決策 | 理由 |
|------|------|------|
| v0.2.0 | `BRAIN_WORKDIR` 改為非必要（自動偵測為主） | 多專案工作流不應被環境變數綁死 |
| v0.2.0 | 查詢展開限每詞 3 個同義詞，總上限 15 | 原本 30 個同義詞造成大量無關結果 |
| v0.2.0 | `brain index` 改用 `_Spinner` 進度條 | 大型知識庫建立索引可能需數分鐘，靜默等待體驗差 |
| v0.1.0 | 使用 SQLite WAL 而非 PostgreSQL | 零依賴部署，備份 = 複製一個文件 |
| v0.1.0 | 知識衰減不刪除節點，只降低可見度 | 歷史記錄有考古價值，刪除不可逆 |

---

## 優先矩陣（Priority Matrix）

> 最後更新：2026-04-03

### 象限說明

| 象限 | 定義 |
|------|------|
| **Q1：立即執行** | 高影響 × 高緊迫（P0/P1，阻礙核心或影響使用者） |
| **Q2：計劃執行** | 高影響 × 可排期（P1/P2，重要但不緊急） |
| **Q3：批次處理** | 低影響 × 技術債清理（P2，快速可解決的瑣碎問題） |
| **Q4：暫緩或捨棄** | 低影響 × 低緊迫（P3，長期願景） |

### Q1 — 立即執行（高影響 × 高緊迫）

| ID | 等級 | 項目 | 狀態 |
|----|------|------|------|
| BUG-01 | P0 | `engine.py` 死鎖修復 | ✅ 已完成 |
| F1 / PH1-01 | P0 | 重寫 CLAUDE.md 生成模板（Brain 行為協議） | ✅ 已完成 |
| PH1-02 | P0 | MCP 工具：`complete_task` | ✅ 已完成 |
| PH1-03 | P0 | MCP 工具：`report_knowledge_outcome` | ✅ 已完成 |
| TD-05 / PH0-02 | P1 | `core/` 目錄重組為薄整合層 | ✅ 已完成 |
| TD-06 / PH0-01 | P1 | `pyproject.toml` 修正（version / URLs） | ✅ 已完成 |
| TD-07 / PH0-05 | P1 | `status_renderer.py` 修復 `db` 未定義 | ✅ 已完成 |
| BUG-02 | P1 | v10 區塊節點/邊數量不顯示 | ✅ 已完成 |
| PH0-03 | P1 | `CONTRIBUTING.md` 更新邊界說明 | ✅ 已完成 |
| PH0-04 | P1 | 整合測試補全（init / add / ask） | ✅ 已完成 |

### Q2 — 計劃執行（高影響 × 可排期）

| ID | 等級 | 項目 | Phase |
|----|------|------|-------|
| PH1-04 | P1 | 強化 `extractor.py`（session-aware） | ✅ 已完成 |
| PH1-05 | P1 | `analytics_engine.py` 基礎版 | ✅ 已完成 |
| PH1-06 | P1 | `brain report` 指令 | ✅ 已完成 |
| F2 / PH2-01 | P1 | Web UI dashboard ROI 指標強化 | ✅ 已完成 |
| PH2-02 | P1 | `brain search` 指令 | ✅ 已完成 |

### Q3 — 批次處理（低影響 × 技術債清理）

| ID | 等級 | 項目 | Phase |
|----|------|------|-------|
| TD-01 / PH2-05 | P2 | 同義詞設定檔 `.brain/synonyms.json` | Phase 2 |
| TD-02 | P2 | `embedder.py` 維度環境變數化 | Phase 2 |
| TD-03 | P2 | `graph.py` 批次 edge INSERT | Phase 2 |
| PH2-03 | P2 | `brain add` 互動模式 | Phase 2 |
| PH2-04 | P2 | `brain export --format markdown` | Phase 2 |
| PH2-06 | P2 | GitHub Issues / Linear 整合 | Phase 2 |
| PH2-07 | P2 | `brain ask --json` | Phase 2 |

### Q4 — 暫緩（長期願景）

| ID | 等級 | 項目 |
|----|------|------|
| TD-04 | P3 | `decay_engine.py` 版本落差規則可自訂 |
| PH3-01 | P2 | `federation.py` 跨專案知識分享 |
| PH3-02 | P2 | `knowledge_distiller.py` LoRA fine-tuning |
| PH3-03 | P2 | AI 輔助 KRB 審核 |
| PH3-04 | P3 | Cloud 版本 / 計費系統 |
| PH3-05 | P3 | ANN 向量索引 |
| PH3-06 | P3 | 多語言 embedding |
| VISION-01~05 | P3 | 動態 confidence、知識衝突解決、跨專案遷移… |

### 現況摘要

```
Q1 完成率：10/10（100%）✅
Q2 完成率：5/5（100%）✅
Q3 排隊中：7 項（技術債 + P2 功能）
Q4 暫緩：11 項（長期願景）
下一步行動：Q3 — TD-01/PH2-05 synonyms.json 同義詞設定檔
```

---

## 如何使用此文件

1. **發現問題** → 加入「已知問題」表格，標記等級
2. **想到新功能** → 加入對應 Phase 的功能規劃，標記等級
3. **開始實作某項** → 在描述後加 `🚧 進行中`
4. **完成** → 移至 `docs/COMPLETED_HISTORY.md`，更新 CHANGELOG.md
