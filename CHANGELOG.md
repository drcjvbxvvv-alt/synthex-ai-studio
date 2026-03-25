## [v1.1.0] - 2026-03-25

### 🚀 新增 Project Brain — SYNTHEX 知識積累子系統

這是一項重大的架構升級，旨在解決工程師離職與專案交接造成的知識流失問題。Project Brain 透過自動記錄與結構化，讓 AI 能夠隨時帶著完整的專案記憶進行開發。

#### 🧠 核心概念與三層次知識模型

- **自動知識積累：** 系統能從 Git 提交、PR、Issue 與程式碼中自動擷取知識，並將其轉化為專案資產。
- **向量記憶（陳述性記憶）：** 用於儲存與搜尋相關的顯性知識片段。
- **知識圖譜（情節記憶）：** 記錄系統組件、踩坑經驗、業務規則與架構決策之間的因果關係，支援衝擊分析與路徑查詢。
- **結構化 ADR（程序性記憶）：** 留存技術決策記錄，重現歷史決策過程。

#### 🛠 技術架構與實作

- **Knowledge Graph：** 採用無外部依賴的 SQLite + FTS5，提供嵌入式的圖節點儲存與全文搜尋能力。
- **Knowledge Extractor：** 整合 `claude-sonnet-4-5` API，透過非同步 Git Hook 在背景自動執行知識提取，兼顧語義理解品質與成本預算。
- **Context Engineer：** 負責在 AI 執行任務前，動態評估預算並依序注入最相關的「踩坑記錄」、「業務規則」與「架構決策」，確保 Context Window 的精準度。
- **Project Archaeologist：** 針對缺乏文件記錄的舊專案提供「考古」功能，透過掃描目錄結構、Git 歷史與程式碼（如 TODO/FIXME 註解）來自動重建知識圖譜。

#### ⌨️ 新增 CLI 指令支援

- 新增 `synthex brain init`：初始化新專案的圖譜與自動學習機制。
- 新增 `synthex brain scan`：一鍵執行舊專案考古掃描並產出 `SCAN_REPORT.md`。
- 新增 `synthex brain context "任務描述"`：為 AI 任務動態產生關聯背景知識。
- 支援狀態查詢 (`status`)、手動知識錄入 (`add`)、從特定 commit 學習 (`learn`) 以及視覺化匯出 Mermaid 圖譜 (`export`)。
